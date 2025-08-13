# -*- coding: utf-8 -*-
import os
import logging
from contextlib import contextmanager
import json
import psycopg2
import psycopg2.extras

log = logging.getLogger("crepebar")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL".lower())
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL is missing.")

psycopg2.extras.register_default_json(loads=lambda x: json.loads(x) if x else None)

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
    if not (sql_text or "").strip():
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text, params or ())
            try:
                return cur.fetchall()
            except psycopg2.ProgrammingError:
                return None

# -----------------------------
# اسکیما: تمام SQL داخل این رشته
# -----------------------------
SCHEMA_SQL = r"""
-- =========================
-- پایه: users
-- =========================
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

-- =========================
-- تنظیمات (برای درصد کش‌بک و ...)
-- =========================
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT INTO settings(key, value)
VALUES ('cashback_percent', '3')
ON CONFLICT (key) DO NOTHING;

-- =========================
-- منو/محصولات
-- =========================
CREATE TABLE IF NOT EXISTS products (
  product_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name           TEXT NOT NULL,
  price          NUMERIC NOT NULL,
  photo_file_id  TEXT,
  description    TEXT,
  is_active      BOOLEAN DEFAULT TRUE,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- حذف محصولاتِ فعال که «نام تکراری» دارند (یکی بماند)
WITH d AS (
  SELECT LOWER(name) AS ln, MIN(product_id) AS keep_id
  FROM products
  WHERE is_active = TRUE
  GROUP BY LOWER(name)
  HAVING COUNT(*) > 1
)
DELETE FROM products p
USING d
WHERE p.is_active = TRUE
  AND LOWER(p.name) = d.ln
  AND p.product_id <> d.keep_id;

-- پس از پاکسازی، ایندکس یکتای نامِ فعال
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = ANY(current_schemas(true))
      AND indexname = 'ux_products_name_active'
  ) THEN
    EXECUTE 'CREATE UNIQUE INDEX ux_products_name_active
             ON products (LOWER(name)) WHERE is_active = TRUE';
  END IF;
END $$;

-- =========================
-- سفارش‌ها و اقلام سفارش
-- =========================
CREATE TABLE IF NOT EXISTS orders (
  order_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'draft', -- draft | submitted | paid | canceled | fulfilled
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

-- تابع محاسبه مجموع سفارش
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

-- تریگرهای جدا برای INSERT/UPDATE و DELETE
CREATE OR REPLACE FUNCTION trg_recalc_after_ins_upd()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM fn_recalc_order_total(NEW.order_id);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION trg_recalc_after_del()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM fn_recalc_order_total(OLD.order_id);
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS recalc_after_ins_upd ON order_items;
CREATE TRIGGER recalc_after_ins_upd
AFTER INSERT OR UPDATE ON order_items
FOR EACH ROW EXECUTE FUNCTION trg_recalc_after_ins_upd();

DROP TRIGGER IF EXISTS recalc_after_del ON order_items;
CREATE TRIGGER recalc_after_del
AFTER DELETE ON order_items
FOR EACH ROW EXECUTE FUNCTION trg_recalc_after_del();

-- =========================
-- تراکنش‌های کیف پول
-- =========================
CREATE TABLE IF NOT EXISTS wallet_transactions (
  tx_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,  -- topup | order | refund | cashback | adjust
  amount      NUMERIC NOT NULL, -- + افزایش موجودی، - کسر
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

DROP TRIGGER IF EXISTS apply_wallet_tx ON wallet_transactions;
CREATE TRIGGER apply_wallet_tx
AFTER INSERT ON wallet_transactions
FOR EACH ROW EXECUTE FUNCTION fn_apply_wallet_tx();

-- =========================
-- کش‌بک (هنگام تغییر وضعیت به paid)
-- =========================
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

DROP TRIGGER IF EXISTS apply_cashback ON orders;
CREATE TRIGGER apply_cashback
AFTER UPDATE ON orders
FOR EACH ROW EXECUTE FUNCTION fn_apply_cashback();

-- =========================
-- نماهای کمکی
-- =========================
CREATE OR REPLACE VIEW v_user_balance AS
SELECT u.user_id, u.telegram_id, u.name, u.balance FROM users u;

CREATE OR REPLACE VIEW v_order_summary AS
SELECT o.order_id, o.user_id, o.status, o.total_amount, o.cashback_amount, o.created_at,
       COUNT(oi.item_id) AS items_count
FROM orders o
LEFT JOIN order_items oi ON oi.order_id = o.order_id
GROUP BY o.order_id;
"""

