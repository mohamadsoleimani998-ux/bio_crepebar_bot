import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing")
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id     BIGINT PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            last_name   TEXT,
            wallet_cents INTEGER NOT NULL DEFAULT 0,
            is_admin    BOOLEAN NOT NULL DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS products(
            id SERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            photo_url   TEXT,
            active      BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS orders(
            id SERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL REFERENCES users(user_id),
            status      TEXT NOT NULL DEFAULT 'draft',
            total_cents INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS order_items(
            id SERIAL PRIMARY KEY,
            order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id  INTEGER NOT NULL REFERENCES products(id),
            qty         INTEGER NOT NULL DEFAULT 1,
            line_cents  INTEGER NOT NULL
        );
        """)
    print("DB init OK")

# ---------- users ----------
def get_or_create_user(tg_user: dict):
    uid = tg_user.get("id")
    if not uid:
        raise ValueError("Telegram user has no id")
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE user_id=%s", (uid,))
        row = cur.fetchone()
        if row:
            return row
        cur.execute("""
            INSERT INTO users(user_id, username, first_name, last_name)
            VALUES(%s,%s,%s,%s)
            RETURNING *;
        """, (uid, tg_user.get("username"), tg_user.get("first_name"), tg_user.get("last_name")))
        return cur.fetchone()

def get_wallet(user_id: int) -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT wallet_cents FROM users WHERE user_id=%s", (user_id,))
        r = cur.fetchone()
        return r[0] if r else 0

def adjust_wallet(user_id: int, delta_cents: int) -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE users SET wallet_cents = wallet_cents + %s
            WHERE user_id=%s
            RETURNING wallet_cents;
        """, (delta_cents, user_id))
        r = cur.fetchone()
        return r[0] if r else 0

def set_admins(admin_ids: list[int]):
    if not admin_ids: 
        return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET is_admin=FALSE;")
        cur.execute("UPDATE users SET is_admin=TRUE WHERE user_id = ANY(%s);", (admin_ids,))

def is_admin(user_id: int) -> bool:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT is_admin FROM users WHERE user_id=%s", (user_id,))
        r = cur.fetchone()
        return bool(r and r[0])

# ---------- products ----------
def add_product(name: str, price_cents: int, photo_url: str | None = None) -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO products(name, price_cents, photo_url)
            VALUES(%s,%s,%s) RETURNING id;
        """, (name, price_cents, photo_url))
        return cur.fetchone()[0]

def list_products() -> list[dict]:
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name, price_cents, photo_url FROM products WHERE active=TRUE ORDER BY id;")
        return cur.fetchall()

# ---------- orders (ساده) ----------
def create_order(user_id: int) -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO orders(user_id) VALUES(%s) RETURNING id;", (user_id,))
        return cur.fetchone()[0]

def add_item_to_order(order_id: int, product_id: int, qty: int = 1):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT price_cents FROM products WHERE id=%s", (product_id,))
        price = cur.fetchone()
        if not price:
            raise ValueError("product not found")
        line = price[0] * qty
        cur.execute("""
            INSERT INTO order_items(order_id, product_id, qty, line_cents)
            VALUES(%s,%s,%s,%s);
        """, (order_id, product_id, qty, line))
        cur.execute("UPDATE orders SET total_cents = total_cents + %s WHERE id=%s;", (line, order_id))

def apply_cashback(user_id: int, amount_cents: int):
    # کش‌بک ساده: 5% از مبلغ خرید
    cashback = max(0, int(round(amount_cents * 0.05)))
    if cashback:
        adjust_wallet(user_id, cashback)
    return cashback
