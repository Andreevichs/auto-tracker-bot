import os
import asyncio
from datetime import datetime, date, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
import calendar

from database import (
    init_db, save_user, update_user_field, get_user, save_expense,
    save_reminder, get_reminders, save_document, get_documents,
    was_monthly_report_sent, mark_monthly_report_sent, get_all_users,
    get_total_spent_this_month
)
from reports import generate_monthly_report, generate_chart, export_to_excel

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()

# Состояния
class AddExpense(StatesGroup):
    waiting_for_category = State()
    waiting_for_fuel_type = State()
    waiting_for_amount = State()
    waiting_for_mileage = State()

class SetCar(StatesGroup):
    waiting_for_model = State()
    waiting_for_year = State()
    waiting_for_region = State()

class SetQuickFuel(StatesGroup):
    waiting_for_amount = State()

class SetBudget(StatesGroup):
    waiting_for_amount = State()

class AddMileageReminder(StatesGroup):
    waiting_for_item = State()
    waiting_for_interval = State()
    waiting_for_last_value = State()

class AddDateReminder(StatesGroup):
    waiting_for_doc_type = State()
    waiting_for_date = State()

# Категории
CATEGORIES = ["бензин", "дизель", "масло", "техосмотр", "налог", "ремонт", "страховка", "шиномонтаж", "моика", "прочее"]
FUEL_TYPES = ["АИ-92", "АИ-95", "ДТ"]

def main_menu(user_id=None):
    quick_btn = []
    change_btn = [InlineKeyboardButton(text="✏️ Изменить сумму заправки", callback_data="change_quick_fuel")]
    
    if user_id:
        user = get_user(user_id)
        if user and user.get('quick_fuel_amount'):
            quick_btn = [InlineKeyboardButton(
                text=f"⛽ Быстро: {user['quick_fuel_amount']:.0f} Br",
                callback_data="quick_fuel"
            )]
    
    return InlineKeyboardMarkup(inline_keyboard=[
        quick_btn,
        [InlineKeyboardButton(text="➕ Добавить расход", callback_data="add_expense")],
        [InlineKeyboardButton(text="📊 Отчёт за месяц", callback_data="monthly_report")],
        [InlineKeyboardButton(text="📈 График по месяцам", callback_data="chart")],
        [InlineKeyboardButton(text="📤 Экспорт данных", callback_data="export_data")],
        [InlineKeyboardButton(text="🔔 Напоминания", callback_data="reminders")],
        [InlineKeyboardButton(text="⚙️ Настроить авто", callback_data="set_car")],
        change_btn,
        [InlineKeyboardButton(text="💰 Установить бюджет", callback_data="set_budget")]
    ])

def back_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
    ])

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    save_user(user_id)
    user = get_user(user_id)
    
    # Если ещё не задана сумма заправки — спросим
    if not user or user.get('quick_fuel_amount') is None:
        await message.answer(
            "Привет! 👋 Я — ваш помощник по учёту расходов на автомобиль в Беларуси.\n\n"
            "Для удобства укажите, на какую сумму вы обычно заправляетесь (в Br):"
        )
        await state.set_state(SetQuickFuel.waiting_for_amount)
    else:
        await message.answer(
            "Выберите действие:",
            reply_markup=main_menu(user_id)
        )

