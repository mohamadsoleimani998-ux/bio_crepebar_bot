from __future__ import annotations
import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from .base import DATABASE_URL, log

# ---------- Connection helpers
def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env missing.")
    return psycopg2.connect(DATABASE_URL, sslmode="require")

@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ---------- Schema (همانی که قبلاً اجرا کردی؛ اینجا برای اطمینان)
SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO settings(key, value) VALUES ('cashback_percent','3')
ON CONFLICT (key) DO NOTHING;

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

DROP TRIGGER IF EXISTS trg_recalc_after_change ON order_items;
CREATE TRIGGER trg_recalc_after_change
AFTER INSERT OR UPDATE OR DELETE ON order_items
FOR EACH ROW EXECUTE FUNCTION
  fn_recalc_order_total(
    CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN NEW.order_id ELSE OLD.order_id END
  );

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
  UPDATE users SET balance = COALESCE(balance,0) + NEW.amount
  WHERE user_id = NEW.user_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_wallet_tx ON wallet_transactions;
CREATE TRIGGER trg_apply_wallet_tx
AFTER INSERT ON wallet_transactions
FOR EACH ROW EXECUTE FUNCTION fn_apply_wallet_tx();

CREATE OR REPLACE FUNCTION fn_apply_cashback()
RETURNS TRIGGER AS $$
DECLARE
  percent NUMERIC := 0;
  amount  NUMERIC := 0;
BEGIN
  IF NEW.status = 'paid' AND COALESCE(OLD.status,'') <> 'paid' THEN
    SELECT COALESCE(NULLIF(value,'')::NUMERIC,0) INTO percent
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
FOR EACH ROW EXECUTE FUNCTION fn_apply_cashback();
"""

def init_db():
    log.info("init_db() running...")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
    log.info("Schema ensured.")

# ---------- CRUD helpers
def upsert_user(telegram_id: int, name: str | None):
    sql = """
    INSERT INTO users(telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id) DO UPDATE
      SET name = COALESCE(EXCLUDED.name, users.name)
    RETURNING user_id, telegram_id, name, phone, address, balance, active;
    """
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (telegram_id, name))
            return dict(cur.fetchone())

def update_profile(user_id: int, name=None, phone=None, address=None):
    sql = """
    UPDATE users SET
      name = COALESCE(%s, name),
      phone = COALESCE(%s, phone),
      address = COALESCE(%s, address)
    WHERE user_id = %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (name, phone, address, user_id))

def get_user_by_tg(tg_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE telegram_id=%s", (tg_id,))
            return dict(cur.fetchone()) if cur.rowcount else None

def get_cashback_percent() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key='cashback_percent'")
            row = cur.fetchone()
            return int(row[0]) if row else 0

def set_cashback_percent(p: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO settings(key,value) VALUES ('cashback_percent', %s)
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
            """, (str(p),))

def add_product(name: str, price: float, photo_id: str | None, desc: str | None):
    sql = """INSERT INTO products(name, price, photo_file_id, description)
             VALUES (%s,%s,%s,%s)
             RETURNING product_id"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (name, price, photo_id, desc))
            return cur.fetchone()[0]

def list_products(limit: int = 20):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT product_id, name, price, photo_file_id, description
                           FROM products WHERE is_active=TRUE
                           ORDER BY product_id DESC LIMIT %s""", (limit,))
            return [dict(r) for r in cur.fetchall()]

def find_product_by_name(name: str):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT * FROM products
                           WHERE is_active=TRUE AND LOWER(name)=LOWER(%s)
                           LIMIT 1""", (name,))
            return dict(cur.fetchone()) if cur.rowcount else None

def create_order(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO orders(user_id) VALUES (%s) RETURNING order_id", (user_id,))
            return cur.fetchone()[0]

def add_item(order_id: int, product_id: int, qty: int, unit_price: float):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO order_items(order_id,product_id,qty,unit_price)
                           VALUES (%s,%s,%s,%s)""", (order_id, product_id, qty, unit_price))

def submit_order(order_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE orders SET status='submitted' WHERE order_id=%s", (order_id,))

def mark_paid(order_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE orders SET status='paid' WHERE order_id=%s RETURNING user_id,total_amount,cashback_amount", (order_id,))
            return cur.fetchone()

def topup(user_id: int, amount: float, meta: dict | None = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO wallet_transactions(user_id,kind,amount,meta)
                           VALUES (%s,'topup',%s,%s)""",
                        (user_id, amount, psycopg2.extras.Json(meta or {})))

def get_balance(user_id: int) -> float:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            return float(row[0]) if row else 0.0
