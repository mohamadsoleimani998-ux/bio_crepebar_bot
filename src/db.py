# src/db.py
import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

def _get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# ----- ایجاد جداول در استارتاپ
def init_db():
    with _get_conn() as conn, conn.cursor() as cur:
        # کاربران
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            tg_id BIGINT UNIQUE NOT NULL,
            name TEXT,
            phone TEXT,
            address TEXT,
            wallet BIGINT DEFAULT 0
        );
        """)
        # محصولات
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id BIGSERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            price BIGINT NOT NULL,
            image_file_id TEXT
        );
        """)
        # سفارش‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id BIGSERIAL PRIMARY KEY,
            tg_id BIGINT NOT NULL,
            product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            qty INT NOT NULL DEFAULT 1,
            total BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
    return True

# ----- کاربران
def upsert_user(tg_id: int, name: str | None):
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO users (tg_id, name)
        VALUES (%s, %s)
        ON CONFLICT (tg_id) DO UPDATE SET name = EXCLUDED.name
        """, (tg_id, name))

def get_user(tg_id: int):
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE tg_id=%s", (tg_id,))
        return cur.fetchone()

def set_user_contact(tg_id: int, phone: str | None, address: str | None, name: str | None = None):
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        UPDATE users SET phone=COALESCE(%s, phone),
                         address=COALESCE(%s, address),
                         name=COALESCE(%s, name)
        WHERE tg_id=%s
        """, (phone, address, name, tg_id))

def change_wallet(tg_id: int, delta: int):
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET wallet=wallet + %s WHERE tg_id=%s RETURNING wallet", (delta, tg_id))
        row = cur.fetchone()
        return row["wallet"] if row else None

# ----- محصولات
def add_product(name: str, price: int, image_file_id: str | None):
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO products (name, price, image_file_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (name) DO UPDATE SET price=EXCLUDED.price, image_file_id=EXCLUDED.image_file_id
        RETURNING id
        """, (name.strip(), int(price), image_file_id))
        return cur.fetchone()["id"]

def list_products():
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM products ORDER BY id DESC")
        return cur.fetchall()

def delete_product_by_name(name: str):
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE name=%s", (name.strip(),))
        return cur.rowcount

# ----- سفارش
def create_order(tg_id: int, product_id: int, qty: int, total: int):
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO orders (tg_id, product_id, qty, total)
        VALUES (%s, %s, %s, %s) RETURNING id
        """, (tg_id, product_id, qty, total))
        return cur.fetchone()["id"]
