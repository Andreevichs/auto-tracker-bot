import sqlite3
from datetime import datetime, date

def init_db():
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            car_model TEXT,
            car_year INTEGER,
            region TEXT,
            quick_fuel_amount REAL,
            monthly_budget REAL,
            created_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            category TEXT,
            fuel_type TEXT,
            date TEXT,
            mileage INTEGER
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT, -- 'mileage' or 'date'
            item TEXT, -- 'масло', 'техосмотр', etc.
            interval_value INTEGER, -- km or days
            last_value INTEGER, -- last mileage or timestamp
            next_alert INTEGER
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            user_id INTEGER,
            doc_type TEXT,
            date_value TEXT,
            next_alert_date TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS monthly_reports_sent (
            user_id INTEGER,
            month_year TEXT,
            PRIMARY KEY(user_id, month_year)
        )
    ''')
    
    conn.commit()
    conn.close()

def save_user(user_id):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)',
                   (user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def update_user_field(user_id, field, value):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute(f'UPDATE users SET {field} = ? WHERE user_id = ?', (value, user_id))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        'user_id': row[0],
        'car_model': row[1],
        'car_year': row[2],
        'region': row[3],
        'quick_fuel_amount': row[4],
        'monthly_budget': row[5],
        'created_at': row[6]
    }

def save_expense(user_id, amount, category, fuel_type=None, mileage=None):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO expenses (user_id, amount, category, fuel_type, date, mileage)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, amount, category, fuel_type, datetime.now().date().isoformat(), mileage))
    conn.commit()
    conn.close()

def get_expenses_by_month(user_id, year, month):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT amount, category, fuel_type, mileage FROM expenses
        WHERE user_id = ? AND strftime('%Y-%m', date) = ?
        ORDER BY date
    ''', (user_id, f"{year}-{month:02d}"))
    return cursor.fetchall()

def get_last_months(user_id, n=6):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT strftime('%Y-%m', date) as ym
        FROM expenses
        WHERE user_id = ?
        ORDER BY ym DESC
        LIMIT ?
    ''', (user_id, n))
    return [row[0] for row in cursor.fetchall()]

def save_reminder(user_id, r_type, item, interval_value, last_value, next_alert):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reminders (user_id, type, item, interval_value, last_value, next_alert)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, r_type, item, interval_value, last_value, next_alert))
    conn.commit()
    conn.close()

def get_reminders(user_id):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM reminders WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def save_document(user_id, doc_type, date_value, next_alert_date):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO documents (user_id, doc_type, date_value, next_alert_date)
        VALUES (?, ?, ?, ?)
    ''', (user_id, doc_type, date_value, next_alert_date))
    conn.commit()
    conn.close()

def get_documents(user_id):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM documents WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def mark_monthly_report_sent(user_id, month_year):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO monthly_reports_sent (user_id, month_year) VALUES (?, ?)',
                   (user_id, month_year))
    conn.commit()
    conn.close()

def was_monthly_report_sent(user_id, month_year):
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM monthly_reports_sent WHERE user_id = ? AND month_year = ?',
                   (user_id, month_year))
    return cursor.fetchone() is not None

def get_all_users():
    conn = sqlite3.connect('auto_tracker.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_total_spent_this_month(user_id):
    now = date.today()
    expenses = get_expenses_by_month(user_id, now.year, now.month)
    return sum(e[0] for e in expenses)