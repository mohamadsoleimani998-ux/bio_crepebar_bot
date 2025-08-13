# src/db.py
import os
import logging
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql as _sql

log = logging.getLogger("crepebar")

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL".lower())
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set.")

# ---------- SCHEMA (همان SQL بالا) ----------
SCHEMA_SQL = r"""
-- تمام schema_full.sql اینجاست (بدون هیچ تغییری کپی کن)
-- برای خوانایی، می‌توانی همان فایل schema_full.sql را اینجا paste کنی.
-- من دقیقاً همان متن بالا را اینجا گذاشته‌ام ↓↓↓
-- [Paste the whole SQL from section #1 here verbatim]
"""

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _exec(sql_text: str, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text, params or ())

def _fetchone(sql_text: str, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql_text, params or ())
            return cur.fetchone()

def init_db():
    log.info("init_db() running...")
    _exec(SCHEMA_SQL)
    log.info("init_db() done.")

# ---------- Helpers used by handlers ----------

def upsert_user(telegram_id: int, name: str | None) -> dict:
    """
    اگر کاربر بود نام را به‌روز می‌کنیم؛ در هر حال user_id و balance را برمی‌گردانیم.
    """
    q = """
    INSERT INTO users(telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id)
      DO UPDATE SET name = EXCLUDED.name
    RETURNING user_id, balance;
    """
    return _fetchone(q, (telegram_id, name))

def product_add(name: str, price: float, photo_file_id: str | None = None, description: str | None = None):
    """
    محصول جدید فعال می‌کند. اگر نامِ فعال تکراری باشد، خطای یکتا برمی‌گردد.
    """
    q = """
    INSERT INTO products(name, price, photo_file_id, description, is_active)
    VALUES (%s, %s, %s, %s, TRUE)
    RETURNING product_id;
    """
    return _fetchone(q, (name, price, photo_file_id, description))

def products_list_active() -> list[dict]:
    q = """
    SELECT product_id, name, price, photo_file_id, description
    FROM products
    WHERE is_active = TRUE
    ORDER BY created_at DESC;
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(q)
            return cur.fetchall()

def wallet_topup(user_id: int, amount: int, ref: dict | None = None):
    """
    شارژ کیف پول (مثبت). تریگر موجودی را بالا می‌برد.
    """
    q = """
    INSERT INTO wallet_transactions(user_id, kind, amount, meta)
    VALUES (%s, 'topup', %s, %s::jsonb)
    RETURNING tx_id;
    """
    import json
    return _fetchone(q, (user_id, amount, json.dumps(ref or {})))
