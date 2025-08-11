import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime
from .base import DATABASE_URL

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id BIGINT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            address TEXT,
            wallet_balance INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            photo_url TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
            items JSONB NOT NULL,
            total_amount INTEGER NOT NULL,
            cashback_amount INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            note TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS topups (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
            method TEXT NOT NULL,            -- 'card_to_card' یا 'gateway'
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', -- pending, approved, rejected
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

def upsert_user(tg_id: int, name: str | None = None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO users (telegram_id, name)
        VALUES (%s, %s)
        ON CONFLICT (telegram_id) DO UPDATE SET name = COALESCE(EXCLUDED.name, users.name);
        """, (tg_id, name))

def set_user_info(tg_id: int, name: str | None, phone: str | None, address: str | None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        UPDATE users SET
            name = COALESCE(%s, name),
            phone = COALESCE(%s, phone),
            address = COALESCE(%s, address)
        WHERE telegram_id = %s;
        """, (name, phone, address, tg_id))

def get_user(tg_id: int):
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE telegram_id=%s;", (tg_id,))
        return cur.fetchone()

def list_products():
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, name, price, photo_url FROM products ORDER BY id;")
        return cur.fetchall()

def add_product(name: str, price: int, photo_url: str | None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO products (name, price, photo_url) VALUES (%s,%s,%s);",
                    (name, price, photo_url))

def update_product(prod_id: int, name: str | None, price: int | None, photo_url: str | None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        UPDATE products
        SET name = COALESCE(%s, name),
            price = COALESCE(%s, price),
            photo_url = COALESCE(%s, photo_url)
        WHERE id=%s;
        """, (name, price, photo_url, prod_id))

def delete_product(prod_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE id=%s;", (prod_id,))

def change_wallet(tg_id: int, delta: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        UPDATE users SET wallet_balance = wallet_balance + %s WHERE telegram_id=%s
        RETURNING wallet_balance;
        """, (delta, tg_id))
        row = cur.fetchone()
        return row[0] if row else None

def create_order(tg_id: int, items: list[dict], total: int, cashback: int, note: str | None):
    import json
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO orders (user_id, items, total_amount, cashback_amount, note)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id;
        """, (tg_id, json.dumps(items), total, cashback, note))
        return cur.fetchone()[0]

def create_topup(tg_id: int, amount: int, method: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO topups (user_id, amount, method) VALUES (%s,%s,%s) RETURNING id;
        """, (tg_id, amount, method))
        return cur.fetchone()[0]
