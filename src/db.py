import os
import psycopg2
from psycopg2.extras import Json

# از متغیر محیطی Render/Neon
DATABASE_URL = os.getenv("DATABASE_URL")

# ------------ اتصال -------------
def get_conn():
    return psycopg2.connect(DATABASE_URL)

# ------------ ساخت اسکیمـا -------------
def ensure_schema():
    ddl = """
    CREATE TABLE IF NOT EXISTS users (
        telegram_id BIGINT PRIMARY KEY,
        name        TEXT,
        phone       TEXT,
        address     TEXT,
        wallet_balance INTEGER NOT NULL DEFAULT 0,
        created_at  TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        photo_url TEXT,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
        items JSONB NOT NULL,
        total_amount INTEGER NOT NULL,
        cashback INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS wallet_tx (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
        amount INTEGER NOT NULL,         -- مثبت: شارژ / منفی: خرید
        kind TEXT NOT NULL,              -- 'topup_card','order','cashback','manual'
        meta JSONB,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(ddl)

# برای فراخوانی در استارت‌آپ
def init_db():
    """Called on startup by handlers.startup_warmup()"""
    ensure_schema()

# ------------ توابع کاربردی که handlers صدا می‌زند -------------

def upsert_user(telegram_id: int, name: str | None):
    sql = """
    INSERT INTO users (telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id)
    DO UPDATE SET name = COALESCE(EXCLUDED.name, users.name);
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (telegram_id, name))

def get_wallet(telegram_id: int) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT wallet_balance FROM users WHERE telegram_id=%s;", (telegram_id,))
        row = cur.fetchone()
        return int(row[0]) if row else 0

def change_wallet(telegram_id: int, delta: int, kind: str, meta: dict | None = None):
    with get_conn() as conn, conn.cursor() as cur:
        # مطمئن شو کاربر وجود دارد
        cur.execute("INSERT INTO users (telegram_id) VALUES (%s) ON CONFLICT DO NOTHING;", (telegram_id,))
        # لاگ تراکنش
        cur.execute(
            "INSERT INTO wallet_tx (user_id, amount, kind, meta) VALUES (%s,%s,%s,%s);",
            (telegram_id, delta, kind, Json(meta or {})),
        )
        # بروزرسانی موجودی
        cur.execute(
            "UPDATE users SET wallet_balance = wallet_balance + %s WHERE telegram_id=%s;",
            (delta, telegram_id),
        )

def list_products(active_only: bool = True):
    sql = "SELECT id, name, price, photo_url, is_active FROM products"
    if active_only:
        sql += " WHERE is_active = TRUE"
    sql += " ORDER BY id;"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()

def add_product(name: str, price: int, photo_url: str | None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO products (name, price, photo_url) VALUES (%s,%s,%s) RETURNING id;",
            (name, price, photo_url),
        )
        return cur.fetchone()[0]

def update_product(pid: int, name: str | None = None, price: int | None = None,
                   photo_url: str | None = None, is_active: bool | None = None):
    sets, vals = [], []
    if name is not None:
        sets.append("name=%s"); vals.append(name)
    if price is not None:
        sets.append("price=%s"); vals.append(price)
    if photo_url is not None:
        sets.append("photo_url=%s"); vals.append(photo_url)
    if is_active is not None:
        sets.append("is_active=%s"); vals.append(is_active)
    if not sets:
        return
    vals.append(pid)
    sql = "UPDATE products SET " + ", ".join(sets) + " WHERE id=%s;"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(vals))

def create_order(telegram_id: int, items: list[dict], total_amount: int, cashback: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO orders (user_id, items, total_amount, cashback) VALUES (%s,%s,%s,%s) RETURNING id;",
            (telegram_id, Json(items), total_amount, cashback),
        )
        return cur.fetchone()[0]
