from __future__ import annotations
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from typing import Any, Iterable
from .base import SETTINGS

# اتصال ساده؛ هر کوئری یک کانکشن کوتاه‌مدت می‌گیرد (برای Render/Neon امن‌تر است)
@contextmanager
def _conn():
    conn = psycopg2.connect(SETTINGS.DATABASE_URL, sslmode="require")
    try:
        yield conn
    finally:
        conn.close()

def init_db() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS users(
        id BIGINT PRIMARY KEY,
        tg_username TEXT,
        full_name TEXT,
        phone TEXT,
        address TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS wallets(
        user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        balance BIGINT NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS wallet_tx(
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
        amount BIGINT NOT NULL,          -- + شارژ / - برداشت
        kind TEXT NOT NULL,              -- deposit|order|refund|manual
        meta JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS products(
        id BIGSERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        price BIGINT NOT NULL,           -- تومان
        photo_id TEXT,                   -- file_id تلگرام یا URL
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS orders(
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
        customer_name TEXT,
        customer_phone TEXT,
        customer_address TEXT,
        subtotal BIGINT NOT NULL DEFAULT 0,
        cashback BIGINT NOT NULL DEFAULT 0,
        paid_from_wallet BIGINT NOT NULL DEFAULT 0,
        total BIGINT NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'new', -- new|paid|canceled|delivered
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS order_items(
        id BIGSERIAL PRIMARY KEY,
        order_id BIGINT REFERENCES orders(id) ON DELETE CASCADE,
        product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
        title TEXT NOT NULL,
        qty INT NOT NULL DEFAULT 1,
        unit_price BIGINT NOT NULL
    );
    """
    exec_sql(sql)

def exec_sql(sql: str, params: Iterable[Any] | None = None):
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params or ())
            c.commit()

def fetchall(sql: str, params: Iterable[Any] | None = None) -> list[dict]:
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return [dict(r) for r in cur.fetchall()]

def fetchone(sql: str, params: Iterable[Any] | None = None) -> dict | None:
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
            return dict(row) if row else None

# --- Users & Wallets ---------------------------------------------------------
def upsert_user(user_id: int, username: str | None, full_name: str | None) -> None:
    sql = """
    INSERT INTO users(id, tg_username, full_name)
    VALUES(%s, %s, %s)
    ON CONFLICT (id) DO UPDATE SET tg_username=EXCLUDED.tg_username,
                                  full_name=EXCLUDED.full_name;
    INSERT INTO wallets(user_id, balance) VALUES(%s, 0)
    ON CONFLICT DO NOTHING;
    """
    exec_sql(sql, (user_id, username, full_name, user_id))

def update_profile(user_id: int, phone: str, address: str, name: str) -> None:
    exec_sql("UPDATE users SET phone=%s, address=%s, full_name=%s WHERE id=%s",
             (phone, address, name, user_id))

def get_wallet(user_id: int) -> int:
    row = fetchone("SELECT balance FROM wallets WHERE user_id=%s", (user_id,))
    return int(row["balance"]) if row else 0

def add_wallet_tx(user_id: int, amount: int, kind: str, meta: dict | None = None) -> None:
    exec_sql("INSERT INTO wallet_tx(user_id, amount, kind, meta) VALUES(%s,%s,%s,%s)",
             (user_id, amount, kind, psycopg2.extras.Json(meta or {})))
    exec_sql("UPDATE wallets SET balance = balance + %s WHERE user_id=%s", (amount, user_id))

# --- Products ----------------------------------------------------------------
def add_product(title: str, price: int, photo_id: str | None) -> int:
    row = fetchone(
        "INSERT INTO products(title, price, photo_id) VALUES(%s,%s,%s) RETURNING id",
        (title, price, photo_id),
    )
    return int(row["id"])

def list_products(active_only: bool = True) -> list[dict]:
    if active_only:
        return fetchall("SELECT * FROM products WHERE is_active=TRUE ORDER BY id DESC")
    return fetchall("SELECT * FROM products ORDER BY id DESC")

def set_product_active(pid: int, active: bool) -> None:
    exec_sql("UPDATE products SET is_active=%s WHERE id=%s", (active, pid))

# --- Orders ------------------------------------------------------------------
def create_order(user_id: int, name: str, phone: str, address: str,
                 items: list[dict], cashback_percent: int) -> int:
    # subtotal
    subtotal = sum(int(i["qty"]) * int(i["unit_price"]) for i in items)
    cashback = subtotal * cashback_percent // 100
    paid_from_wallet = 0
    total = max(subtotal - paid_from_wallet - cashback, 0)

    row = fetchone("""
        INSERT INTO orders(user_id, customer_name, customer_phone, customer_address,
                           subtotal, cashback, paid_from_wallet, total)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (user_id, name, phone, address, subtotal, cashback, paid_from_wallet, total))
    order_id = int(row["id"])

    for it in items:
        exec_sql("""
            INSERT INTO order_items(order_id, product_id, title, qty, unit_price)
            VALUES(%s,%s,%s,%s,%s)
        """, (order_id, it.get("product_id"), it["title"], it["qty"], it["unit_price"]))

    # ثبت کش‌بک به کیف پول
    if cashback > 0:
        add_wallet_tx(user_id, cashback, "cashback", {"order_id": order_id})

    return order_id

def get_order(order_id: int) -> dict | None:
    o = fetchone("SELECT * FROM orders WHERE id=%s", (order_id,))
    if not o:
        return None
    items = fetchall("SELECT * FROM order_items WHERE order_id=%s", (order_id,))
    o["items"] = items
    return o
