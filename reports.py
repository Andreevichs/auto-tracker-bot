import sqlite3
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
from datetime import datetime, date
import calendar

# Средние цены на топливо в РБ (обновлять раз в месяц)
FUEL_PRICES = {
    'АИ-92': 2.50,
    'АИ-95': 2.60,
    'ДТ': 2.60
}

CATEGORIES = [
    "бензин", "дизель", "масло", "техосмотр", "налог", "ремонт",
    "страховка", "шиномонтаж", "моика", "прочее"
]

def calculate_fuel_efficiency(user_id, year, month):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT mileage FROM expenses
        WHERE user_id = ? AND strftime('%Y-%m', date) = ? AND mileage IS NOT NULL
        ORDER BY date
    ''', (user_id, f"{year}-{month:02d}"))
    mileages = [row[0] for row in cursor.fetchall() if row[0]]
    conn.close()

    if len(mileages) < 2:
        return None

    start_mileage = min(mileages)
    end_mileage = max(mileages)
    distance = end_mileage - start_mileage
    if distance <= 0:
        return None

    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT SUM(amount), fuel_type FROM expenses
        WHERE user_id = ? AND strftime('%Y-%m', date) = ? AND category IN ('бензин', 'дизель')
        GROUP BY fuel_type
    ''', (user_id, f"{year}-{month:02d}"))
    fuel_data = cursor.fetchall()
    conn.close()

    if not fuel_data:
        return None

    total_liters = 0
    for amount, fuel_type in fuel_data:
        price = FUEL_PRICES.get(fuel_type, 2.8)
        total_liters += amount / price

    consumption = (total_liters / distance) * 100
    return round(consumption, 1)

def get_fuel_advice(consumption, car_model):
    if consumption is None:
        return ""
    if consumption > 9.0:
        return "\n💡 Совет: проверьте давление в шинах и воздушный фильтр — это может снизить расход на 0.5 л/100 км."
    elif consumption > 7.5:
        return "\n💡 Ваш расход в норме. Продолжайте в том же духе!"
    else:
        return "\n🏆 Отличный результат! Ваш стиль вождения очень экономичный."

def generate_monthly_report(user_id, year, month):
    from database import get_expenses_by_month, get_user
    expenses = get_expenses_by_month(user_id, year, month)
    if not expenses:
        return "В этом месяце расходов не было."

    total = sum(e[0] for e in expenses)
    by_category = {cat: 0 for cat in CATEGORIES}
    for amount, cat, fuel_type, _ in expenses:
        key = fuel_type if cat in ['бензин', 'дизель'] and fuel_type else cat
        by_category[key] = by_category.get(key, 0) + amount

    # Сравнение с предыдущим месяцем
    prev_month = month - 1
    prev_year = year
    if prev_month == 0:
        prev_month = 12
        prev_year -= 1

    prev_expenses = get_expenses_by_month(user_id, prev_year, prev_month)
    prev_total = sum(e[0] for e in prev_expenses) if prev_expenses else 0

    if prev_total == 0:
        comparison = "— нет данных за предыдущий месяц"
    elif total < prev_total:
        diff = prev_total - total
        comparison = f"Вы сэкономили **{diff:.0f} Br** по сравнению с прошлым месяцем!"
    else:
        diff = total - prev_total
        comparison = f"Расходы выросли на **{diff:.0f} Br** по сравнению с прошлым месяцем."

    text = f"📅 Отчёт за {month}.{year}\n\n"
    text += f"💰 Всего потрачено: **{total:.0f} Br**\n\n"
    
    for key, amount in by_category.items():
        if amount > 0:
            text += f"• {key.capitalize()}: {amount:.0f} Br\n"
    
    # Расход топлива
    efficiency = calculate_fuel_efficiency(user_id, year, month)
    if efficiency:
        text += f"\n⛽ Средний расход: **{efficiency} л/100 км**"
        user = get_user(user_id)
        advice = get_fuel_advice(efficiency, user['car_model'] if user else "")
        text += advice
    
    text += f"\n\n{comparison}"
    return text

def generate_chart(user_id):
    from database import get_last_months, get_expenses_by_month
    months = get_last_months(user_id, 6)
    if len(months) < 2:
        return None

    totals = []
    labels = []
    for ym in sorted(months):
        year, month = map(int, ym.split('-'))
        expenses = get_expenses_by_month(user_id, year, month)
        totals.append(sum(e[0] for e in expenses))
        labels.append(f"{month}.{str(year)[-2:]}")

    plt.figure(figsize=(8, 5))
    bars = plt.bar(labels, totals, color='#1E88E5')
    plt.title("Расходы по месяцам (Br)", fontsize=14, pad=20)
    plt.ylabel("Сумма, Br", fontsize=12)
    plt.xticks(rotation=0)
    
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height + max(totals)*0.01,
                 f'{height:.0f}', ha='center', va='bottom', fontsize=10)

    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

def export_to_excel(user_id):
    from database import get_expenses_by_month
    import openpyxl
    from openpyxl.styles import Font
    from io import BytesIO

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Расходы"

    headers = ["Дата", "Категория", "Тип топлива", "Сумма (Br)", "Пробег"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    all_expenses = []
    for year in range(2020, date.today().year + 1):
        for month in range(1, 13):
            expenses = get_expenses_by_month(user_id, year, month)
            for amount, cat, fuel_type, mileage in expenses:
                d = date(year, month, 1)
                all_expenses.append((d.isoformat(), cat, fuel_type or "", amount, mileage or ""))

    all_expenses.sort(key=lambda x: x[0])
    for row in all_expenses:
        ws.append(row)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf