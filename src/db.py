# src/db.py
import os
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

import psycopg2
import psycopg2.extras

# ---------- Logger ----------
log = logging.getLogger("crepebar")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

# ---------- Config ----------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env is missing")

# ---------- SQL Schema (idempotent) ----------
SCHEMA_SQL = """
-- =========================
-- users
-- =========================
CREATE TABLE IF NOT EXISTS users (
  user_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  telegram_id  BIGINT UNIQUE NOT NULL,
  name         TEXT,
  phone        TEXT,
  address      TEXT,
  balance      NUMERIC NOT NULL DEFAULT 0,
  active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_telegram_id ON users (telegram_id);

-- =========================
-- settings (برای کش‌بک و تنظیمات ساده)
-- =========================
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT INTO settings(key, value)
VALUES ('cashback_percent', '3')
ON CONFLICT (key) DO NOTHING;

-- =========================
-- products
-- =========================
CREATE TABLE IF NOT EXISTS products (
  product_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name           TEXT NOT NULL,
  price          NUMERIC NOT NULL,
  photo_file_id  TEXT,
  description    TEXT,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- اگر ایندکس یکتای محصولات فعال وجود نداشت، بساز
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

-- پاکسازی داده‌های تکراری فعال: از هر نامِ فعال فقط کوچک‌ترین product_id بماند
DELETE FROM products p
USING (
  SELECT LOWER(name) AS ln, MIN(product_id) AS keep_id
  FROM products
  WHERE is_active = TRUE
  GROUP BY LOWER(name)
) d
WHERE p.is_active = TRUE
  AND LOWER(p.name) = d.ln
  AND p.product_id <> d.keep_id;

-- =========================
-- orders / order_items
-- =========================
CREATE TABLE IF NOT EXISTS orders (
  order_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'draft', -- draft | submitted | paid | canceled | fulfilled
  total_amount    NUMERIC NOT NULL DEFAULT 0,
  cashback_amount NUMERIC NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
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

-- تابع/تریگر: محاسبه مجموع سفارش بعد از تغییر اقلام
CREATE OR REPLACE FUNCTION fn_recalc_order_total_trg()
RETURNS TRIGGER AS $$
DECLARE
  v_order_id BIGINT;
BEGIN
  IF TG_OP = 'DELETE' THEN
    v_order_id := OLD.order_id;
  ELSE
    v_order_id := NEW.order_id;
  END IF;

  UPDATE orders o
  SET total_amount = COALESCE((
    SELECT SUM(line_total) FROM order_items WHERE order_id = v_order_id
  ), 0)
  WHERE o.order_id = v_order_id;

  IF TG_OP <> 'DELETE' THEN
    RETURN NEW;
  ELSE
    RETURN OLD;
  END IF;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_recalc_after_change ON order_items;
CREATE TRIGGER trg_recalc_after_change
AFTER INSERT OR UPDATE OR DELETE ON order_items
FOR EACH ROW EXECUTE FUNCTION fn_recalc_order_total_trg();

-- =========================
-- wallet (تراکنش‌های کیف پول)
-- =========================
CREATE TABLE IF NOT EXISTS wallet_transactions (
  tx_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,  -- topup | order | refund | cashback | adjust
  amount      NUMERIC NOT NULL, -- + افزایش، - کاهش
  meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
FOR EACH ROW EXECUTE FUNCTION fn_apply_wallet_tx();

-- =========================
-- cashback (اعمال کش‌بک وقتی paid شد)
-- =========================
CREATE OR REPLACE FUNCTION fn_apply_cashback()
RETURNS TRIGGER AS $$
DECLARE
  percent NUMERIC := 0;
  amount  NUMERIC := 0;
BEGIN
  IF NEW.status = 'paid' AND COALESCE(OLD.status,'') <> 'paid' THEN
    SELECT COALESCE(NULLIF(value,'')::NUMERIC, 0)
      INTO percent
    FROM settings WHERE key = 'cashback_percent';

    amount := ROUND(NEW.total_amount * percent / 100.0, 0);
    NEW.cashback_amount := COALESCE(NEW.cashback_amount,0) + amount;

    INSERT INTO wallet_transactions(user_id, kind, amount, meta)
    VALUES (
      NEW.user_id,
      'cashback',
      amount,
      jsonb_build_object('order_id', NEW.order_id, 'percent', percent)
    );
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_cashback ON orders;
CREATE TRIGGER trg_apply_cashback
AFTER UPDATE ON orders
FOR EACH ROW EXECUTE FUNCTION fn_apply_cashback();

-- =========================
-- نماها
-- =========================
CREATE OR REPLACE VIEW v_user_balance AS
SELECT u.user_id, u.telegram_id, u.name, u.balance
FROM users u;

CREATE OR REPLACE VIEW v_order_summary AS
SELECT o.order_id, o.user_id, o.status, o.total_amount, o.cashback_amount, o.created_at,
       COUNT(oi.item_id) AS items_count
FROM orders o
LEFT JOIN order_items oi ON oi.order_id = o.order_id
GROUP BY o.order_id;
"""

# ---------- Low-level helpers ----------
def _get_conn():
    # DSN Neon معمولاً sslmode=require دارد؛ همان URL محیط را استفاده می‌کنیم
    return psycopg2.connect(DATABASE_URL)

