# src/db.py
import os
import time
import threading
from typing import List, Dict, Optional, Tuple

DB_URL = os.getenv("DATABASE_URL", "").strip()

# دو درایور برای fallback
import sqlite3
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:  # روی بیلد هم اگر در دسترس نبود، مشکلی نشود
    psycopg2 = None
    RealDictCursor = None

# وضعیت اتصال
_DB_KIND = None  # "pg" | "sqlite" | None
_CONN = None
_LOCK = threading.Lock()


def _pg_connect():
    assert psycopg2 is not None, "psycopg2 not installed"
    # connect_timeout برای جلوگیری از Timeout
    conn = psycopg2.connect(DB_URL, connect_timeout=3, sslmode="require")
    conn.autocommit = True
    with conn.cursor() as cur:
        # محدودیت برای کوئری‌های طولانی
        try:
            cur.execute("SET statement_timeout TO 3000;")
        except Exception:
            pass
    return conn


def _sqlite_connect():
    # فایل در /tmp تا روی Render قابل نوشتن باشد
    path = "/tmp/app.db"
    conn = sqlite3.connect(path, check_same_thread=False)
    return conn


def _ensure_connection():
    """تنها زمانی که نیاز شد وصل می‌شویم (lazy)"""
    global _CONN, _DB_KIND
    with _LOCK:
        if _CONN:
            return

        # ابتدا تلاش برای Postgres (Neon)
        if DB_URL and psycopg2:
            try:
                _CONN = _pg_connect()
                _DB_KIND = "pg"
                print("DB: connected to Postgres")
                return
            except Exception as e:
                print("DB: Postgres connect failed ->", e)

        # fallback: SQLite
        _CONN = _sqlite_connect()
        _DB_KIND = "sqlite"
        print("DB: connected to SQLite at /tmp/app.db")


def _exec(sql: str, params: Tuple = ()):
    _ensure_connection()
    if _DB_KIND == "pg":
        with _CONN.cursor() as cur:
            cur.execute(sql, params)
            # اگر نیاز به نتیجه نباشد، چیزی برنمی‌گردانیم
    else:
        cur = _CONN.cursor()
        try:
            cur.execute(sql, params)
            _CONN.commit()
        finally:
            cur.close()


def _fetchone(sql: str, params: Tuple = ()) -> Optional[Tuple]:
    _ensure_connection()
    if _DB_KIND == "pg":
        with _CONN.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    else:
        cur = _CONN.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchone()
        finally:
            cur.close()


def _fetchall(sql: str, params: Tuple = ()) -> List[Tuple]:
    _ensure_connection()
    if _DB_KIND == "pg":
        with _CONN.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    else:
        cur = _CONN.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()


# ---------- Schema & public functions ----------

def init_db():
    """
    ساخت جداول در صورت نبودن.
    سریع است و اگر Neon کند باشد، قبلاً اتصال fallback شده.
    """
    _ensure_connection()

    if _DB_KIND == "pg":
        _exec("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            tg_id BIGINT UNIQUE,
            wallet_cents INTEGER DEFAULT 0,
            is_admin BOOLEAN DEFAULT FALSE
        );
        """)
        _exec("""
        CREATE TABLE IF NOT EXISTS products (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            photo_file_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)
    else:
        _exec("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            wallet_cents INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        );
        """)
        _exec("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            photo_file_id TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)

    print("DB: init_db done")


def get_or_create_user(tg_id: int) -> Tuple[int, int, bool]:
    """
    برمی‌گرداند: (id, wallet_cents, is_admin)
    """
    row = _fetchone("SELECT id, wallet_cents, is_admin FROM users WHERE tg_id=%s" if _DB_KIND == "pg"
                    else "SELECT id, wallet_cents, is_admin FROM users WHERE tg_id=?",
                    (tg_id,))
    if row:
        uid, wallet, is_admin = row
        # در SQLite is_admin عدد است
        if isinstance(is_admin, int):
            is_admin = bool(is_admin)
        return uid, wallet, is_admin

    # ایجاد کاربر
    _exec("INSERT INTO users (tg_id) VALUES (%s)" if _DB_KIND == "pg" else "INSERT INTO users (tg_id) VALUES (?)",
          (tg_id,))
    row = _fetchone("SELECT id, wallet_cents, is_admin FROM users WHERE tg_id=%s" if _DB_KIND == "pg"
                    else "SELECT id, wallet_cents, is_admin FROM users WHERE tg_id=?",
                    (tg_id,))
    uid, wallet, is_admin = row
    if isinstance(is_admin, int):
        is_admin = bool(is_admin)
    return uid, wallet, is_admin


def get_wallet(tg_id: int) -> int:
    row = _fetchone("SELECT wallet_cents FROM users WHERE tg_id=%s" if _DB_KIND == "pg"
                    else "SELECT wallet_cents FROM users WHERE tg_id=?",
                    (tg_id,))
    return int(row[0]) if row else 0


def list_products() -> List[Dict]:
    rows = _fetchall("SELECT id, name, price_cents, photo_file_id FROM products ORDER BY id DESC")
    return [
        {"id": r[0], "name": r[1], "price_cents": int(r[2]), "photo_file_id": r[3]}
        for r in rows
    ]


def add_product(name: str, price_cents: int, photo_file_id: Optional[str]) -> int:
    if _DB_KIND == "pg":
        _exec("INSERT INTO products (name, price_cents, photo_file_id) VALUES (%s,%s,%s)",
              (name, price_cents, photo_file_id))
        row = _fetchone("SELECT id FROM products ORDER BY id DESC LIMIT 1")
        return int(row[0])
    else:
        _exec("INSERT INTO products (name, price_cents, photo_file_id) VALUES (?,?,?)",
              (name, price_cents, photo_file_id))
        row = _fetchone("SELECT last_insert_rowid()")
        return int(row[0])