def init_db():
    log.info("init_db() running...")
    _exec(SCHEMA_SQL)
    log.info("init_db() done.")

# -----------------------------
# توابع دسترسی به داده
# -----------------------------
def upsert_user(telegram_id: int, name: str = None):
    sql = """
    INSERT INTO users(telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id)
    DO UPDATE SET name = COALESCE(EXCLUDED.name, users.name)
    RETURNING user_id, telegram_id, name, phone, address, balance, active, created_at;
    """
    rows = _exec(sql, (telegram_id, name))
    return rows[0] if rows else None

def get_user_by_tg(telegram_id: int):
    rows = _exec("SELECT * FROM users WHERE telegram_id=%s;", (telegram_id,))
    return rows[0] if rows else None

def update_user_profile(user_id: int, name=None, phone=None, address=None):
    sql = """
    UPDATE users SET
      name = COALESCE(%s, name),
      phone = COALESCE(%s, phone),
      address = COALESCE(%s, address)
    WHERE user_id=%s
    RETURNING user_id, telegram_id, name, phone, address, balance, active, created_at;
    """
    rows = _exec(sql, (name, phone, address, user_id))
    return rows[0] if rows else None

def list_products(limit=50):
    sql = """
    SELECT product_id, name, price, photo_file_id, description
    FROM products
    WHERE is_active = TRUE
    ORDER BY created_at DESC
    LIMIT %s;
    """
    return _exec(sql, (limit,)) or []

def add_product(name: str, price: float, photo_file_id: str = None, description: str = None):
    sql = """
    INSERT INTO products(name, price, photo_file_id, description, is_active)
    VALUES (%s, %s, %s, %s, TRUE)
    ON CONFLICT ON CONSTRAINT ux_products_name_active DO UPDATE
    SET price = EXCLUDED.price,
        photo_file_id = COALESCE(EXCLUDED.photo_file_id, products.photo_file_id),
        description = COALESCE(EXCLUDED.description, products.description)
    RETURNING product_id, name, price, photo_file_id, description;
    """
    # اگر ایندکس هنوز ایجاد نشده باشد، عبارت بالا خطا می‌دهد.
    # در این صورت نسخهٔ ساده بدون on conflict:
    try:
        rows = _exec(sql, (name, price, photo_file_id, description))
        return rows[0] if rows else None
    except Exception:
        sql2 = """
        INSERT INTO products(name, price, photo_file_id, description, is_active)
        VALUES (%s, %s, %s, %s, TRUE)
        RETURNING product_id, name, price, photo_file_id, description;
        """
        rows = _exec(sql2, (name, price, photo_file_id, description))
        return rows[0] if rows else None

def create_order(user_id: int):
    rows = _exec("INSERT INTO orders(user_id) VALUES (%s) RETURNING order_id;", (user_id,))
    return rows[0][0]

def add_order_item(order_id: int, product_id: int, qty: int, unit_price: float):
    _exec("""
        INSERT INTO order_items(order_id, product_id, qty, unit_price)
        VALUES (%s, %s, %s, %s);
    """, (order_id, product_id, qty, unit_price))
    return True

def get_open_order(user_id: int):
    rows = _exec("""
      SELECT order_id FROM orders
      WHERE user_id=%s AND status='draft'
      ORDER BY created_at DESC LIMIT 1;
    """, (user_id,))
    return rows[0][0] if rows else None

def submit_order(order_id: int):
    _exec("UPDATE orders SET status='submitted' WHERE order_id=%s;", (order_id,))

def set_order_status(order_id: int, status: str):
    _exec("UPDATE orders SET status=%s WHERE order_id=%s;", (status, order_id))

def record_wallet_tx(user_id: int, amount: float, kind: str, meta: dict = None):
    _exec("""
      INSERT INTO wallet_transactions(user_id, kind, amount, meta)
      VALUES (%s, %s, %s, %s::jsonb);
    """, (user_id, kind, amount, json.dumps(meta or {})))

def get_wallet(user_id: int):
    rows = _exec("SELECT balance FROM users WHERE user_id=%s;", (user_id,))
    bal = rows[0][0] if rows else 0
    txs = _exec("""
      SELECT kind, amount, meta, created_at
      FROM wallet_transactions
      WHERE user_id=%s
      ORDER BY created_at DESC
      LIMIT 20;
    """, (user_id,)) or []
    return bal, txs

def get_cashback_percent():
    rows = _exec("SELECT value FROM settings WHERE key='cashback_percent';")
    return int(rows[0][0]) if rows else 0
