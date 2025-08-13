# src/db.py
from __future__ import annotations

import os
import json
import contextlib
from typing import Any, Dict, Iterable, Optional, Tuple, List

import psycopg2
import psycopg2.pool
import psycopg2.extras

# اگر در base.py این‌ها را داری، ایمپورت کن؛ در غیر اینصورت از env می‌خوانیم
try:
    from .base import log, DATABASE_URL as BASE_DB_URL  # type: ignore
except Exception:
    import logging
    log = logging.getLogger("crepebar.db")
    logging.basicConfig(level=logging.INFO)
    BASE_DB_URL = None

DATABASE_URL = (BASE_DB_URL or os.getenv("DATABASE_URL") or os.getenv("DB_URL"))
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env is missing.")

# Neon معمولاً ssl می‌خواهد
if "sslmode" not in DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    if "?" in DATABASE_URL:
        DATABASE_URL += "&sslmode=require"
    else:
        DATABASE_URL += "?sslmode=require"

# ---------- اتصال Pool ----------
POOL: psycopg2.pool.SimpleConnectionPool = psycopg2.pool.SimpleConnectionPool(
    minconn=1, maxconn=5, dsn=DATABASE_URL
)

@contextlib.contextmanager
def get_conn():
    conn = POOL.getconn()
    try:
        yield conn
    finally:
        POOL.putconn(conn)

