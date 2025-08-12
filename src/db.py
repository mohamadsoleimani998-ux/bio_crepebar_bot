import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from .base import DATABASE_URL, log

@contextmanager
def _conn():
    con = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield con
        con.commit()
    finally:
        con.close()

def _exec(sql: str, params=None, fetch: str | None = None):
    with _conn() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()

# ---------- bootstrap (بدون استارتاپ DDL حجیم) ----------
def init_db():
    # users
    _exec("""
    CREATE TABLE IF NOT EXISTS users(
        user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        telegram_id BIGINT NOT NULL,
        name TEXT,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    # یکتا کردن آیدی تلگرام (مشکلات ON CONFLICT حل می‌شود)
    _exec("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_telegram_id ON users(telegram_id);")

    # products
    _exec("""
    CREATE TABLE IF NOT EXISTS products(
        product_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        photo_file_id TEXT,
        description TEXT,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

    # orders (ساده)
    _exec("""
    CREATE TABLE IF NOT EXISTS orders(
        order_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        telegram_id BIGINT NOT NULL,
        product_id BIGINT NOT NULL REFERENCES products(product_id),
        qty INTEGER NOT NULL DEFAULT 1,
        total INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)

# ---------- users ----------
def upsert_user(telegram_id: int, name: str | None):
    # اگر وجود داشت آپدیت نام، اگر نبود اینسرت
    row = _exec("""
        INSERT INTO users(telegram_id, name)
        VALUES (%s, %s)
        ON CONFLICT (telegram_id) DO UPDATE
        SET name = EXCLUDED.name
        RETURNING user_id, telegram_id, name, active;
    """, (telegram_id, name), fetch="one")
    return row

# ---------- products ----------
def add_product(name: str, price: int, photo_file_id: str | None, description: str | None):
    return _exec("""
        INSERT INTO products(name, price, photo_file_id, description)
        VALUES (%s, %s, %s, %s)
        RETURNING product_id;
    """, (name, price, photo_file_id, description), fetch="one")["product_id"]

def list_products(active_only=True):
    where = "WHERE active = TRUE" if active_only else ""
    return _exec(f"SELECT * FROM products {where} ORDER BY product_id DESC", fetch="all")

def get_product(pid: int):
    return _exec("SELECT * FROM products WHERE product_id=%s", (pid,), fetch="one")

# ---------- orders ----------
def place_order(telegram_id: int, product_id: int, qty: int):
    p = get_product(product_id)
    if not p or not p["active"]:
        return None
    total = int(p["price"]) * int(qty)
    _exec("""
        INSERT INTO orders(telegram_id, product_id, qty, total)
        VALUES (%s, %s, %s, %s)
    """, (telegram_id, product_id, qty, total))
    return total
