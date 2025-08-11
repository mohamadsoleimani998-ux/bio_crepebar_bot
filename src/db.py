import os
import json
import psycopg2
from psycopg2.extras import Json
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL".upper()) or os.getenv("DATABASE_URL".lower())
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env is missing")

_conn = psycopg2.connect(DATABASE_URL)
_conn.autocommit = True

def _init():
    with _conn.cursor() as cur:
        # کاربران
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            name TEXT,
            phone TEXT,
            address TEXT,
            wallet BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)
        # محصولات
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price BIGINT NOT NULL,
            photo_url TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)
        # سفارش‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            items JSONB NOT NULL,   -- [{"id":1,"qty":2,"name":"...", "price":30000}, ...]
            total BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)
        # شارژها/تراکنش‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS topups (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount BIGINT NOT NULL,
            method TEXT NOT NULL,   -- "card2card" | "gateway"
            ref TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """)

_init()

# --- کاربران ---
def get_or_create_user(user_id: int):
    with _conn.cursor() as cur:
        cur.execute("SELECT user_id, name, phone, address, wallet FROM users WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        if row:
            return {"user_id": row[0], "name": row[1], "phone": row[2], "address": row[3], "wallet": row[4]}
        cur.execute("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        return {"user_id": user_id, "name": None, "phone": None, "address": None, "wallet": 0}

def update_user_profile(user_id: int, name=None, phone=None, address=None):
    with _conn.cursor() as cur:
        cur.execute("""
            UPDATE users
            SET name = COALESCE(%s, name),
                phone = COALESCE(%s, phone),
                address = COALESCE(%s, address)
            WHERE user_id = %s
        """, (name, phone, address, user_id))

def get_wallet(user_id: int) -> int:
    with _conn.cursor() as cur:
        cur.execute("SELECT wallet FROM users WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        return int(row[0] if row else 0)

def add_wallet(user_id: int, delta: int):
    with _conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users (user_id, wallet) VALUES (%s, GREATEST(%s,0))
            ON CONFLICT (user_id) DO UPDATE SET wallet = users.wallet + EXCLUDED.wallet
        """, (user_id, delta))

# --- محصولات ---
def add_product(name: str, price: int, photo_url: str | None):
    with _conn.cursor() as cur:
        cur.execute("INSERT INTO products (name, price, photo_url) VALUES (%s,%s,%s)", (name, price, photo_url))

def edit_product(pid: int, name=None, price=None, photo_url=None):
    with _conn.cursor() as cur:
        cur.execute("""
            UPDATE products
            SET name = COALESCE(%s, name),
                price = COALESCE(%s, price),
                photo_url = COALESCE(%s, photo_url)
            WHERE id = %s
        """, (name, price, photo_url, pid))

def delete_product(pid: int):
    with _conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE id=%s", (pid,))

def list_products():
    with _conn.cursor() as cur:
        cur.execute("SELECT id, name, price, photo_url FROM products ORDER BY id ASC")
        return [{"id": r[0], "name": r[1], "price": int(r[2]), "photo_url": r[3]} for r in cur.fetchall()]

def get_product(pid: int):
    with _conn.cursor() as cur:
        cur.execute("SELECT id, name, price, photo_url FROM products WHERE id=%s", (pid,))
        r = cur.fetchone()
        if not r:
            return None
        return {"id": r[0], "name": r[1], "price": int(r[2]), "photo_url": r[3]}

# --- سفارش ---
def create_order(user_id: int, items: list[dict], total: int, status: str = "pending") -> int:
    with _conn.cursor() as cur:
        cur.execute(
            "INSERT INTO orders (user_id, items, total, status) VALUES (%s, %s, %s, %s) RETURNING id",
            (user_id, Json(items), total, status)
        )
        return int(cur.fetchone()[0])

def list_user_orders(user_id: int):
    with _conn.cursor() as cur:
        cur.execute("SELECT id, items, total, status, created_at FROM orders WHERE user_id=%s ORDER BY id DESC", (user_id,))
        out = []
        for r in cur.fetchall():
            out.append({"id": r[0], "items": r[1], "total": int(r[2]), "status": r[3], "created_at": r[4]})
        return out

# --- شارژ ---
def create_topup(user_id: int, amount: int, method: str, ref: str | None):
    with _conn.cursor() as cur:
        cur.execute(
            "INSERT INTO topups (user_id, amount, method, ref) VALUES (%s,%s,%s,%s)",
            (user_id, amount, method, ref)
        )

def confirm_topup(user_id: int, amount: int):
    add_wallet(user_id, amount)