def _exec(sql: str, params: Optional[Iterable[Any]] = None) -> None:
    if not sql.strip():
        return
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())

def _fetchone(sql: str, params: Optional[Iterable[Any]] = None) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
            return dict(row) if row else None

def _fetchall(sql: str, params: Optional[Iterable[Any]] = None) -> List[Dict[str, Any]]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return [dict(r) for r in cur.fetchall()]

# ---------- Public API used by handlers ----------

def init_db() -> None:
    log.info("init_db() running...")
    _exec(SCHEMA_SQL)

# --- users ---
def upsert_user(telegram_id: int, name: Optional[str]) -> Dict[str, Any]:
    sql = """
    INSERT INTO users (telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id) DO UPDATE
      SET name = COALESCE(EXCLUDED.name, users.name)
    RETURNING user_id, telegram_id, name, phone, address, balance, active, created_at;
    """
    return _fetchone(sql, (telegram_id, name))

def update_user_profile(telegram_id: int, name: Optional[str], phone: Optional[str], address: Optional[str]) -> Dict[str, Any]:
    sql = """
    UPDATE users
    SET
      name = COALESCE(%s, name),
      phone = COALESCE(%s, phone),
      address = COALESCE(%s, address)
    WHERE telegram_id = %s
    RETURNING user_id, telegram_id, name, phone, address, balance, active, created_at;
    """
    return _fetchone(sql, (name, phone, address, telegram_id))

def get_user_by_tg(telegram_id: int) -> Optional[Dict[str, Any]]:
    return _fetchone("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))

# --- settings ---
def get_setting(key: str, default: Optional[str] = None) -> str:
    row = _fetchone("SELECT value FROM settings WHERE key=%s", (key,))
    return row["value"] if row else (default or "")

def set_setting(key: str, value: str) -> None:
    _exec("""
    INSERT INTO settings(key, value) VALUES (%s,%s)
    ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
    """, (key, value))

# --- products ---
def list_products(active_only: bool = True) -> List[Dict[str, Any]]:
    if active_only:
        return _fetchall("SELECT * FROM products WHERE is_active = TRUE ORDER BY LOWER(name)")
    return _fetchall("SELECT * FROM products ORDER BY is_active DESC, LOWER(name)")

def add_or_replace_product(name: str, price: float, photo_file_id: Optional[str], description: Optional[str]) -> Dict[str, Any]:
    # برای رعایت ایندکس یکتا، نسخه‌های فعال هم‌نام را غیرفعال می‌کنیم
    _exec("UPDATE products SET is_active = FALSE WHERE is_active = TRUE AND LOWER(name)=LOWER(%s)", (name,))
    sql = """
    INSERT INTO products(name, price, photo_file_id, description, is_active)
    VALUES (%s, %s, %s, %s, TRUE)
    RETURNING *;
    """
    return _fetchone(sql, (name, price, photo_file_id, description))

def deactivate_product(product_id: int) -> None:
    _exec("UPDATE products SET is_active = FALSE WHERE product_id = %s", (product_id,))

# --- orders ---
def create_order_draft(user_id: int) -> Dict[str, Any]:
    return _fetchone("INSERT INTO orders(user_id) VALUES (%s) RETURNING *", (user_id,))

def add_order_item(order_id: int, product_id: int, qty: int) -> Dict[str, Any]:
    # قیمت واحد از جدول محصولات
    row = _fetchone("SELECT price FROM products WHERE product_id=%s", (product_id,))
    if not row:
        raise ValueError("محصول یافت نشد")
    unit_price = row["price"]
    return _fetchone("""
      INSERT INTO order_items(order_id, product_id, qty, unit_price)
      VALUES (%s, %s, %s, %s)
      RETURNING *;
    """, (order_id, product_id, qty, unit_price))

def set_order_status(order_id: int, status: str) -> Dict[str, Any]:
    return _fetchone("UPDATE orders SET status=%s WHERE order_id=%s RETURNING *", (status, order_id))

def get_order(order_id: int) -> Optional[Dict[str, Any]]:
    return _fetchone("SELECT * FROM orders WHERE order_id=%s", (order_id,))

# --- wallet ---
def wallet_get_balance(user_id: int) -> float:
    row = _fetchone("SELECT balance FROM users WHERE user_id=%s", (user_id,))
    return float(row["balance"] if row else 0)

def wallet_add_topup(user_id: int, amount: float, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta_json = psycopg2.extras.Json(meta or {})
    return _fetchone("""
      INSERT INTO wallet_transactions(user_id, kind, amount, meta)
      VALUES (%s, 'topup', %s, %s)
      RETURNING *;
    """, (user_id, amount, meta_json))

def wallet_charge_for_order(user_id: int, amount: float, order_id: int) -> Dict[str, Any]:
    meta = {"order_id": order_id}
    meta_json = psycopg2.extras.Json(meta)
    return _fetchone("""
      INSERT INTO wallet_transactions(user_id, kind, amount, meta)
      VALUES (%s, 'order', %s, %s)
      RETURNING *;
    """, (user_id, -abs(amount), meta_json))
