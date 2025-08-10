import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "bot.db")

# اتصال به دیتابیس
def get_conn():
    return sqlite3.connect(DB_PATH)

# ساخت جداول
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # جدول کاربران
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            wallet_cents INTEGER DEFAULT 0
        )
    """)
    # جدول محصولات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            price_cents INTEGER,
            description TEXT,
            photo_id TEXT
        )
    """)
    conn.commit()
    conn.close()

# گرفتن یا ساختن کاربر
def get_or_create_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, wallet_cents FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row
    cur.execute("INSERT INTO users (user_id, wallet_cents) VALUES (?, ?)", (user_id, 0))
    conn.commit()
    conn.close()
    return (user_id, 0)

# گرفتن موجودی کیف پول
def get_wallet(user_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT wallet_cents FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0] or 0
    return 0

# لیست محصولات
def list_products():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, title, price_cents, description, photo_id FROM products ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows

# افزودن محصول
def add_product(title: str, price_cents: int, description: str, photo_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (title, price_cents, description, photo_id) VALUES (?, ?, ?, ?)",
        (title, price_cents, description, photo_id)
    )
    conn.commit()
    conn.close()
