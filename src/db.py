import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            tg_id BIGINT PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            wallet_cents INTEGER NOT NULL DEFAULT 0,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products(
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders(
            id SERIAL PRIMARY KEY,
            user_tg_id BIGINT NOT NULL REFERENCES users(tg_id),
            product_id INTEGER NOT NULL REFERENCES products(id),
            qty INTEGER NOT NULL DEFAULT 1,
            total_cents INTEGER NOT NULL,
            cashback_cents INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'placed',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)

def set_admins(admin_ids: list[int]):
    if not admin_ids:
        return
    with get_conn() as conn, conn.cursor() as cur:
        for aid in admin_ids:
            cur.execute("UPDATE users SET is_admin=TRUE WHERE tg_id=%s;", (aid,))

def get_or_create_user(user):
    tg_id = user.get("id")
    first_name = user.get("first_name")
    last_name = user.get("last_name")
    username = user.get("username")
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE tg_id=%s;", (tg_id,))
        row = cur.fetchone()
        if row:
            return row
        cur.execute("""
            INSERT INTO users(tg_id, first_name, last_name, username)
            VALUES (%s,%s,%s,%s)
            RETURNING tg_id, first_name, last_name, username, wallet_cents, is_admin;
        """, (tg_id, first_name, last_name, username))
        return cur.fetchone()

def get_wallet(tg_id: int) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s;", (tg_id,))
        val = cur.fetchone()
        return int(val[0]) if val else 0

def add_credit(tg_id: int, amount_cents: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET wallet_cents = wallet_cents + %s WHERE tg_id=%s;", (amount_cents, tg_id))

def list_products():
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, title, price_cents FROM products WHERE is_active=TRUE ORDER BY id;")
        rows = cur.fetchall()
        # همراه قیمت به تومان برای نمایش در کیبورد
        for r in rows:
            r["price_t"] = r["price_cents"] // 100
        return rows

def add_product(title: str, price_toman: int):
    price_cents = int(price_toman) * 100
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO products(title, price_cents) VALUES (%s,%s);", (title, price_cents))

def is_admin(tg_id: int) -> bool:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT is_admin FROM users WHERE tg_id=%s;", (tg_id,))
        row = cur.fetchone()
        return bool(row and row[0])

def place_order(tg_id: int, product_id: int, qty: int = 1, cashback_percent: int = 5) -> tuple[bool, str]:
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT price_cents FROM products WHERE id=%s AND is_active=TRUE;", (product_id,))
        p = cur.fetchone()
        if not p:
            return False, "محصول پیدا نشد."
        total = int(p["price_cents"]) * int(qty)
        # بررسی موجودی
        cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s FOR UPDATE;", (tg_id,))
        w = cur.fetchone()
        wallet = int(w["wallet_cents"]) if w else 0
        if wallet < total:
            need = (total - wallet) // 100
            return False, f"موجودی کافی نیست. {need} تومان کم دارید."

        cashback = (total * int(cashback_percent)) // 100
        # کسر مبلغ و ثبت کش‌بک
        cur.execute("UPDATE users SET wallet_cents = wallet_cents - %s + %s WHERE tg_id=%s;", (total, cashback, tg_id))
        cur.execute("""
            INSERT INTO orders(user_tg_id, product_id, qty, total_cents, cashback_cents)
            VALUES (%s,%s,%s,%s,%s);
        """, (tg_id, product_id, qty, total, cashback))
        return True, f"سفارش شما ثبت شد. مبلغ: {total//100} تومان | کش‌بک: {cashback//100} تومان"
