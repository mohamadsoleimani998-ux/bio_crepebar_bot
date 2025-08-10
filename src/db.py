import psycopg2
from psycopg2.extras import RealDictCursor
from .base import DATABASE_URL

def _conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    """ساخت/به‌روزرسانی امن اسکیمای لازم (Idempotent)."""
    with _conn() as conn, conn.cursor() as cur:
        # جدول کاربران
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id BIGINT PRIMARY KEY,
                first_name TEXT,
                last_name  TEXT,
                username   TEXT,
                wallet_cents INTEGER NOT NULL DEFAULT 0,
                is_admin   BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        # اطمینان از وجود ستون‌ها (اگر نسخه قبلی ناقص بود)
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name   TEXT;""")
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name    TEXT;""")
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS username     TEXT;""")
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_cents INTEGER NOT NULL DEFAULT 0;""")
        cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin     BOOLEAN  NOT NULL DEFAULT FALSE;""")

        # جدول محصولات ساده
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                price_cents INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

def get_or_create_user(tg_user):
    """بر اساس tg_user (شیء یوزر تلگرام)، اگر نبود بساز و برگردون."""
    uid = tg_user.get("id")
    first = tg_user.get("first_name")
    last  = tg_user.get("last_name")
    uname = tg_user.get("username")

    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s;", (uid,))
        row = cur.fetchone()
        if row:
            return row

        cur.execute("""
            INSERT INTO users (tg_id, first_name, last_name, username)
            VALUES (%s, %s, %s, %s)
            RETURNING tg_id, wallet_cents, is_admin;
        """, (uid, first, last, uname))
        return cur.fetchone()

def get_wallet(tg_id: int) -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s;", (tg_id,))
        r = cur.fetchone()
        return int(r[0]) if r else 0

def list_products():
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, title, price_cents FROM products ORDER BY id;")
        return cur.fetchall()
