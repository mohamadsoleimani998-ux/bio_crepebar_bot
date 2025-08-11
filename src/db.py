import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from typing import Optional, List, Tuple, Dict, Any

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            address TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS products(
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price INT NOT NULL,
            photo_url TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS wallets(
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            balance INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS transactions(
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount INT NOT NULL,
            kind TEXT NOT NULL,      -- 'order','cashback','topup','adjust'
            meta TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS orders(
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            full_name TEXT,
            phone TEXT,
            address TEXT,
            total INT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS order_items(
            id SERIAL PRIMARY KEY,
            order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id INT NOT NULL REFERENCES products(id),
            quantity INT NOT NULL,
            price INT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS topups(
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount INT NOT NULL,
            method TEXT NOT NULL,    -- 'card'
            note TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        cur.close()

def get_or_create_user(user_id: int, first_name: str = "", last_name: str = ""):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM users WHERE user_id=%s;", (user_id,))
        row = cur.fetchone()
        if row:
            return row
        cur.execute(
            "INSERT INTO users(user_id,first_name,last_name) VALUES(%s,%s,%s) RETURNING *;",
            (user_id, first_name, last_name)
        )
        return cur.fetchone()

def upsert_user_contact(user_id: int, full_name: str, phone: str, address: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users(user_id, first_name, phone, address)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
              first_name=EXCLUDED.first_name,
              phone=EXCLUDED.phone,
              address=EXCLUDED.address;
        """, (user_id, full_name, phone, address))

def ensure_wallet(user_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO wallets(user_id) VALUES(%s) ON CONFLICT (user_id) DO NOTHING;", (user_id,))

def get_wallet(user_id: int) -> int:
    ensure_wallet(user_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT balance FROM wallets WHERE user_id=%s;", (user_id,))
        bal = cur.fetchone()
        return int(bal[0]) if bal else 0

def add_balance(user_id: int, amount: int, kind: str, meta: str = ""):
    ensure_wallet(user_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE wallets SET balance = balance + %s WHERE user_id=%s;", (amount, user_id))
        cur.execute("INSERT INTO transactions(user_id, amount, kind, meta) VALUES (%s,%s,%s,%s);",
                    (user_id, amount, kind, meta))

def deduct_balance(user_id: int, amount: int) -> bool:
    ensure_wallet(user_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT balance FROM wallets WHERE user_id=%s FOR UPDATE;", (user_id,))
        bal = cur.fetchone()
        if not bal or bal[0] < amount:
            return False
        cur.execute("UPDATE wallets SET balance = balance - %s WHERE user_id=%s;", (amount, user_id))
        cur.execute("INSERT INTO transactions(user_id, amount, kind) VALUES (%s,%s,'order');",
                    (user_id, -amount))
        return True

# Products
def add_product(name: str, price: int, photo_url: Optional[str]) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO products(name, price, photo_url) VALUES(%s,%s,%s) RETURNING id;",
            (name, price, photo_url)
        )
        return cur.fetchone()[0]

def list_products() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT id, name, price, photo_url FROM products WHERE is_active=TRUE ORDER BY id;")
        return [dict(r) for r in cur.fetchall()]

def get_product(pid: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT id,name,price,photo_url FROM products WHERE id=%s AND is_active=TRUE;", (pid,))
        row = cur.fetchone()
        return dict(row) if row else None

def deactivate_product(pid: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE products SET is_active=FALSE WHERE id=%s;", (pid,))

# Orders
def create_order(user_id: int, full_name: str, phone: str, address: str,
                 items: List[Tuple[int, int]]) -> int:
    """
    items: list of tuples (product_id, quantity)
    """
    with get_conn() as conn:
        cur = conn.cursor()
        # calc total
        total = 0
        prod_prices = {}
        for pid, qty in items:
            cur.execute("SELECT price FROM products WHERE id=%s;", (pid,))
            r = cur.fetchone()
            if not r:
                continue
            price = int(r[0])
            prod_prices[pid] = price
            total += price * qty

        cur.execute("""
            INSERT INTO orders(user_id, full_name, phone, address, total)
            VALUES (%s,%s,%s,%s,%s) RETURNING id;
        """, (user_id, full_name, phone, address, total))
        order_id = cur.fetchone()[0]

        for pid, qty in items:
            if pid in prod_prices:
                cur.execute("""
                    INSERT INTO order_items(order_id, product_id, quantity, price)
                    VALUES (%s,%s,%s,%s);
                """, (order_id, pid, qty, prod_prices[pid]))
        return order_id
