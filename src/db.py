import os
import psycopg2
from psycopg2.extras import RealDictCursor

DB_URL = os.getenv("DATABASE_URL")

def _get_conn():
    if not DB_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

def init_db():
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_id BIGINT PRIMARY KEY,
            first_name TEXT,
            last_name  TEXT,
            username   TEXT,
            wallet_cents INTEGER NOT NULL DEFAULT 0,
            is_admin  BOOLEAN NOT NULL DEFAULT FALSE
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            price_cents INTEGER NOT NULL DEFAULT 0,
            image_url TEXT,
            caption TEXT
        );
        """)
        conn.commit()

def get_or_create_user(tg_id: int, first_name=None, last_name=None, username=None):
    if not tg_id:
        return None
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE tg_id=%s", (tg_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        cur.execute("""
            INSERT INTO users (tg_id, first_name, last_name, username)
            VALUES (%s, %s, %s, %s)
            RETURNING *;
        """, (tg_id, first_name, last_name, username))
        conn.commit()
        return dict(cur.fetchone())

def get_wallet(tg_id: int) -> int:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s", (tg_id,))
        row = cur.fetchone()
        return int(row["wallet_cents"]) if row and row["wallet_cents"] is not None else 0

def list_products():
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, title, price_cents, image_url, caption FROM products ORDER BY id DESC LIMIT 20;")
        rows = cur.fetchall() or []
        return [dict(r) for r in rows]

# امضاها را نگه می‌داریم تا ایمپورت در handlers خطا ندهد
def add_product(*args, **kwargs):
    raise NotImplementedError

def set_admins(*args, **kwargs):
    raise NotImplementedError
