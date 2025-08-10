# src/db.py
import os
import psycopg2
from psycopg2.extras import DictCursor

DATABASE_URL = os.getenv("DATABASE_URL")

# اتصال ساده؛ چون psycopg2 سنک است، در bot.py آن را داخل threadpool صدا می‌زنیم
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env var is missing")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
    conn.autocommit = True
    return conn

def ensure_schema():
    """جدول‌ها اگر نبودند ساخته می‌شوند؛ اجرای امن برای چند بار پشت سر هم."""
    conn = get_conn()
    cur = conn.cursor()

    # users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        tg_id BIGINT UNIQUE NOT NULL,
        username TEXT,
        first_name TEXT,
        wallet_balance INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # products
    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        image_file_id TEXT,          -- file_id تلگرام
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # orders
    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        quantity INTEGER NOT NULL DEFAULT 1,
        amount INTEGER NOT NULL,     -- مبلغ کل سفارش (قبل از کش‌بک)
        cashback_applied INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    cur.close()
    conn.close()

def ensure_user(tg_id: int, username: str | None, first_name: str | None):
    """اگر کاربر وجود نداشت بساز."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM users WHERE tg_id = %s;",
        (tg_id,)
    )
    row = cur.fetchone()
    if not row:
        cur.execute(
            "INSERT INTO users (tg_id, username, first_name) VALUES (%s, %s, %s);",
            (tg_id, username, first_name)
        )
    cur.close()
    conn.close()
