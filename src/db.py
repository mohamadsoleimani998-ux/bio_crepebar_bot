import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL")

def _conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """ایجاد جداول پایه (idempotent)"""
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price_cents INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            qty INTEGER NOT NULL DEFAULT 1,
            total_cents INTEGER NOT NULL,
            cashback_cents INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_txns (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount_cents INTEGER NOT NULL,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        cn.commit()

def get_or_create_user(tg_id, first_name=None, last_name=None, username=None):
    with _conn() as cn, cn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT id, tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s", (tg_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        cur.execute("""
            INSERT INTO users (tg_id, first_name, last_name, username, wallet_cents, is_admin)
            VALUES (%s, %s, %s, %s, 0, FALSE)
            RETURNING id, tg_id, wallet_cents, is_admin
        """, (tg_id, first_name, last_name, username))
        return dict(cur.fetchone())

def get_wallet(user_id):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT wallet_cents FROM users WHERE id=%s", (user_id,))
        (cents,) = cur.fetchone()
        return cents

def list_products():
    with _conn() as cn, cn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT id, name, price_cents FROM products WHERE is_active=TRUE ORDER BY id")
        return [dict(r) for r in cur.fetchall()]

def add_product(name, price_cents):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("INSERT INTO products (name, price_cents) VALUES (%s, %s) RETURNING id", (name, price_cents))
        (pid,) = cur.fetchone()
        return pid

def get_product(product_id):
    with _conn() as cn, cn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT id, name, price_cents FROM products WHERE id=%s AND is_active=TRUE", (product_id,))
        row = cur.fetchone()
        return dict(row) if row else None

def record_txn(user_id, amount_cents, reason):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE users SET wallet_cents = wallet_cents + %s WHERE id=%s", (amount_cents, user_id))
        cur.execute("INSERT INTO wallet_txns (user_id, amount_cents, reason) VALUES (%s, %s, %s)",
                    (user_id, amount_cents, reason))
        cn.commit()

def get_cashback_percent():
    v = os.getenv("CASHBACK_PERCENT")
    if v and v.strip().isdigit():
        return int(v.strip())
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key='cashback_percent'")
        row = cur.fetchone()
        if row and row[0].isdigit():
            return int(row[0])
    return 0

def set_cashback_percent(p):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO settings(key,value) VALUES ('cashback_percent', %s)
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
        """, (str(int(p)),))
        cn.commit()

def create_order_with_cashback(user_id, product_id, qty):
    qty = max(1, int(qty))
    prod = get_product(product_id)
    if not prod:
        raise ValueError("محصول یافت نشد")

    total = prod["price_cents"] * qty
    cb_percent = get_cashback_percent()
    cashback = (total * cb_percent) // 100 if cb_percent > 0 else 0

    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO orders (user_id, product_id, qty, total_cents, cashback_cents)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, product_id, qty, total, cashback))
        (order_id,) = cur.fetchone()

        if cashback > 0:
            cur.execute("UPDATE users SET wallet_cents = wallet_cents + %s WHERE id=%s", (cashback, user_id))
            cur.execute("INSERT INTO wallet_txns (user_id, amount_cents, reason) VALUES (%s, %s, %s)",
                        (user_id, cashback, f"cashback order #{order_id}"))
        cn.commit()

    return {"order_id": order_id, "total_cents": total, "cashback_cents": cashback, "product": prod, "qty": qty}