# === БЫСТРАЯ ЗАПРАВКА ===
@dp.callback_query(F.data == "quick_fuel")
async def quick_fuel(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or not user.get('quick_fuel_amount'):
        await callback.answer("Сначала настройте сумму заправки в меню.", show_alert=True)
        return
    save_expense(callback.from_user.id, user['quick_fuel_amount'], "бензин", "АИ-95")
    await callback.message.edit_text(
        f"✅ Быстрая заправка добавлена: {user['quick_fuel_amount']:.0f} Br",
        reply_markup=main_menu(callback.from_user.id)
    )

@dp.callback_query(F.data == "change_quick_fuel")
async def change_quick_fuel_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите новую сумму заправки в Br:")
    await state.set_state(SetQuickFuel.waiting_for_amount)

@dp.message(StateFilter(SetQuickFuel.waiting_for_amount))
async def save_quick_fuel(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError
        update_user_field(message.from_user.id, 'quick_fuel_amount', amount)
        await message.answer(f"✅ Сумма заправки обновлена: {amount:.0f} Br", reply_markup=main_menu(message.from_user.id))
        await state.clear()
    except (ValueError, TypeError):
        await message.answer("❌ Введите корректное число:")

# === ДОБАВЛЕНИЕ РАСХОДА ===
@dp.callback_query(F.data == "add_expense")
async def add_expense_start(callback: CallbackQuery, state: FSMContext):
    buttons = [[InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}") for cat in CATEGORIES[i:i+2]] 
               for i in range(0, len(CATEGORIES), 2)]
    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")])
    await callback.message.edit_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AddExpense.waiting_for_category)

@dp.callback_query(F.data.startswith("cat_"), StateFilter(AddExpense.waiting_for_category))
async def select_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data[4:]
    await state.update_data(category=category)
    if category in ["бензин", "дизель"]:
        buttons = [[InlineKeyboardButton(text=ft, callback_data=f"fuel_{ft}") for ft in FUEL_TYPES[i:i+2]] 
                   for i in range(0, len(FUEL_TYPES), 2)]
        buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")])
        await callback.message.edit_text("Выберите тип топлива:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await state.set_state(AddExpense.waiting_for_fuel_type)
    else:
        await callback.message.edit_text(f"Категория: *{category}*\nВведите сумму в Br:", parse_mode="Markdown", reply_markup=back_button())
        await state.set_state(AddExpense.waiting_for_amount)

@dp.callback_query(F.data.startswith("fuel_"), StateFilter(AddExpense.waiting_for_fuel_type))
async def select_fuel_type(callback: CallbackQuery, state: FSMContext):
    fuel_type = callback.data[5:]
    await state.update_data(fuel_type=fuel_type)
    await callback.message.edit_text(f"Тип топлива: *{fuel_type}*\nВведите сумму в Br:", parse_mode="Markdown", reply_markup=back_button())
    await state.set_state(AddExpense.waiting_for_amount)

@dp.message(StateFilter(AddExpense.waiting_for_amount))
async def enter_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError
        await state.update_data(amount=amount)
        await message.answer(
            "Введите текущий пробег (в км) или нажмите «Пропустить»:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Пропустить", callback_data="skip_mileage")],
                [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
            ])
        )
        await state.set_state(AddExpense.waiting_for_mileage)
    except (ValueError, TypeError):
        await message.answer("❌ Введите корректное число:", reply_markup=back_button())

@dp.message(StateFilter(AddExpense.waiting_for_mileage))
async def enter_mileage(message: Message, state: FSMContext):
    try:
        mileage = int(message.text)
        data = await state.get_data()
        save_expense(message.from_user.id, data['amount'], data['category'], data.get('fuel_type'), mileage)
        await message.answer(
            f"✅ Расход добавлен: {data['amount']:.0f} Br на {data['category']}",
            reply_markup=main_menu(message.from_user.id)
        )
        await state.clear()
    except (ValueError, TypeError):
        await message.answer(
            "❌ Введите целое число или нажмите «Пропустить»:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Пропустить", callback_data="skip_mileage")],
                [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
            ])
        )

@dp.callback_query(F.data == "skip_mileage", StateFilter(AddExpense.waiting_for_mileage))
async def skip_mileage(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    save_expense(callback.from_user.id, data['amount'], data['category'], data.get('fuel_type'))
    await callback.message.edit_text(
        f"✅ Расход добавлен: {data['amount']:.0f} Br на {data['category']}",
        reply_markup=main_menu(callback.from_user.id)
    )
    await state.clear()

# === НАСТРОЙКА АВТО ===
@dp.callback_query(F.data == "set_car")
async def set_car_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите модель авто (например: Lada Granta):", reply_markup=back_button())
    await state.set_state(SetCar.waiting_for_model)

@dp.message(StateFilter(SetCar.waiting_for_model))
async def set_car_model(message: Message, state: FSMContext):
    if len(message.text.strip()) < 2:
        await message.answer("❌ Слишком короткое название. Попробуйте снова:", reply_markup=back_button())
        return
    await state.update_data(model=message.text.strip())
    await message.answer("Введите год выпуска (например: 2019):", reply_markup=back_button())
    await state.set_state(SetCar.waiting_for_year)

@dp.message(StateFilter(SetCar.waiting_for_year))
async def set_car_year(message: Message, state: FSMContext):
    try:
        year = int(message.text)
        if year < 1990 or year > datetime.now().year + 1:
            raise ValueError
        await state.update_data(year=year)
        await message.answer("Введите регион регистрации (например: Минск):", reply_markup=back_button())
        await state.set_state(SetCar.waiting_for_region)
    except (ValueError, TypeError):
        await message.answer("❌ Введите корректный год (например: 2019):", reply_markup=back_button())

@dp.message(StateFilter(SetCar.waiting_for_region))
async def set_car_region(message: Message, state: FSMContext):
    data = await state.get_data()
    update_user_field(message.from_user.id, 'car_model', data['model'])
    update_user_field(message.from_user.id, 'car_year', data['year'])
    update_user_field(message.from_user.id, 'region', message.text.strip())
    await message.answer(f"✅ Авто сохранено:\nМодель: {data['model']}\nГод: {data['year']}\nРегион: {message.text}", reply_markup=main_menu(message.from_user.id))
    await state.clear()

# === НАПОМИНАНИЯ ===
@dp.callback_query(F.data == "reminders")
async def reminders_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Выберите тип напоминания:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="По пробегу (масло, фильтр и т.д.)", callback_data="rem_mileage")],
            [InlineKeyboardButton(text="По дате (техосмотр, налог, страховка)", callback_data="rem_date")],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
        ])
    )

