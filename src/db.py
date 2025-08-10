# src/db.py
import os
import psycopg2
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(",", " ").split() if x.strip().isdigit()]

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """
    ایجاد/همسان‌سازی امن اسکیمای لازم.
    موجود باشد، تغییری نمی‌دهد؛ موجود نباشد، می‌سازد.
    """
    with get_conn() as conn:
        cur = conn.cursor()

        # === جدول کاربران
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           BIGSERIAL PRIMARY KEY,
            tg_id        BIGINT UNIQUE NOT NULL,
            first_name   TEXT,
            last_name    TEXT,
            wallet_cents INTEGER NOT NULL DEFAULT 0,
            is_admin     BOOLEAN NOT NULL DEFAULT FALSE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        # ستون‌هایی که ممکن است در DB فعلی نباشند، اضافه شوند
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS tg_id BIGINT;""")
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;""")
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name TEXT;""")
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_cents INTEGER NOT NULL DEFAULT 0;""")
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;""")
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();""")
        # یکتا بودن tg_id (اگر قبلاً نبود)
        cur.execute("""DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'users_tg_id_key'
            ) THEN
                BEGIN
                    ALTER TABLE users ADD CONSTRAINT users_tg_id_key UNIQUE (tg_id);
                EXCEPTION WHEN duplicate_table THEN
                    -- اگر قبلاً وجود دارد، نادیده بگیر
                END;
            END IF;
        END$$;""")

        # === جدول محصولات
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id            BIGSERIAL PRIMARY KEY,
            name          TEXT NOT NULL,
            price_cents   INTEGER NOT NULL,
            photo_file_id TEXT,
            caption       TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        cur.execute("""ALTER TABLE products ADD COLUMN IF NOT EXISTS name TEXT;""")
        cur.execute("""ALTER TABLE products ADD COLUMN IF NOT EXISTS price_cents INTEGER;""")
        cur.execute("""ALTER TABLE products ADD COLUMN IF NOT EXISTS photo_file_id TEXT;""")
        cur.execute("""ALTER TABLE products ADD COLUMN IF NOT EXISTS caption TEXT;""")
        cur.execute("""ALTER TABLE products ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();""")

        conn.commit()
        cur.close()

        # بعد از ساخت جداول، ادمین‌ها را ست کن (ایمن)
        set_admins(ADMIN_IDS)

def set_admins(admin_ids):
    """لیست ادمین‌ها را طبق ENV به‌روز می‌کند (اگر کاربر نبود، می‌سازد)."""
    if not admin_ids:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        for tg_id in admin_ids:
            # اگر نبود، بساز؛ اگر بود، is_admin را True کن
            cur.execute("""
                INSERT INTO users (tg_id, is_admin)
                VALUES (%s, TRUE)
                ON CONFLICT (tg_id) DO UPDATE SET is_admin = TRUE;
            """, (tg_id,))
        conn.commit()
        cur.close()

def get_or_create_user(tg_id, first_name=None, last_name=None):
    """کاربر را برمی‌گرداند؛ اگر وجود نداشت، می‌سازد."""
    with get_conn() as conn:
        cur = conn.cursor()
        # سعی کن بخوانی
        cur.execute("SELECT id, tg_id, first_name, last_name, wallet_cents, is_admin FROM users WHERE tg_id=%s;", (tg_id,))
        row = cur.fetchone()
        if row:
            cur.close()
            return row

        # اگر نبود، بساز
        cur.execute("""
            INSERT INTO users (tg_id, first_name, last_name)
            VALUES (%s, %s, %s)
            RETURNING id, tg_id, first_name, last_name, wallet_cents, is_admin;
        """, (tg_id, first_name, last_name))
        user = cur.fetchone()
        conn.commit()
        cur.close()
        return user

def get_wallet(tg_id):
    """موجودی کیف پول بر حسب تومان (تبدیل از ریال/سِنت داخلی)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s;", (tg_id,))
        row = cur.fetchone()
        cur.close()
        return (row[0] if row else 0)

def list_products():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, price_cents, photo_file_id, caption
            FROM products
            ORDER BY id DESC
            LIMIT 50;
        """)
        rows = cur.fetchall()
        cur.close()
        return rows

def add_product(name, price_cents, photo_file_id=None, caption=None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO products (name, price_cents, photo_file_id, caption)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """, (name, price_cents, photo_file_id, caption))
        pid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return pid
