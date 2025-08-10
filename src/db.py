import os
import sqlite3
from contextlib import contextmanager

USE_PG = False
PG_URL = os.getenv("DATABASE_URL", "").strip()

# اگر DATABASE_URL ست شده بود به Postgres وصل می‌شیم
try:
    if PG_URL.startswith("postgres://") or PG_URL.startswith("postgresql://"):
        import psycopg2  # type: ignore
        USE_PG = True
except Exception:
    USE_PG = False


def _connect_pg():
    # psycopg2 خودش اتو-کمیت نمی‌کند؛ خودمان commit می‌کنیم
    return psycopg2.connect(PG_URL)

def _connect_sqlite():
    # یک فایل ساده محلی (فالبک امن)
    path = os.path.join(os.path.dirname(__file__), "bot.db")
    conn = sqlite3.connect(path, check_same_thread=False)
    return conn

@contextmanager
def get_conn():
    conn = _connect_pg() if USE_PG else _connect_sqlite()
    try:
        yield conn
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass

def _ph(n=1):
    """
    placeholder ساز: در PG از %s و در sqlite از ? استفاده می‌کنیم.
    """
    return ", ".join(["%s" if USE_PG else "?" for _ in range(n)])


# ---------- Bootstrap / Migrations ساده ----------
def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        # users
        if USE_PG:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id BIGINT PRIMARY KEY,
                wallet_cents INTEGER DEFAULT 0,
                is_admin BOOLEAN DEFAULT FALSE
            );
            """)
            # اگر قبلاً جدول بوده ولی بعضی ستون‌ها نبودند
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_cents INTEGER DEFAULT 0;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;")
        else:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                wallet_cents INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0
            );
            """)
            # تلاش برای اضافه کردن ستون‌ها (اگر وجود داشته باشند خطا را نادیده می‌گیریم)
            try:
                cur.execute("ALTER TABLE users ADD COLUMN wallet_cents INTEGER DEFAULT 0;")
            except Exception:
                pass
            try:
                cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0;")
            except Exception:
                pass

        # products
        if USE_PG:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                image_file_id TEXT
            );
            """)
        else:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                image_file_id TEXT
            );
            """)


# ---------- کاربران ----------
def get_or_create_user(tg_id: int, is_admin: bool = False):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT tg_id, wallet_cents, { 'is_admin' if USE_PG else 'is_admin' } FROM users WHERE tg_id={_ph(1)}",
            (tg_id,),
        )
        row = cur.fetchone()
        if row:
            # row: (tg_id, wallet_cents, is_admin)
            return {"tg_id": int(row[0]), "wallet_cents": int(row[1]), "is_admin": bool(row[2])}

        # ایجاد
        if USE_PG:
            cur.execute(
                f"INSERT INTO users (tg_id, wallet_cents, is_admin) VALUES ({_ph(3)}) RETURNING tg_id, wallet_cents, is_admin",
                (tg_id, 0, is_admin),
            )
            r = cur.fetchone()
            return {"tg_id": int(r[0]), "wallet_cents": int(r[1]), "is_admin": bool(r[2])}
        else:
            cur.execute(
                f"INSERT INTO users (tg_id, wallet_cents, is_admin) VALUES ({_ph(3)})",
                (tg_id, 0, 1 if is_admin else 0),
            )
            return {"tg_id": tg_id, "wallet_cents": 0, "is_admin": is_admin}

def get_wallet(tg_id: int) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT wallet_cents FROM users WHERE tg_id={_ph(1)}",
            (tg_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

def update_wallet(tg_id: int, delta_cents: int):
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_PG:
            cur.execute(
                f"UPDATE users SET wallet_cents = wallet_cents + {_ph(1)} WHERE tg_id={_ph(1)}",
                (delta_cents, tg_id),
            )
        else:
            cur.execute(
                f"UPDATE users SET wallet_cents = wallet_cents + {_ph(1)} WHERE tg_id={_ph(1)}",
                (delta_cents, tg_id),
            )


# ---------- محصولات ----------
def add_product(title: str, price_cents: int, image_file_id: str | None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO products (title, price_cents, image_file_id) VALUES ({_ph(3)})",
            (title, price_cents, image_file_id),
        )

def list_products():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, title, price_cents, image_file_id FROM products ORDER BY id DESC;")
        rows = cur.fetchall() or []
        return [
            {"id": int(r[0]), "title": r[1], "price_cents": int(r[2]), "image_file_id": r[3]}
            for r in rows
        ]
