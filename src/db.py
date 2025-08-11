# src/db.py
import os
import psycopg2
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

def ensure_schema():
    """ساخت خودکار جداول در صورت نبودنشان (Neon)."""
    with get_conn() as conn:
        cur = conn.cursor()

        # === users
        # توجه: ستون اصلی id است (همان آیدی تلگرام). قبلاً telegram_id بود که حذف شده.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            address TEXT,
            wallet INTEGER DEFAULT 0,
            cashback INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # === products
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            price INTEGER NOT NULL,
            photo_url TEXT
        );
        """)

        # === orders
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
            total_price INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # === order_items
        cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES products(id),
            qty INTEGER NOT NULL DEFAULT 1,
            price_each INTEGER NOT NULL
        );
        """)

        conn.commit()
        cur.close()

# ========== کاربران ==========
def upsert_user(user_id: int, name: str | None = None):
    """ساخت/به‌روزرسانی کاربر با کلید اصلی id (آیدی تلگرام)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (id, name)
            VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE
            SET name = COALESCE(EXCLUDED.name, users.name)
        """, (user_id, name))
        conn.commit()
        cur.close()

def get_user(user_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, phone, address, wallet, cashback FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        return {
            "id": row[0], "name": row[1], "phone": row[2], "address": row[3],
            "wallet": row[4], "cashback": row[5]
        }

def set_user_contact(user_id: int, name: str | None, phone: str | None, address: str | None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (id, name, phone, address)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET name = COALESCE(EXCLUDED.name, users.name),
                phone = COALESCE(EXCLUDED.phone, users.phone),
                address = COALESCE(EXCLUDED.address, users.address)
        """, (user_id, name, phone, address))
        conn.commit()
        cur.close()

# ========== کیف پول ==========
def change_wallet(user_id: int, delta: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users
               SET wallet = COALESCE(wallet, 0) + %s
             WHERE id = %s
        """, (delta, user_id))
        conn.commit()
        cur.close()

def add_cashback(user_id: int, amount: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE users
               SET cashback = COALESCE(cashback, 0) + %s
             WHERE id = %s
        """, (amount, user_id))
        conn.commit()
        cur.close()

# ========== محصولات ==========
def add_product(title: str, price: int, photo_url: str | None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO products (title, price, photo_url)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (title, price, photo_url))
        pid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return pid

def list_products():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, title, price, photo_url FROM products ORDER BY id DESC")
        rows = cur.fetchall()
        cur.close()
        return [{"id": r[0], "title": r[1], "price": r[2], "photo": r[3]} for r in rows]

def delete_product(pid: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE id = %s", (pid,))
        conn.commit()
        cur.close()

# ========== سفارش ==========
def create_order(user_id: int, items: list[tuple[int, int, int]]):
    """
    items: لیست تاپل‌ها به شکل (product_id, qty, price_each)
    """
    total = sum(q * p for _, q, p in items)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO orders (user_id, total_price) VALUES (%s, %s) RETURNING id", (user_id, total))
        order_id = cur.fetchone()[0]
        for product_id, qty, price_each in items:
            cur.execute("""
                INSERT INTO order_items (order_id, product_id, qty, price_each)
                VALUES (%s, %s, %s, %s)
            """, (order_id, product_id, qty, price_each))
        conn.commit()
        cur.close()
        return order_id, total