def _exec(sql: str, params: Optional[Iterable[Any]] = None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
        conn.commit()

def _fetchone(sql: str, params: Optional[Iterable[Any]] = None) -> Optional[Tuple]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
        conn.commit()
    return row

def _fetchall(sql: str, params: Optional[Iterable[Any]] = None) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
        conn.commit()
    return list(rows)

# ---------- اسکیما (کامل و اصلاح‌شده) ----------
SCHEMA_SQL = """
-- users
CREATE TABLE IF NOT EXISTS users (
  user_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  telegram_id  BIGINT UNIQUE NOT NULL,
  name         TEXT,
  phone        TEXT,
  address      TEXT,
  balance      NUMERIC DEFAULT 0 NOT NULL,
  active       BOOLEAN DEFAULT TRUE,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone       TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS address     TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS balance     NUMERIC DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS active      BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at  TIMESTAMPTZ DEFAULT NOW();
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_telegram_id ON users(telegram_id);

-- settings
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO settings(key, value)
VALUES ('cashback_percent', '3')
ON CONFLICT (key) DO NOTHING;

-- products
CREATE TABLE IF NOT EXISTS products (
  product_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name           TEXT NOT NULL,
  price          NUMERIC NOT NULL,
  photo_file_id  TEXT,
  description    TEXT,
  is_active      BOOLEAN DEFAULT TRUE,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_products_name_active
  ON products (LOWER(name)) WHERE is_active = TRUE;

-- orders & order_items
CREATE TABLE IF NOT EXISTS orders (
  order_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'draft',
  total_amount    NUMERIC NOT NULL DEFAULT 0,
  cashback_amount NUMERIC NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS order_items (
  item_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id    BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
  product_id  BIGINT NOT NULL REFERENCES products(product_id),
  qty         INTEGER NOT NULL DEFAULT 1,
  unit_price  NUMERIC NOT NULL,
  line_total  NUMERIC GENERATED ALWAYS AS (qty * unit_price) STORED
);
CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items(order_id);

CREATE OR REPLACE FUNCTION fn_recalc_order_total(p_order_id BIGINT)
RETURNS VOID AS $$
BEGIN
  UPDATE orders o
  SET total_amount = COALESCE((
    SELECT SUM(line_total) FROM order_items WHERE order_id = p_order_id
  ), 0)
  WHERE o.order_id = p_order_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_recalc_order_total_wrap()
RETURNS TRIGGER AS $$
DECLARE
  v_order_id BIGINT;
BEGIN
  IF TG_OP IN ('INSERT','UPDATE') THEN
    v_order_id := NEW.order_id;
  ELSE
    v_order_id := OLD.order_id;
  END IF;

  PERFORM fn_recalc_order_total(v_order_id);

  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  ELSE
    RETURN NEW;
  END IF;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_recalc_after_change ON order_items;
CREATE TRIGGER trg_recalc_after_change
AFTER INSERT OR UPDATE OR DELETE ON order_items
FOR EACH ROW
EXECUTE FUNCTION fn_recalc_order_total_wrap();

-- wallet
CREATE TABLE IF NOT EXISTS wallet_transactions (
  tx_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,
  amount      NUMERIC NOT NULL,
  meta        JSONB DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_wallet_tx_user ON wallet_transactions(user_id);

CREATE OR REPLACE FUNCTION fn_apply_wallet_tx()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE users
  SET balance = COALESCE(balance,0) + NEW.amount
  WHERE user_id = NEW.user_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_wallet_tx ON wallet_transactions;
CREATE TRIGGER trg_apply_wallet_tx
AFTER INSERT ON wallet_transactions
FOR EACH ROW
EXECUTE FUNCTION fn_apply_wallet_tx();

-- cashback
CREATE OR REPLACE FUNCTION fn_apply_cashback()
RETURNS TRIGGER AS $$
DECLARE
  percent NUMERIC := 0;
  amount  NUMERIC := 0;
BEGIN
  IF NEW.status = 'paid' AND COALESCE(OLD.status,'') <> 'paid' THEN
    SELECT COALESCE(NULLIF(value, '')::NUMERIC, 0) INTO percent
    FROM settings WHERE key='cashback_percent';

    amount := ROUND(NEW.total_amount * percent / 100.0, 0);
    NEW.cashback_amount := COALESCE(NEW.cashback_amount,0) + amount;

    INSERT INTO wallet_transactions (user_id, kind, amount, meta)
    VALUES (NEW.user_id, 'cashback', amount,
            jsonb_build_object('order_id', NEW.order_id, 'percent', percent));
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_cashback ON orders;
CREATE TRIGGER trg_apply_cashback
AFTER UPDATE ON orders
FOR EACH ROW
EXECUTE FUNCTION fn_apply_cashback();

-- views
CREATE OR REPLACE VIEW v_user_balance AS
SELECT u.user_id, u.telegram_id, u.name, u.balance FROM users u;

CREATE OR REPLACE VIEW v_order_summary AS
SELECT o.order_id, o.user_id, o.status, o.total_amount, o.cashback_amount, o.created_at,
       COUNT(oi.item_id) AS items_count
FROM orders o
LEFT JOIN order_items oi ON oi.order_id = o.order_id
GROUP BY o.order_id;
"""

def init_db() -> None:
    log.info("init_db() running...")
    _exec(SCHEMA_SQL)
    log.info("init_db() done.")

# ---------- Helpers & Queries ----------

def upsert_user(telegram_id: int, name: Optional[str] = None,
                phone: Optional[str] = None, address: Optional[str] = None) -> Dict[str, Any]:
    sql = """
    INSERT INTO users(telegram_id, name, phone, address)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (telegram_id)
    DO UPDATE SET
      name = COALESCE(EXCLUDED.name, users.name),
      phone = COALESCE(EXCLUDED.phone, users.phone),
      address = COALESCE(EXCLUDED.address, users.address),
      active = TRUE
    RETURNING user_id, telegram_id, name, phone, address, balance, active, created_at;
    """
    row = _fetchone(sql, (telegram_id, name, phone, address))
    return dict(row) if row else {}

def get_user_by_telegram(telegram_id: int) -> Optional[Dict[str, Any]]:
    row = _fetchone(
        "SELECT * FROM users WHERE telegram_id=%s;",
        (telegram_id,)
    )
    return dict(row) if row else None

def set_user_profile(telegram_id: int, name: str, phone: str, address: str) -> None:
    _exec(
        "UPDATE users SET name=%s, phone=%s, address=%s WHERE telegram_id=%s;",
        (name, phone, address, telegram_id)
    )

# -------- products --------

def add_product(name: str, price: float,
                photo_file_id: Optional[str] = None,
                description: Optional[str] = None,
                is_active: bool = True) -> Dict[str, Any]:
    row = _fetchone(
        """
        INSERT INTO products(name, price, photo_file_id, description, is_active)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT ON CONSTRAINT ux_products_name_active
        DO NOTHING
        RETURNING *;
        """,
        (name, price, photo_file_id, description, is_active)
    )
    return dict(row) if row else {}

def list_products(active_only: bool = True) -> List[Dict[str, Any]]:
    if active_only:
        sql = "SELECT * FROM products WHERE is_active=TRUE ORDER BY product_id DESC;"
        return _fetchall(sql)
    else:
        return _fetchall("SELECT * FROM products ORDER BY product_id DESC;")

# -------- orders --------

def ensure_draft_order(user_id: int) -> int:
    row = _fetchone(
        "SELECT order_id FROM orders WHERE user_id=%s AND status='draft' ORDER BY order_id DESC LIMIT 1;",
        (user_id,)
    )
    if row:
        return int(row["order_id"])
    row = _fetchone(
        "INSERT INTO orders(user_id, status) VALUES (%s, 'draft') RETURNING order_id;",
        (user_id,)
    )
    return int(row["order_id"])  # type: ignore

def add_item_to_order(order_id: int, product_id: int, qty: int, unit_price: float) -> None:
    _exec(
        """
        INSERT INTO order_items(order_id, product_id, qty, unit_price)
        VALUES (%s, %s, %s, %s);
        """,
        (order_id, product_id, qty, unit_price)
    )

def set_order_status(order_id: int, status: str) -> None:
    _exec("UPDATE orders SET status=%s WHERE order_id=%s;", (status, order_id))

def get_order_summary(order_id: int) -> Optional[Dict[str, Any]]:
    row = _fetchone("SELECT * FROM v_order_summary WHERE order_id=%s;", (order_id,))
    return dict(row) if row else None

# -------- wallet --------

def add_wallet_tx(user_id: int, kind: str, amount: float, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    row = _fetchone(
        """
        INSERT INTO wallet_transactions(user_id, kind, amount, meta)
        VALUES (%s, %s, %s, %s)
        RETURNING *;
        """,
        (user_id, kind, amount, json.dumps(meta or {}))
    )
    return dict(row) if row else {}

def get_balance(user_id: int) -> float:
    row = _fetchone("SELECT balance FROM users WHERE user_id=%s;", (user_id,))
    return float(row["balance"]) if row else 0.0  # type: ignore

# -------- settings --------

def get_setting(key: str, default: Optional[str] = None) -> str:
    row = _fetchone("SELECT value FROM settings WHERE key=%s;", (key,))
    if row and row["value"] is not None:
        return str(row["value"])
    return default if default is not None else ""

def set_setting(key: str, value: str) -> None:
    _exec(
        """
        INSERT INTO settings(key,value) VALUES (%s,%s)
        ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value;
        """,
        (key, value)
    )
