import os
import psycopg2
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """ایجاد جداول در صورت نبودن‌شان. اجرای سریع و یک‌باره در استارت‌آپ."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            tg_id BIGINT UNIQUE NOT NULL,
            wallet_cents INTEGER NOT NULL DEFAULT 0,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            photo_file_id TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            product_id INTEGER NOT NULL REFERENCES products(id),
            qty INTEGER NOT NULL DEFAULT 1,
            total_cents INTEGER NOT NULL,
            cashback_cents INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)
        conn.commit()

def get_or_create_user(tg_id: int, admin_ids: set[int]):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, wallet_cents, is_admin FROM users WHERE tg_id=%s", (tg_id,))
        row = cur.fetchone()
        if row:
            return {"id": row[0], "wallet_cents": row[1], "is_admin": row[2]}
        is_admin = tg_id in admin_ids
        cur.execute("INSERT INTO users (tg_id, is_admin) VALUES (%s, %s) RETURNING id, wallet_cents, is_admin",
                    (tg_id, is_admin))
        row = cur.fetchone()
        conn.commit()
        return {"id": row[0], "wallet_cents": row[1], "is_admin": row[2]}

def add_product(title: str, price_cents: int, photo_file_id: str | None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO products (title, price_cents, photo_file_id) VALUES (%s,%s,%s) RETURNING id",
            (title, price_cents, photo_file_id)
        )
        pid = cur.fetchone()[0]
        conn.commit()
        return pid

def list_products():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, title, price_cents FROM products ORDER BY id DESC LIMIT 20")
        return [{"id": r[0], "title": r[1], "price_cents": r[2]} for r in cur.fetchall()]

def get_product(pid: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, title, price_cents, photo_file_id FROM products WHERE id=%s", (pid,))
        r = cur.fetchone()
        if not r: return None
        return {"id": r[0], "title": r[1], "price_cents": r[2], "photo_file_id": r[3]}

def add_order(user_id: int, product_id: int, qty: int, cashback_percent: int):
    pr = get_product(product_id)
    if not pr: return None
    total = pr["price_cents"] * qty
    cashback = total * max(cashback_percent, 0) // 100
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO orders (user_id, product_id, qty, total_cents, cashback_cents) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (user_id, product_id, qty, total, cashback)
        )
        oid = cur.fetchone()[0]
        # کیف پول را شارژ می‌کنیم
        cur.execute("UPDATE users SET wallet_cents = wallet_cents + %s WHERE id=%s", (cashback, user_id))
        conn.commit()
    return {"order_id": oid, "total_cents": total, "cashback_cents": cashback}

def get_wallet(user_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT wallet_cents FROM users WHERE id=%s", (user_id,))
        w = cur.fetchone()
        return 0 if not w else w[0]
