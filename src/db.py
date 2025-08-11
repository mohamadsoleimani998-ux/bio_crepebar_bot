# src/db.py
from __future__ import annotations

import os
import psycopg2
from psycopg2.extras import RealDictCursor

# -------------------------------
# تنظیمات
# -------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")  # مثل: postgresql://.../neondb?sslmode=require
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL محیطی تنظیم نشده است.")

def get_cashback_percent() -> int:
    """درصد کش‌بک از ENV. اگر تنظیم نبود، 0."""
    try:
        return int(os.getenv("CASHBACK_PERCENT", "0").strip())
    except Exception:
        return 0

# -------------------------------
# اتصال پایگاه‌داده (singleton)
# -------------------------------
_conn = None

def _get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        _conn.autocommit = True
    return _conn

# ابزار ساده اجرا
def _fetchall(sql: str, params: tuple = ()):
    with _get_conn().cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

def _fetchone(sql: str, params: tuple = ()):
    with _get_conn().cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

def _execute(sql: str, params: tuple = ()):
    with _get_conn().cursor() as cur:
        cur.execute(sql, params)

# -------------------------------
# ساخت اسکیمای اولیه
# -------------------------------
def ensure_schema() -> None:
    """
    جداول لازم را اگر وجود ندارند ایجاد می‌کند.
    """
    _execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price BIGINT NOT NULL,    -- تومان
            photo_url TEXT DEFAULT ''
        );
        """
    )

    _execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id SERIAL PRIMARY KEY,
            tg_user_id BIGINT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """
    )

    _execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
            qty INTEGER NOT NULL,
            total_amount BIGINT NOT NULL,   -- تومان
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """
    )

    _execute(
        """
        CREATE TABLE IF NOT EXISTS wallets (
            user_id BIGINT PRIMARY KEY,
            balance BIGINT NOT NULL DEFAULT 0
        );
        """
    )

    _execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            delta BIGINT NOT NULL,          -- + یا - به تومان
            reason TEXT DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """
    )

    _execute(
        """
        CREATE TABLE IF NOT EXISTS topups (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount BIGINT NOT NULL,
            method TEXT NOT NULL,           -- card2card / gateway / ...
            reference TEXT DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """
    )

# -------------------------------
# محصولات
# -------------------------------
def list_products():
    return _fetchall(
        "SELECT id, name, price, COALESCE(photo_url, '') AS photo_url FROM products ORDER BY id ASC;"
    )

def get_product(product_id: int):
    return _fetchone(
        "SELECT id, name, price, COALESCE(photo_url,'') AS photo_url FROM products WHERE id=%s;",
        (product_id,),
    )

def add_product(name: str, price: int, photo_url: str = "") -> int:
    row = _fetchone(
        "INSERT INTO products (name, price, photo_url) VALUES (%s, %s, %s) RETURNING id;",
        (name, int(price), photo_url or ""),
    )
    return int(row["id"])

def update_product(product_id: int, field: str, value):
    allowed = {"name", "price", "photo_url"}
    if field not in allowed:
        raise ValueError("فیلد نامعتبر برای ویرایش.")
    if field == "price":
        value = int(value)
    _execute(f"UPDATE products SET {field}=%s WHERE id=%s;", (value, product_id))

# -------------------------------
# مشتری و سفارش
# -------------------------------
def upsert_customer(user_id: int, name: str, phone: str, address: str) -> int:
    """
    اگر مشتری با tg_user_id وجود داشت آپدیت می‌شود؛ در غیر این صورت ساخته می‌شود.
    """
    existing = _fetchone("SELECT id FROM customers WHERE tg_user_id=%s;", (user_id,))
    if existing:
        _execute(
            "UPDATE customers SET name=%s, phone=%s, address=%s, updated_at=NOW() WHERE id=%s;",
            (name, phone, address, existing["id"]),
        )
        return int(existing["id"])
    row = _fetchone(
        "INSERT INTO customers (tg_user_id, name, phone, address) VALUES (%s,%s,%s,%s) RETURNING id;",
        (user_id, name, phone, address),
    )
    return int(row["id"])

def create_order(customer_id: int, product_id: int, qty: int, total_amount: int) -> int:
    row = _fetchone(
        """
        INSERT INTO orders (customer_id, product_id, qty, total_amount)
        VALUES (%s, %s, %s, %s)
        RETURNING id;
        """,
        (customer_id, product_id, int(qty), int(total_amount)),
    )
    return int(row["id"])

# -------------------------------
# کیف پول و تراکنش‌ها
# -------------------------------
def get_wallet(user_id: int):
    row = _fetchone("SELECT user_id, balance FROM wallets WHERE user_id=%s;", (user_id,))
    if not row:
        return {"user_id": user_id, "balance": 0}
    return {"user_id": int(row["user_id"]), "balance": int(row["balance"])}

def change_wallet_balance(user_id: int, delta: int, reason: str = "") -> None:
    # به‌روزرسانی یا درج اولیه
    _execute(
        """
        INSERT INTO wallets (user_id, balance)
        VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET balance = wallets.balance + EXCLUDED.balance;
        """,
        (user_id, int(delta)),
    )
    # لاگ تراکنش
    _execute(
        "INSERT INTO wallet_transactions (user_id, delta, reason) VALUES (%s, %s, %s);",
        (user_id, int(delta), reason or ""),
    )

def record_topup(user_id: int, amount: int, method: str, reference: str = "") -> int:
    row = _fetchone(
        """
        INSERT INTO topups (user_id, amount, method, reference)
        VALUES (%s, %s, %s, %s)
        RETURNING id;
        """,
        (user_id, int(amount), method, reference or ""),
    )
    return int(row["id"])
