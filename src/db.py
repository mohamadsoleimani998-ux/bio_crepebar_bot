import os
import psycopg2

# به متغیر محیطی Render/Neon وصل می‌شویم
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# اتصال سراسری ساده (کافی برای این پروژه)
conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()

def init_db():
    """ساخت جدول‌ها و ستون‌ها اگر وجود نداشتند (idempotent)"""
    # جدول کاربران
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            tg_id BIGINT UNIQUE,
            wallet_cents INT NOT NULL DEFAULT 0,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    # جدول محصولات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price_cents INT NOT NULL,
            photo_file_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    conn.commit()

def get_or_create_user(tg_id: int):
    """اگر کاربر بود برگردان، نبود بساز"""
    cur.execute(
        "SELECT id, wallet_cents, is_admin FROM users WHERE tg_id=%s",
        (tg_id,)
    )
    row = cur.fetchone()
    if row:
        return row  # (id, wallet_cents, is_admin)

    cur.execute(
        "INSERT INTO users (tg_id) VALUES (%s) RETURNING id, wallet_cents, is_admin",
        (tg_id,)
    )
    created = cur.fetchone()
    conn.commit()
    return created  # (id, wallet_cents, is_admin)

def list_products():
    """لیست محصولات (ساده)"""
    cur.execute(
        "SELECT id, name, price_cents, photo_file_id FROM products ORDER BY id DESC LIMIT 50;"
    )
    return cur.fetchall()

def add_product(name: str, price_cents: int, photo_file_id: str | None = None) -> int:
    """افزودن محصول جدید و برگرداندن id"""
    cur.execute(
        "INSERT INTO products (name, price_cents, photo_file_id) VALUES (%s, %s, %s) RETURNING id;",
        (name, price_cents, photo_file_id),
    )
    pid = cur.fetchone()[0]
    conn.commit()
    return pid
