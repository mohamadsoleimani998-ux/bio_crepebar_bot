import os
import psycopg2
from psycopg2.extras import RealDictCursor

# ------------------ اتصال به دیتابیس ------------------
def get_connection():
    dsn = os.getenv("DATABASE_URL")
    if "sslmode" not in dsn:
        dsn = dsn + ("&" if "?" in dsn else "?") + "sslmode=require"
    return psycopg2.connect(dsn, cursor_factory=RealDictCursor)

# ------------------ ایجاد یا آپدیت جداول ------------------
def _get_conn():
    dsn = os.getenv("DATABASE_URL")
    if "sslmode" not in dsn:
        dsn = dsn + ("&" if "?" in dsn else "?") + "sslmode=require"
    return psycopg2.connect(dsn)

_SCHEMA_SQL = """
-- جدول کاربران
CREATE TABLE IF NOT EXISTS users (
  id           BIGSERIAL PRIMARY KEY,
  tg_id        BIGINT UNIQUE NOT NULL,
  wallet_cents INTEGER NOT NULL DEFAULT 0,
  is_admin     BOOLEAN NOT NULL DEFAULT FALSE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS wallet_cents INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS is_admin     BOOLEAN NOT NULL DEFAULT FALSE;

-- جدول محصولات
CREATE TABLE IF NOT EXISTS products (
  id            BIGSERIAL PRIMARY KEY,
  title         TEXT NOT NULL,
  price_cents   INTEGER NOT NULL,
  photo_file_id TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

def ensure_schema():
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_SQL)
        print("DB schema ensured.")
    except Exception as e:
        print("ensure_schema error:", repr(e))

# ------------------ توابع کمکی ------------------
def get_or_create_user(tg_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, wallet_cents, is_admin FROM users WHERE tg_id=%s", (tg_id,))
            user = cur.fetchone()
            if not user:
                cur.execute("INSERT INTO users (tg_id) VALUES (%s) RETURNING id, wallet_cents, is_admin", (tg_id,))
                user = cur.fetchone()
        return user

def get_products():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, price_cents, photo_file_id FROM products ORDER BY id")
            return cur.fetchall()
