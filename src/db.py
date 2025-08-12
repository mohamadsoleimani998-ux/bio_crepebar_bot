import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")
CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "3"))

def _conn():
    return psycopg2.connect(DATABASE_URL)

# ------------ schema -------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    name TEXT,
    phone TEXT,
    address TEXT,
    wallet BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    price BIGINT NOT NULL,
    photo TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    items JSONB NOT NULL,           -- [{product_id, qty, price}]
    total BIGINT NOT NULL,
    cashback BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'new',
    address TEXT,
    phone TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

def init_db():
    with _conn() as cn:
        with cn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
    return True

# ------------ users -------------
def upsert_user(telegram_id: int, name: str):
    sql = """
    INSERT INTO users (telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id) DO UPDATE
      SET name = EXCLUDED.name
    RETURNING id, telegram_id, name, phone, address, wallet;
    """
    with _conn() as cn:
        with cn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (telegram_id, name))
            return cur.fetchone()

def get_user(telegram_id: int):
    with _conn() as cn:
        with cn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE telegram_id=%s", (telegram_id,))
            return cur.fetchone()

def set_user_contact(telegram_id: int, phone: str = None, address: str = None, name: str = None):
    # به اندازه‌ی مقادیرِ داده‌شده آپدیت می‌کنیم
    fields, vals = [], []
    if phone is not None:
        fields.append("phone=%s"); vals.append(phone)
    if address is not None:
        fields.append("address=%s"); vals.append(address)
    if name is not None:
        fields.append("name=%s"); vals.append(name)
    if not fields:
        return get_user(telegram_id)
    vals.append(telegram_id)
    sql = f"UPDATE users SET {', '.join(fields)} WHERE telegram_id=%s RETURNING *"
    with _conn() as cn:
        with cn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, tuple(vals))
            return cur.fetchone()

def adjust_wallet(telegram_id: int, delta: int):
    sql = """
    UPDATE users SET wallet = GREATEST(0, wallet + %s)
    WHERE telegram_id=%s
    RETURNING wallet;
    """
    with _conn() as cn:
        with cn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (delta, telegram_id))
            row = cur.fetchone()
            return row["wallet"] if row else 0

def get_wallet(telegram_id: int) -> int:
    u = get_user(telegram_id)
    return int(u["wallet"]) if u else 0

# ------------ products -------------
def add_product(title: str, price: int, photo: str | None):
    with _conn() as cn:
        with cn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO products(title, price, photo) VALUES(%s,%s,%s) RETURNING *",
                (title, price, photo)
            )
            return cur.fetchone()

def update_product(pid: int, title: str | None = None, price: int | None = None, photo: str | None = None):
    fields, vals = [], []
    if title is not None:
        fields.append("title=%s"); vals.append(title)
    if price is not None:
        fields.append("price=%s"); vals.append(price)
    if photo is not None:
        fields.append("photo=%s"); vals.append(photo)
    if not fields:
        return get_product(pid)
    vals.append(pid)
    sql = f"UPDATE products SET {', '.join(fields)} WHERE id=%s RETURNING *"
    with _conn() as cn:
        with cn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, tuple(vals))
            return cur.fetchone()

def get_product(pid: int):
    with _conn() as cn:
        with cn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
            return cur.fetchone()

def list_products():
    with _conn() as cn:
        with cn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM products ORDER BY id DESC")
            return cur.fetchall()

# ------------ orders -------------
def create_order(telegram_id: int, items: list, address: str, phone: str):
    # items: [{"product_id":1,"qty":2}]
    with _conn() as cn:
        with cn.cursor(cursor_factory=RealDictCursor) as cur:
            # کاربر
            cur.execute("SELECT id, wallet FROM users WHERE telegram_id=%s", (telegram_id,))
            u = cur.fetchone()
            if not u:
                raise RuntimeError("user not found")
            # محاسبه مبلغ
            pids = tuple([it["product_id"] for it in items]) or (0,)
            cur.execute(f"SELECT id, price FROM products WHERE id IN %s", (pids,))
            price_map = {r["id"]: int(r["price"]) for r in cur.fetchall()}
            total = sum(int(it["qty"]) * price_map.get(int(it["product_id"]), 0) for it in items)
            cashback = total * CASHBACK_PERCENT // 100
            # ساخت سفارش
            cur.execute(
                "INSERT INTO orders(user_id, items, total, cashback, address, phone) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
                (u["id"], psycopg2.extras.Json(items), total, cashback, address, phone)
            )
            order = cur.fetchone()
            # افزودن کش‌بک به کیف پول
            cur.execute("UPDATE users SET wallet = wallet + %s WHERE id=%s", (cashback, u["id"]))
            return order
