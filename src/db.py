import os
import ssl
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

_conn = None

def get_conn():
    global _conn
    if _conn and not _conn.closed:
        return _conn
    ctx = ssl.create_default_context()
    _conn = psycopg2.connect(DATABASE_URL, sslmode="require", sslrootcert=None)
    _conn.autocommit = True
    return _conn

def init_db():
    """
    ساخت امن جداول/ستون‌ها. اگر از قبل باشند تغییری نمی‌دهد.
    """
    conn = get_conn()
    with conn.cursor() as cur:
        # users
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id BIGINT PRIMARY KEY,
                wallet_cents INT NOT NULL DEFAULT 0,
                is_admin BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)
        # products
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                price_cents INT NOT NULL,
                photo_file_id TEXT
            );
        """)
        # اطمینان از وجود ستون‌ها (برای دیتابیس‌های قبلی)
        for sql in [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_cents INT NOT NULL DEFAULT 0;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS photo_file_id TEXT;"
        ]:
            cur.execute(sql)
    print("init_db done")

def set_admins(admin_ids: set[int]):
    if not admin_ids:
        return
    conn = get_conn()
    with conn.cursor() as cur:
        for aid in admin_ids:
            cur.execute("""
                INSERT INTO users (tg_id, is_admin)
                VALUES (%s, TRUE)
                ON CONFLICT (tg_id) DO UPDATE SET is_admin = TRUE;
            """, (aid,))

def get_or_create_user(tg_id: int) -> dict:
    conn = get_conn()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s;", (tg_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        cur.execute("INSERT INTO users (tg_id) VALUES (%s) ON CONFLICT DO NOTHING;", (tg_id,))
        return {"tg_id": tg_id, "wallet_cents": 0, "is_admin": False}

def get_wallet(tg_id: int) -> int:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s;", (tg_id,))
        r = cur.fetchone()
        return int(r[0]) if r else 0

def list_products() -> list[dict]:
    conn = get_conn()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name, price_cents, photo_file_id FROM products ORDER BY id DESC;")
        return [dict(x) for x in cur.fetchall()]

def add_product(name: str, price_cents: int, photo_file_id: str | None):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO products (name, price_cents, photo_file_id)
            VALUES (%s, %s, %s);
        """, (name, price_cents, photo_file_id))
