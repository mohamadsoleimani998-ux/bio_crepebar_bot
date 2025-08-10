# src/db.py
import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ["DATABASE_URL"]

def get_conn():
    # Render/Neon معمولاً SSL می‌خواهد
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    """ساخت/اصلاح اسکیمای لازم بدون اینکه سرویس از لایو خارج شود."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            # جدول کاربران: اگر نبود بساز
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    tg_id BIGINT PRIMARY KEY,
                    wallet_cents INT NOT NULL DEFAULT 0,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE
                );
            """)
            # اگر قبلاً users ساخته شده ولی ستون‌های ما را ندارد، اضافه کن
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tg_id BIGINT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_cents INT NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;")
            # اگر Primary Key روی tg_id نیست، حداقل یکتا باشد
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes
                        WHERE tablename = 'users' AND indexname = 'users_tg_id_uq'
                    ) THEN
                        CREATE UNIQUE INDEX users_tg_id_uq ON users(tg_id);
                    END IF;
                END $$;
            """)

            # جدول محصولات
            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    price_cents INT NOT NULL,
                    caption TEXT,
                    photo_file_id TEXT
                );
            """)

def get_or_create_user(tg_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s;",
                (tg_id,),
            )
            row = cur.fetchone()
            if row is None:
                # اگر کاربر نبود، بساز
                cur.execute(
                    "INSERT INTO users (tg_id) VALUES (%s) ON CONFLICT (tg_id) DO NOTHING;",
                    (tg_id,),
                )
                cur.execute(
                    "SELECT tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s;",
                    (tg_id,),
                )
                row = cur.fetchone()
            return row  # dict با کلیدهای tg_id, wallet_cents, is_admin

def get_wallet(tg_id: int) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s;", (tg_id,))
            r = cur.fetchone()
            return int(r[0]) if r else 0

def list_products():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, title, price_cents, caption, photo_file_id
                FROM products
                ORDER BY id DESC;
            """)
            return cur.fetchall()

def add_product(title: str, price_cents: int, caption: str | None, photo_file_id: str | None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO products (title, price_cents, caption, photo_file_id)
                VALUES (%s, %s, %s, %s);
                """,
                (title, price_cents, caption, photo_file_id),
            )
