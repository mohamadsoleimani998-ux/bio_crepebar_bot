import os
import psycopg2

DB_URL = os.getenv("DATABASE_URL")

def _get_conn():
    return psycopg2.connect(DB_URL)

def init_db():
    """ایجاد جداول در صورت نبودن (بدون دست‌زدن به داده‌های فعلی)"""
    conn = _get_conn()
    cur = conn.cursor()

    # کاربران
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_id BIGINT PRIMARY KEY,
            wallet_cents BIGINT DEFAULT 0,
            is_admin BOOLEAN DEFAULT FALSE
        )
    """)

    # محصولات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            price_cents BIGINT NOT NULL,
            photo_file_id TEXT
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

def get_or_create_user(tg_id: int):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s", (tg_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users (tg_id, wallet_cents, is_admin) VALUES (%s, %s, %s)", (tg_id, 0, False))
        conn.commit()
        row = (tg_id, 0, False)
    cur.close()
    conn.close()
    return {"tg_id": row[0], "wallet_cents": row[1], "is_admin": row[2]}

def get_wallet(tg_id: int) -> int:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s", (tg_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else 0

def update_wallet(tg_id: int, delta_cents: int):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET wallet_cents = COALESCE(wallet_cents,0) + %s WHERE tg_id=%s", (delta_cents, tg_id))
    conn.commit()
    cur.close()
    conn.close()

def list_products():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, title, price_cents, photo_file_id FROM products ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"id": r[0], "title": r[1], "price_cents": r[2], "photo_file_id": r[3]}
        for r in rows
    ]

def add_product(title: str, price_cents: int, photo_file_id: str | None):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (title, price_cents, photo_file_id) VALUES (%s, %s, %s)",
        (title, price_cents, photo_file_id),
    )
    conn.commit()
    cur.close()
    conn.close()
