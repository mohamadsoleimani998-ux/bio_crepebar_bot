# src/db.py
import os
import psycopg2
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """
    این تابع هر بار موقع بالا آمدن سرویس صدا زده می‌شود
    و اگر جدول/ستون‌های لازم وجود نداشته باشند می‌سازد.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # جدول users اگر نبود ساخته می‌شود
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE,
                    name TEXT,
                    phone TEXT,
                    address TEXT,
                    wallet_balance BIGINT DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # اگر قبلاً جدول بوده ولی ستون‌ها نبودند، اضافه‌شان کن
            cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT;""")
            cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS name TEXT;""")
            cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT;""")
            cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT;""")
            cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance BIGINT DEFAULT 0;""")
            cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();""")

            # ایندکس یونیک روی telegram_id (اگر قبلاً ساخته نشده)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_telegram_id
                ON users(telegram_id);
            """)

            conn.commit()

def upsert_user(telegram_id: int, name: str | None):
    """
    ایجاد/به‌روزرسانی کاربر بر اساس telegram_id
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (telegram_id, name)
                VALUES (%s, %s)
                ON CONFLICT (telegram_id)
                DO UPDATE SET name = EXCLUDED.name;
                """,
                (telegram_id, name),
            )
            conn.commit()

def get_user(telegram_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, telegram_id, name, phone, address, wallet_balance FROM users WHERE telegram_id=%s;", (telegram_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "telegram_id": row[1],
                "name": row[2],
                "phone": row[3],
                "address": row[4],
                "wallet_balance": row[5],
            }

def update_user_contact(telegram_id: int, name: str | None, phone: str | None, address: str | None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET name = COALESCE(%s, name),
                    phone = COALESCE(%s, phone),
                    address = COALESCE(%s, address)
                WHERE telegram_id = %s;
                """,
                (name, phone, address, telegram_id),
            )
            conn.commit()

def add_wallet(telegram_id: int, amount: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET wallet_balance = COALESCE(wallet_balance, 0) + %s
                WHERE telegram_id = %s;
                """,
                (amount, telegram_id),
            )
            conn.commit()

def get_wallet(telegram_id: int) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(wallet_balance,0) FROM users WHERE telegram_id=%s;", (telegram_id,))
            row = cur.fetchone()
            return int(row[0]) if row else 0
