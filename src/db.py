import os
import ssl
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DB_URL = os.getenv("DATABASE_URL")

def _conn():
    if not DB_URL:
        raise RuntimeError("DATABASE_URL is not set")
    # Neon به SSL نیاز دارد
    return psycopg2.connect(DB_URL, sslmode="require")

@contextmanager
def get_cursor():
    conn = _conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

def init_db():
    """ایمن: اگر نبود می‌سازد، اگر بود کاری نمی‌کند."""
    with get_cursor() as cur:
        # users
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              SERIAL PRIMARY KEY,
                tg_id           BIGINT UNIQUE,
                full_name       TEXT,
                username        TEXT,
                wallet_cents    BIGINT DEFAULT 0,
                is_admin        BOOLEAN DEFAULT FALSE
            );
        """)
        # ستون‌ها را در صورت نبود اضافه کن (برای سازگاری با نسخه‌های قبل)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_cents BIGINT DEFAULT 0;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;")

        # products
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id              SERIAL PRIMARY KEY,
                name            TEXT NOT NULL,
                price_cents     BIGINT NOT NULL,
                photo_file_id   TEXT,
                created_at      TIMESTAMPTZ DEFAULT now()
            );
        """)

def get_or_create_user(tg_id: int, full_name: str = None, username: str = None):
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO users (tg_id, full_name, username)
            VALUES (%s, %s, %s)
            ON CONFLICT (tg_id)
            DO UPDATE SET full_name = EXCLUDED.full_name,
                          username  = EXCLUDED.username
            RETURNING id, tg_id, wallet_cents, is_admin, full_name, username;
        """, (tg_id, full_name, username))
        return cur.fetchone()

def get_wallet(tg_id: int) -> int:
    with get_cursor() as cur:
        cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s;", (tg_id,))
        row = cur.fetchone()
        return int(row["wallet_cents"]) if row else 0

def list_products():
    with get_cursor() as cur:
        cur.execute("""
            SELECT id, name, price_cents, photo_file_id
            FROM products
            ORDER BY id DESC
            LIMIT 20;
        """)
        return cur.fetchall()

def add_product(name: str, price_cents: int, photo_file_id: str):
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO products (name, price_cents, photo_file_id)
            VALUES (%s, %s, %s)
            RETURNING id;
        """, (name, price_cents, photo_file_id))
        return cur.fetchone()["id"]