@dp.callback_query(F.data == "rem_mileage")
async def rem_mileage_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Что напоминать? (например: замена масла):", reply_markup=back_button())
    await state.set_state(AddMileageReminder.waiting_for_item)

@dp.message(StateFilter(AddMileageReminder.waiting_for_item))
async def rem_mileage_item(message: Message, state: FSMContext):
    await state.update_data(item=message.text.strip())
    await message.answer("Через сколько км напоминать? (например: 10000):", reply_markup=back_button())
    await state.set_state(AddMileageReminder.waiting_for_interval)

@dp.message(StateFilter(AddMileageReminder.waiting_for_interval))
async def rem_mileage_interval(message: Message, state: FSMContext):
    try:
        interval = int(message.text)
        if interval <= 0:
            raise ValueError
        await state.update_data(interval=interval)
        await message.answer("Введите текущий пробег (после последнего ТО):", reply_markup=back_button())
        await state.set_state(AddMileageReminder.waiting_for_last_value)
    except (ValueError, TypeError):
        await message.answer("❌ Введите число км:", reply_markup=back_button())

@dp.message(StateFilter(AddMileageReminder.waiting_for_last_value))
async def rem_mileage_save(message: Message, state: FSMContext):
    try:
        last_mileage = int(message.text)
        data = await state.get_data()
        next_alert = last_mileage + data['interval']
        save_reminder(message.from_user.id, 'mileage', data['item'], data['interval'], last_mileage, next_alert)
        await message.answer(f"✅ Напоминание добавлено!\n'{data['item']}' каждые {data['interval']} км\nСледующее: на {next_alert} км", reply_markup=main_menu(message.from_user.id))
        await state.clear()
    except (ValueError, TypeError):
        await message.answer("❌ Введите пробег:", reply_markup=back_button())

@dp.callback_query(F.data == "rem_date")
async def rem_date_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Выберите документ:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Техосмотр", callback_data="doc_техосмотр")],
            [InlineKeyboardButton(text="Налог", callback_data="doc_налог")],
            [InlineKeyboardButton(text="Страховка", callback_data="doc_страховка")],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
        ])
    )
    await state.set_state(AddDateReminder.waiting_for_doc_type)

@dp.callback_query(F.data.startswith("doc_"), StateFilter(AddDateReminder.waiting_for_doc_type))
async def rem_date_type(callback: CallbackQuery, state: FSMContext):
    doc_type = callback.data[4:]
    await state.update_data(doc_type=doc_type)
    await callback.message.edit_text(f"Введите дату окончания '{doc_type}' (ДД.ММ.ГГГГ):", reply_markup=back_button())
    await state.set_state(AddDateReminder.waiting_for_date)

@dp.message(StateFilter(AddDateReminder.waiting_for_date))
async def rem_date_save(message: Message, state: FSMContext):
    try:
        d = datetime.strptime(message.text, "%d.%m.%Y").date()
        data = await state.get_data()
        # Напоминание за 14 дней
        alert_date = d - timedelta(days=14)
        save_document(message.from_user.id, data['doc_type'], d.isoformat(), alert_date.isoformat())
        await message.answer(f"✅ Напоминание добавлено!\n'{data['doc_type']}' до {d.strftime('%d.%m.%Y')}\nНапомним: {alert_date.strftime('%d.%m.%Y')}", reply_markup=main_menu(message.from_user.id))
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте ДД.ММ.ГГГГ:", reply_markup=back_button())

