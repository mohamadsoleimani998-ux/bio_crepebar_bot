import os
import json
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ["DATABASE_URL"]

def get_conn():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    conn.autocommit = True
    return conn

def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            addr TEXT,
            wallet_balance INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            photo_file_id TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            items JSONB NOT NULL,           -- [{id,name,qty,price}]
            total INTEGER NOT NULL,
            cashback INTEGER DEFAULT 0,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMPTZ DEFAULT now()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            amount INTEGER NOT NULL,         -- ریال، مثبت=واریز، منفی=برداشت
            ttype TEXT NOT NULL,             -- 'topup','order','cashback','refund'
            meta JSONB,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS carts (
            user_id BIGINT PRIMARY KEY,
            items JSONB NOT NULL DEFAULT '[]'::jsonb   -- [{id,qty}]
        );
        """)

# ---------- Users ----------
def upsert_user(user_id:int, name:str=None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users(user_id,name) VALUES(%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET name=COALESCE(EXCLUDED.name, users.name)
        """, (user_id, name))

def update_profile(user_id:int, name:str, phone:str, addr:str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET name=%s, phone=%s, addr=%s WHERE user_id=%s",
                    (name, phone, addr, user_id))

def get_user(user_id:int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
            return cur.fetchone()

# ---------- Wallet ----------
def wallet_balance(user_id:int)->int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT wallet_balance FROM users WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        return row[0] if row else 0

def wallet_change(user_id:int, amount:int, ttype:str, meta:dict=None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET wallet_balance = COALESCE(wallet_balance,0) + %s WHERE user_id=%s",
                    (amount, user_id))
        cur.execute("INSERT INTO transactions(user_id,amount,ttype,meta) VALUES(%s,%s,%s,%s)",
                    (user_id, amount, ttype, json.dumps(meta or {})))

# ---------- Products ----------
def add_product(name:str, price:int, photo_file_id:str|None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO products(name,price,photo_file_id) VALUES(%s,%s,%s)", (name, price, photo_file_id))

def update_product(pid:int, name:str=None, price:int=None, active:bool=None, photo_file_id:str|None=None):
    cols, vals = [], []
    if name is not None: cols.append("name=%s"); vals.append(name)
    if price is not None: cols.append("price=%s"); vals.append(price)
    if active is not None: cols.append("is_active=%s"); vals.append(active)
    if photo_file_id is not None: cols.append("photo_file_id=%s"); vals.append(photo_file_id)
    if not cols: return
    vals.append(pid)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE products SET {', '.join(cols)} WHERE id=%s", vals)

def list_products(offset:int=0, limit:int=6):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT * FROM products WHERE is_active=TRUE
                           ORDER BY id DESC OFFSET %s LIMIT %s""", (offset, limit))
            return cur.fetchall()

def get_product(pid:int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
            return cur.fetchone()

# ---------- Cart ----------
def get_cart(user_id:int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT items FROM carts WHERE user_id=%s", (user_id,))
            r = cur.fetchone()
            return r["items"] if r else []

def save_cart(user_id:int, items:list):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO carts(user_id, items) VALUES(%s, %s::jsonb)
            ON CONFLICT (user_id) DO UPDATE SET items=EXCLUDED.items
        """, (user_id, json.dumps(items)))

def clear_cart(user_id:int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM carts WHERE user_id=%s", (user_id,))

# ---------- Orders ----------
def create_order(user_id:int, items:list, total:int, cashback:int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO orders(user_id, items, total, cashback)
                       VALUES(%s, %s::jsonb, %s, %s) RETURNING id""",
                       (user_id, json.dumps(items), total, cashback))
        return cur.fetchone()[0]

def user_transactions(user_id:int, limit:int=20):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT * FROM transactions WHERE user_id=%s
                           ORDER BY id DESC LIMIT %s""", (user_id, limit))
            return cur.fetchall()
