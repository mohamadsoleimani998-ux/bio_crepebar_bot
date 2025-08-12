from __future__ import annotations
import os
import psycopg2
import psycopg2.extras
from typing import Any, Optional, Tuple, List
from .base import log, DATABASE_URL, CASHBACK_PERCENT

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env is missing")
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def _exec(sql: str, params: Tuple[Any,...] | None = None, fetch: str = ""):
    with _conn() as cn:
        with cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
            return None

# ---------- DDL ----------
def init_db():
    log.info("init_db() running...")
    # users
    _exec("""
    CREATE TABLE IF NOT EXISTS users(
        user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        name TEXT,
        phone TEXT,
        address TEXT,
        active BOOLEAN DEFAULT TRUE,
        wallet_balance BIGINT DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    """)
    # products
    _exec("""
    CREATE TABLE IF NOT EXISTS products(
        product_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,
        price BIGINT NOT NULL,
        photo_file_id TEXT,
        description TEXT,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    """)
    # orders (ساده)
    _exec("""
    CREATE TABLE IF NOT EXISTS orders(
        order_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id BIGINT REFERENCES users(user_id),
        total_amount BIGINT NOT NULL,
        cashback BIGINT DEFAULT 0,
        status TEXT DEFAULT 'new',
        created_at TIMESTAMPTZ DEFAULT now()
    );
    """)
    # wallet transactions
    _exec("""
    CREATE TABLE IF NOT EXISTS wallet_tx(
        tx_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id BIGINT REFERENCES users(user_id),
        amount BIGINT NOT NULL,             -- +credit, -debit
        kind TEXT NOT NULL,                 -- 'topup' | 'order' | 'cashback' | 'adjust'
        meta JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    """)
    # ایندکس‌ها/ستون‌های جدید در صورت نبود
    _exec("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance BIGINT DEFAULT 0;")
    _exec("ALTER TABLE products ADD COLUMN IF NOT EXISTS description TEXT;")
    _exec("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;")
    log.info("init_db() done.")

# ---------- Users ----------
def upsert_user(telegram_id: int, name: Optional[str]) -> dict:
    row = _exec("""
    INSERT INTO users(telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id) DO UPDATE
      SET name = COALESCE(EXCLUDED.name, users.name)
    RETURNING *;
    """, (telegram_id, name), fetch="one")
    return row

def update_user_profile(telegram_id: int, name: str | None, phone: str | None, address: str | None):
    _exec("""
    UPDATE users SET
      name = COALESCE(%s, name),
      phone = COALESCE(%s, phone),
      address = COALESCE(%s, address)
    WHERE telegram_id = %s;
    """, (name, phone, address, telegram_id))

def get_user_by_tid(telegram_id: int) -> Optional[dict]:
    return _exec("SELECT * FROM users WHERE telegram_id=%s;", (telegram_id,), fetch="one")

# ---------- Products ----------
def add_product(name: str, price: int, photo_file_id: str | None, description: str | None) -> dict:
    return _exec("""
    INSERT INTO products(name, price, photo_file_id, description)
    VALUES (%s, %s, %s, %s)
    RETURNING *;
    """, (name, price, photo_file_id, description), fetch="one")

def list_products(active_only: bool = True) -> List[dict]:
    if active_only:
        return _exec("SELECT * FROM products WHERE is_active IS TRUE ORDER BY product_id DESC;", fetch="all") or []
    return _exec("SELECT * FROM products ORDER BY product_id DESC;", fetch="all") or []

# ---------- Wallet ----------
def wallet_balance(telegram_id: int) -> int:
    row = _exec("SELECT wallet_balance FROM users WHERE telegram_id=%s;", (telegram_id,), fetch="one")
    return int(row["wallet_balance"]) if row else 0

def wallet_add(telegram_id: int, amount: int, kind: str, meta: dict | None = None):
    # افزایش/کاهش موجودی و ثبت تراکنش
    u = get_user_by_tid(telegram_id)
    if not u:
        raise RuntimeError("user not found for wallet")
    _exec("UPDATE users SET wallet_balance = wallet_balance + %s WHERE telegram_id=%s;", (amount, telegram_id))
    _exec("INSERT INTO wallet_tx(user_id, amount, kind, meta) VALUES (%s,%s,%s,%s::jsonb);",
          (u["user_id"], amount, kind, psycopg2.extras.Json(meta or {})))

def apply_cashback(order_id: int, user_id: int, amount: int):
    cb = amount * CASHBACK_PERCENT // 100
    _exec("UPDATE orders SET cashback=%s WHERE order_id=%s;", (cb, order_id))
    _exec("UPDATE users SET wallet_balance = wallet_balance + %s WHERE user_id=%s;", (cb, user_id))
    _exec("INSERT INTO wallet_tx(user_id, amount, kind, meta) VALUES (%s,%s,'cashback', json_build_object('order_id',%s));",
          (user_id, cb, order_id))
    return cb