# === ОСТАЛЬНЫЕ ФУНКЦИИ ===
@dp.callback_query(F.data == "monthly_report")
async def send_monthly_report(callback: CallbackQuery):
    now = datetime.now()
    report = generate_monthly_report(callback.from_user.id, now.year, now.month)
    await callback.message.edit_text(report, parse_mode="Markdown", reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "chart")
async def send_chart(callback: CallbackQuery):
    chart = generate_chart(callback.from_user.id)
    if chart:
        await callback.message.answer_photo(chart, caption="Ваши расходы за последние 6 месяцев (Br)")
    else:
        await callback.message.answer("Нужны данные хотя бы за 2 месяца.")
    await callback.message.answer("Выберите действие:", reply_markup=main_menu(callback.from_user.id))

@dp.callback_query(F.data == "export_data")
async def export_data(callback: CallbackQuery):
    try:
        excel_file = export_to_excel(callback.from_user.id)
        await callback.message.answer_document(
            FSInputFile(excel_file, filename="auto_expenses.xlsx"),
            caption="Ваши данные в Excel!"
        )
    except Exception as e:
        await callback.message.answer("Ошибка при создании файла.")

@dp.callback_query(F.data == "set_budget")
async def set_budget_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите месячный бюджет на авто (в Br):", reply_markup=back_button())
    await state.set_state(SetBudget.waiting_for_amount)

@dp.message(StateFilter(SetBudget.waiting_for_amount))
async def save_budget(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError
        update_user_field(message.from_user.id, 'monthly_budget', amount)
        await message.answer(f"✅ Бюджет установлен: {amount:.0f} Br/мес", reply_markup=main_menu(message.from_user.id))
        await state.clear()
    except (ValueError, TypeError):
        await message.answer("❌ Введите число:")

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Выберите действие:", reply_markup=main_menu(callback.from_user.id))

# === ЕЖЕМЕСЯЧНАЯ РАССЫЛКА + ПРОВЕРКА НАПОМИНАНИЙ ===
async def check_reminders():
    from database import get_all_users, get_reminders, get_documents, get_user
    today = date.today()
    today_str = today.isoformat()
    
    for user_id in get_all_users():
        # Проверка по дате
        docs = get_documents(user_id)
        for _, doc_type, _, alert_date in docs:
            if alert_date == today_str:
                await bot.send_message(user_id, f"🔔 Напоминание!\nСрок действия '{doc_type}' истекает скоро. Не забудьте обновить!")
        
        # Проверка по пробегу — требует ввода пробега пользователем, поэтому пока пропустим
        # (можно реализовать при добавлении расхода с пробегом)

async def send_monthly_reports_to_all():
    today = date.today()
    if today.day != 1:
        return

    if today.month == 1:
        prev_month, prev_year = 12, today.year - 1
    else:
        prev_month, prev_year = today.month - 1, today.year

    month_year_str = f"{prev_year}-{prev_month:02d}"
    users = get_all_users()

    for user_id in users:
        if was_monthly_report_sent(user_id, month_year_str):
            continue
        try:
            report = generate_monthly_report(user_id, prev_year, prev_month)
            await bot.send_message(user_id, f"📬 Автоматический отчёт:\n\n{report}", parse_mode="Markdown")
            mark_monthly_report_sent(user_id, month_year_str)
            
            # Проверка бюджета
            user = get_user(user_id)
            if user and user.get('monthly_budget'):
                spent = get_total_spent_this_month(user_id)
                budget = user['monthly_budget']
                if spent > budget:
                    await bot.send_message(user_id, f"⚠️ Вы превысили бюджет на {spent - budget:.0f} Br!")
                elif spent > budget * 0.9:
                    await bot.send_message(user_id, f"ℹ️ Вы уже потратили {spent:.0f} Br из {budget:.0f} Br бюджета.")
        except Exception as e:
            print(f"Ошибка отправки {user_id}: {e}")

async def start_scheduler():
    scheduler.add_job(check_reminders, 'cron', hour=9, minute=0)
    scheduler.add_job(send_monthly_reports_to_all, 'cron', hour=9, minute=0)
    scheduler.start()

async def main():
    init_db()
    await start_scheduler()
    print("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())