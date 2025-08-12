# src/db.py
import os
import psycopg2
import psycopg2.extras
from typing import List, Tuple, Optional, Dict, Any

DATABASE_URL = os.environ.get("DATABASE_URL")
CASHBACK_PERCENT = int(os.environ.get("CASHBACK_PERCENT", "3"))

_conn: Optional[psycopg2.extensions.connection] = None


# ---------- low level ----------
def _get_conn():
    global _conn
    if _conn is None or _conn.closed != 0:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL env var is not set")
        _conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        _conn.autocommit = True
    return _conn


def _exec(sql: str, params: Tuple = ()) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(sql, params)


def _fetchone(sql: str, params: Tuple = ()) -> Optional[tuple]:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _fetchall(sql: str, params: Tuple = ()) -> List[tuple]:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# ---------- schema & migrations ----------
def init_db() -> None:
    """
    ایجاد جداول در صورت نبودن و افزودن ستون‌های جدید (بدون حذف دیتا).
    این تابع را در استارتاپ اپلیکیشن صدا بزن.
    """
    ddl = """
    CREATE TABLE IF NOT EXISTS users (
        id                   SERIAL PRIMARY KEY,
        telegram_id          BIGINT NOT NULL,
        name                 TEXT,
        phone                TEXT,
        address              TEXT,
        wallet_balance_cents INTEGER NOT NULL DEFAULT 0,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- تضمین یکتا بودن آیدی تلگرام برای upsert
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = 'users_telegram_id_key'
        ) THEN
            BEGIN
                CREATE UNIQUE INDEX users_telegram_id_key ON users(telegram_id);
            EXCEPTION WHEN OTHERS THEN
                -- اگر از قبل ایندکس مشابه با اسم دیگر بود، نادیده بگیر
                NULL;
            END;
        END IF;
    END$$;

    CREATE TABLE IF NOT EXISTS products (
        id           SERIAL PRIMARY KEY,
        name         TEXT NOT NULL,
        price_cents  INTEGER NOT NULL CHECK (price_cents >= 0),
        photo_url    TEXT,
        active       BOOLEAN NOT NULL DEFAULT TRUE,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- ستون‌ها را اگر نبودند اضافه کن (برای سازگاری با نسخه‌های قبلی)
    ALTER TABLE users
        ADD COLUMN IF NOT EXISTS phone TEXT,
        ADD COLUMN IF NOT EXISTS address TEXT,
        ADD COLUMN IF NOT EXISTS wallet_balance_cents INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        ADD COLUMN IF NOT EXISTS name TEXT;

    ALTER TABLE products
        ADD COLUMN IF NOT EXISTS name TEXT,
        ADD COLUMN IF NOT EXISTS price_cents INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS photo_url TEXT,
        ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE,
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

    CREATE TABLE IF NOT EXISTS orders (
        id               SERIAL PRIMARY KEY,
        user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        total_cents      INTEGER NOT NULL,
        cashback_cents   INTEGER NOT NULL DEFAULT 0,
        status           TEXT NOT NULL DEFAULT 'new', -- new|paid|canceled
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS order_items (
        id           SERIAL PRIMARY KEY,
        order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        product_id   INTEGER NOT NULL REFERENCES products(id),
        quantity     INTEGER NOT NULL CHECK (quantity > 0),
        unit_price_cents INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS wallet_txns (
        id           SERIAL PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        change_cents INTEGER NOT NULL, -- + یا -
        method       TEXT,             -- recharge|purchase|cashback|manual
        note         TEXT,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    _exec(ddl)


# ---------- users ----------
def upsert_user(telegram_id: int, name: Optional[str]) -> int:
    """
    اگر کاربر وجود نداشت بساز، اگر بود نامش را آپدیت کن.
    خروجی: id داخلی جدول users
    """
    sql = """
    INSERT INTO users (telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id)
    DO UPDATE SET name = COALESCE(EXCLUDED.name, users.name)
    RETURNING id;
    """
    row = _fetchone(sql, (telegram_id, name))
    return int(row[0])


def get_user_by_tid(telegram_id: int) -> Optional[Dict[str, Any]]:
    row = _fetchone(
        "SELECT id, telegram_id, name, phone, address, wallet_balance_cents "
        "FROM users WHERE telegram_id = %s",
        (telegram_id,),
    )
    if not row:
        return None
    return {
        "id": row[0],
        "telegram_id": row[1],
        "name": row[2],
        "phone": row[3],
        "address": row[4],
        "wallet_balance_cents": row[5],
    }


def update_user_contact(telegram_id: int, phone: Optional[str], address: Optional[str]) -> None:
    _exec(
        "UPDATE users SET phone = %s, address = %s WHERE telegram_id = %s",
        (phone, address, telegram_id),
    )


# ---------- wallet ----------
def get_wallet_balance_cents(telegram_id: int) -> int:
    row = _fetchone("SELECT wallet_balance_cents FROM users WHERE telegram_id=%s", (telegram_id,))
    return int(row[0]) if row else 0


def _wallet_change(user_id: int, delta_cents: int, method: str, note: Optional[str]) -> None:
    _exec(
        "UPDATE users SET wallet_balance_cents = wallet_balance_cents + %s WHERE id = %s",
        (delta_cents, user_id),
    )
    _exec(
        "INSERT INTO wallet_txns (user_id, change_cents, method, note) VALUES (%s, %s, %s, %s)",
        (user_id, delta_cents, method, note),
    )


def add_wallet_funds(telegram_id: int, amount_cents: int, note: str = "recharge", method: str = "recharge") -> int:
    user = get_user_by_tid(telegram_id)
    if not user:
        uid = upsert_user(telegram_id, None)
    else:
        uid = user["id"]
    _wallet_change(uid, amount_cents, method, note)
    return get_wallet_balance_cents(telegram_id)


# ---------- products ----------
def add_product(name: str, price_cents: int, photo_url: Optional[str]) -> int:
    row = _fetchone(
        "INSERT INTO products (name, price_cents, photo_url, active) VALUES (%s,%s,%s,TRUE) RETURNING id",
        (name, price_cents, photo_url),
    )
    return int(row[0])


def set_product_active(product_id: int, active: bool) -> None:
    _exec("UPDATE products SET active=%s WHERE id=%s", (active, product_id))


def list_products(only_active: bool = True) -> List[Dict[str, Any]]:
    if only_active:
        rows = _fetchall(
            "SELECT id, name, price_cents, photo_url, active FROM products WHERE active = TRUE ORDER BY id DESC"
        )
    else:
        rows = _fetchall(
            "SELECT id, name, price_cents, photo_url, active FROM products ORDER BY id DESC"
        )
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {"id": r[0], "name": r[1], "price_cents": r[2], "photo_url": r[3], "active": r[4]}
        )
    return out


def get_product(product_id: int) -> Optional[Dict[str, Any]]:
    r = _fetchone("SELECT id, name, price_cents, photo_url, active FROM products WHERE id=%s", (product_id,))
    if not r:
        return None
    return {"id": r[0], "name": r[1], "price_cents": r[2], "photo_url": r[3], "active": r[4]}


# ---------- orders ----------
def create_order(telegram_id: int, items: List[Tuple[int, int]]) -> int:
    """
    items: list of (product_id, quantity)
    - جمع کل را می‌سازد
    - کش‌بک را طبق CASHBACK_PERCENT محاسبه و به کیف پول اضافه می‌کند
    خروجی: order_id
    """
    user = get_user_by_tid(telegram_id)
    user_id = user["id"] if user else upsert_user(telegram_id, None)

    # محاسبه جمع کل
    total = 0
    products_map: Dict[int, Dict[str, Any]] = {}
    for pid, qty in items:
        prod = get_product(pid)
        if not prod or not prod["active"]:
            raise ValueError("محصول نامعتبر یا غیرفعال است")
        total += prod["price_cents"] * qty
        products_map[pid] = prod

    cashback_cents = (total * CASHBACK_PERCENT) // 100

    # ثبت سفارش
    row = _fetchone(
        "INSERT INTO orders (user_id, total_cents, cashback_cents, status) VALUES (%s,%s,%s,'new') RETURNING id",
        (user_id, total, cashback_cents),
    )
    order_id = int(row[0])

    # آیتم‌ها
    for pid, qty in items:
        prod = products_map[pid]
        _exec(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price_cents) VALUES (%s,%s,%s,%s)",
            (order_id, pid, qty, prod["price_cents"]),
        )

    # کش‌بک به کیف پول
    if cashback_cents > 0:
        _wallet_change(user_id, cashback_cents, "cashback", f"cashback {CASHBACK_PERCENT}% for order #{order_id}")

    return order_id


def get_order_summary(order_id: int) -> Dict[str, Any]:
    order = _fetchone(
        "SELECT id, user_id, total_cents, cashback_cents, status, created_at FROM orders WHERE id=%s",
        (order_id,),
    )
    if not order:
        raise ValueError("order not found")

    items = _fetchall(
        "SELECT product_id, quantity, unit_price_cents FROM order_items WHERE order_id=%s",
        (order_id,),
    )
    return {
        "id": order[0],
        "user_id": order[1],
        "total_cents": order[2],
        "cashback_cents": order[3],
        "status": order[4],
        "created_at": order[5],
        "items": [{"product_id": r[0], "qty": r[1], "unit_price_cents": r[2]} for r in items],
    }


# ---------- handy helpers used by handlers ----------
def ensure_user_and_get_id(telegram_id: int, name: Optional[str]) -> int:
    """برای هندلرها؛ مطمئن می‌شود کاربر وجود دارد و id داخلی را برمی‌گرداند."""
    user = get_user_by_tid(telegram_id)
    return user["id"] if user else upsert_user(telegram_id, name)


def reset_demo_data() -> None:
    """اختیاری برای تست محلی"""
    _exec("DELETE FROM order_items;")
    _exec("DELETE FROM orders;")
    _exec("DELETE FROM products;")
    _exec("DELETE FROM wallet_txns;")
    _exec("DELETE FROM users;")
