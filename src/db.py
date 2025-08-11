import os
import json
import psycopg2
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL".upper())
CASHBACK_PERCENT = int(os.environ.get("CASHBACK_PERCENT", "3"))

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            name TEXT,
            phone TEXT,
            address TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS products(
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            photo_url TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS orders(
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            items JSONB NOT NULL,          -- [{id,name,price,qty}]
            total_price INTEGER NOT NULL,
            address TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS wallet_txns(
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            amount INTEGER NOT NULL,       -- positive: credit, negative: debit
            kind TEXT NOT NULL,            -- 'topup','order','cashback','manual'
            note TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        conn.commit()

# ---------- users ----------
def upsert_user(tg_id: int, name: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        INSERT INTO users(telegram_id, name)
        VALUES (%s, %s)
        ON CONFLICT (telegram_id) DO UPDATE SET name = EXCLUDED.name
        RETURNING id;
        """, (tg_id, name))
        user_id = cur.fetchone()[0]
        conn.commit()
        return user_id

def set_user_info(tg_id: int, phone: str = None, address: str = None, name: str = None):
    fields, vals = [], []
    if name is not None:
        fields.append("name=%s"); vals.append(name)
    if phone is not None:
        fields.append("phone=%s"); vals.append(phone)
    if address is not None:
        fields.append("address=%s"); vals.append(address)
    if not fields:
        return
    vals.append(tg_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE telegram_id=%s", vals)
        conn.commit()

def get_user_by_tg(tg_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, telegram_id, name, phone, address FROM users WHERE telegram_id=%s", (tg_id,))
        row = cur.fetchone()
        if not row: return None
        return {"id": row[0], "telegram_id": row[1], "name": row[2], "phone": row[3], "address": row[4]}

# ---------- products ----------
def add_product(name: str, price: int, photo_url: str | None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO products(name,price,photo_url) VALUES(%s,%s,%s) RETURNING id",
                    (name, price, photo_url))
        pid = cur.fetchone()[0]
        conn.commit()
        return pid

def get_products():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id,name,price,photo_url FROM products ORDER BY id DESC")
        return [{"id": r[0], "name": r[1], "price": r[2], "photo_url": r[3]} for r in cur.fetchall()]

def delete_product(pid: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE id=%s", (pid,))
        conn.commit()

# ---------- wallet ----------
def wallet_balance(user_id: int) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM wallet_txns WHERE user_id=%s", (user_id,))
        return cur.fetchone()[0] or 0

def add_wallet(user_id: int, amount: int, kind: str, note: str = None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO wallet_txns(user_id,amount,kind,note) VALUES(%s,%s,%s,%s)",
                    (user_id, amount, kind, note))
        conn.commit()

# ---------- orders ----------
def create_order(user_id: int, items: list[dict], total: int, address: str, phone: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO orders(user_id,items,total_price,address,phone) VALUES(%s,%s,%s,%s,%s) RETURNING id",
            (user_id, json.dumps(items), total, address, phone)
        )
        oid = cur.fetchone()[0]
        # برداشت از کیف پول (اگر مثبت نباشد برداشت نمی‌کنیم)
        if total > 0:
            add_wallet(user_id, -total, "order", f"سفارش #{oid}")
            # کش‌بک
            cashback = (total * CASHBACK_PERCENT) // 100
            if cashback > 0:
                add_wallet(user_id, cashback, "cashback", f"{CASHBACK_PERCENT}% کش‌بک سفارش #{oid}")
        conn.commit()
        return oid
