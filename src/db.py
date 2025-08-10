# src/db.py
import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")

def _conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """ایمن اجرا می‌شود؛ جدول‌ها را می‌سازد و نام ستون tg_id را به user_id مهاجرت می‌دهد."""
    with _conn() as conn:
        with conn.cursor() as cur:
            # ساخت جدول users اگر نبود
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id      BIGINT PRIMARY KEY,
                    username     TEXT,
                    full_name    TEXT,
                    wallet_cents INTEGER NOT NULL DEFAULT 0,
                    is_admin     BOOLEAN NOT NULL DEFAULT FALSE
                );
            """)
            # ساخت جدول products اگر نبود
            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    price_cents INTEGER NOT NULL,
                    description TEXT,
                    photo_file_id TEXT
                );
            """)
            # اگر قبلاً ستونی به نام tg_id بوده و user_id نیست، رینیم کن
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='users';
            """)
            cols = {r[0] for r in cur.fetchall()}
            if "tg_id" in cols and "user_id" not in cols:
                cur.execute('ALTER TABLE users RENAME COLUMN tg_id TO user_id;')
            # اگر هر دلیلی user_id nullable شده بود، not null کن
            cur.execute("""
                ALTER TABLE users
                ALTER COLUMN user_id SET NOT NULL;
            """)

def set_admins(admin_ids):
    """لیست ادمین‌ها را ست می‌کند (اگر کاربر وجود نداشت می‌سازد)."""
    if not admin_ids:
        return
    with _conn() as conn:
        with conn.cursor() as cur:
            for aid in admin_ids:
                cur.execute("""
                    INSERT INTO users (user_id, is_admin)
                    VALUES (%s, TRUE)
                    ON CONFLICT (user_id) DO UPDATE SET is_admin=EXCLUDED.is_admin;
                """, (int(aid),))

def get_or_create_user(user_id: int, username: str = None, full_name: str = None):
    """اگر کاربر نبود می‌سازد. از NULL برای user_id جلوگیری می‌کند."""
    if user_id is None:
        raise ValueError("user_id is None")

    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO users (user_id, username, full_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET username = COALESCE(EXCLUDED.username, users.username),
                    full_name = COALESCE(EXCLUDED.full_name, users.full_name)
                RETURNING user_id, username, full_name, wallet_cents, is_admin;
            """, (int(user_id), username, full_name))
            return cur.fetchone()

def get_wallet(user_id: int) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT wallet_cents FROM users WHERE user_id=%s;", (int(user_id),))
            row = cur.fetchone()
            return int(row[0]) if row else 0

def list_products():
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, name, price_cents, description FROM products ORDER BY id DESC;")
            return cur.fetchall()

def add_product(name: str, price_cents: int, description: str = None, photo_file_id: str = None):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO products (name, price_cents, description, photo_file_id)
                VALUES (%s, %s, %s, %s);
            """, (name, int(price_cents), description, photo_file_id))
