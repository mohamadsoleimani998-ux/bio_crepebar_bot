# src/db.py
from __future__ import annotations
import os
import json
import logging
from contextlib import contextmanager
import psycopg2
import psycopg2.extras

log = logging.getLogger("crepebar")

# ----- ENV -----
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE") or os.getenv("PG_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env is missing.")

# Neon/Render معمولاً SSL می‌خواهد
if "sslmode=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=require"

# درصد کش‌بک پیش‌فرض اگر settings خالی باشد
DEFAULT_CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "3"))

# ----- CONNECTION -----
@contextmanager
def _conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def _exec(sql_text: str, params: tuple | None = None):
    if not sql_text.strip():
        return
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(sql_text, params or ())

def _fetchone(sql_text: str, params: tuple | None = None):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql_text, params or ())
            r = cur.fetchone()
    return dict(r) if r else None

def _fetchall(sql_text: str, params: tuple | None = None):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql_text, params or ())
            rows = cur.fetchall()
    return [dict(r) for r in rows]

# ----- SCHEMA -----
SCHEMA_SQL = r"""
-- USERS
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
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_telegram_id ON users(telegram_id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone       TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS address     TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS balance     NUMERIC DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS active      BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at  TIMESTAMPTZ DEFAULT NOW();

-- SETTINGS (cashback)
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO settings(key, value)
VALUES ('cashback_percent', '""" + str(DEFAULT_CASHBACK_PERCENT) + """')
ON CONFLICT (key) DO NOTHING;

-- PRODUCTS
CREATE TABLE IF NOT EXISTS products (
  product_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name           TEXT NOT NULL,
  price          NUMERIC NOT NULL,
  photo_file_id  TEXT,
  description    TEXT,
  is_active      BOOLEAN DEFAULT TRUE,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- حذف محصولات تکراری فعال با نام یکسان (یکی نگه‌داشته می‌شود)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='products') THEN
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
  END IF;
END $$;

-- ایندکس یکتای نامِ فعال (بعد از پاکسازی)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = ANY(current_schemas(true))
      AND indexname = 'ux_products_name_active'
  ) THEN
    EXECUTE 'CREATE UNIQUE INDEX ux_products_name_active
             ON products (LOWER(name)) WHERE is_active = TRUE';
  END IF;
END $$;

-- ORDERS
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

-- محاسبه مجموع سفارش
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

-- تابع تریگر برای تشخیص INSERT/UPDATE/DELETE
CREATE OR REPLACE FUNCTION fn_recalc_order_total_trg()
RETURNS TRIGGER AS $$
DECLARE
  v_order BIGINT;
BEGIN
  IF TG_OP IN ('INSERT','UPDATE') THEN
    v_order := NEW.order_id;
  ELSE
    v_order := OLD.order_id;
  END IF;
  PERFORM fn_recalc_order_total(v_order);
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
FOR EACH ROW EXECUTE FUNCTION fn_recalc_order_total_trg();

-- WALLET
CREATE TABLE IF NOT EXISTS wallet_transactions (
  tx_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,  -- topup | order | refund | cashback | adjust
  amount      NUMERIC NOT NULL, -- + افزایش / - کاهش
  meta        JSONB DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_wallet_tx_user ON wallet_transactions(user_id);

-- به‌روزرسانی اتومات موجودی
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

-- CASHBACK
CREATE OR REPLACE FUNCTION fn_apply_cashback()
RETURNS TRIGGER AS $$
DECLARE
  percent NUMERIC := 0;
  amount  NUMERIC := 0;
BEGIN
  IF NEW.status = 'paid' AND COALESCE(OLD.status,'') <> 'paid' THEN
    SELECT COALESCE(NULLIF(value,'')::NUMERIC, 0) INTO percent
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

-- VIEWS (اختیاری)
CREATE OR REPLACE VIEW v_user_balance AS
SELECT user_id, telegram_id, name, balance FROM users;

CREATE OR REPLACE VIEW v_order_summary AS
SELECT o.order_id, o.user_id, o.status, o.total_amount, o.cashback_amount, o.created_at,
       COUNT(oi.item_id) AS items_count
FROM orders o
LEFT JOIN order_items oi ON oi.order_id = o.order_id
GROUP BY o.order_id;
"""

# ----- INIT -----
def init_db():
    log.info("init_db() running...")
    _exec(SCHEMA_SQL)

# ----- SETTINGS -----
def get_cashback_percent() -> int:
    row = _fetchone("SELECT value FROM settings WHERE key='cashback_percent'")
    if not row:
        return DEFAULT_CASHBACK_PERCENT
    try:
        return int(float(row["value"]))
    except Exception:
        return DEFAULT_CASHBACK_PERCENT

# ----- USERS / WALLET -----
def upsert_user(tg_id: int, name: str | None = None) -> dict:
    sql = """
    INSERT INTO users(telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id)
    DO UPDATE SET name = COALESCE(EXCLUDED.name, users.name)
    RETURNING user_id, telegram_id, name, balance, phone, address, active;
    """
    return _fetchone(sql, (tg_id, name))

def get_user_by_tg(tg_id: int) -> dict | None:
    return _fetchone("SELECT * FROM users WHERE telegram_id=%s", (tg_id,))

def update_profile(user_id: int, name: str | None, phone: str | None, address: str | None):
    _exec("""
        UPDATE users
        SET name = COALESCE(%s, name),
            phone = COALESCE(%s, phone),
            address = COALESCE(%s, address)
        WHERE user_id=%s
    """, (name, phone, address, user_id))

def wallet_add(user_id: int, amount: int | float, meta: dict | None = None, kind: str = "topup"):
    _exec("""
        INSERT INTO wallet_transactions(user_id, kind, amount, meta)
        VALUES (%s, %s, %s, %s::jsonb)
    """, (user_id, kind, amount, json.dumps(meta or {})))

def wallet_balance(user_id: int) -> int:
    row = _fetchone("SELECT balance FROM users WHERE user_id=%s", (user_id,))
    return int(row["balance"]) if row else 0

# ----- PRODUCTS -----
def create_product(name: str, price: int | float, photo_file_id: str | None = None, description: str | None = None):
    _exec("""
        INSERT INTO products(name, price, photo_file_id, description, is_active)
        VALUES (%s, %s, %s, %s, TRUE)
        ON CONFLICT (LOWER(name)) WHERE is_active = TRUE DO NOTHING
    """, (name, price, photo_file_id, description))

def list_products(limit: int = 20) -> list[dict]:
    return _fetchall("""
        SELECT product_id, name, price, photo_file_id, description
        FROM products
        WHERE is_active = TRUE
        ORDER BY product_id DESC
        LIMIT %s
    """, (limit,))

def get_product_by_name(name: str) -> dict | None:
    return _fetchone("""
        SELECT * FROM products
        WHERE is_active = TRUE AND LOWER(name)=LOWER(%s)
        LIMIT 1
    """, (name,))

# ----- ORDERS -----
def get_or_create_draft_order(user_id: int) -> dict:
    row = _fetchone("""
        SELECT * FROM orders
        WHERE user_id=%s AND status='draft'
        ORDER BY order_id DESC LIMIT 1
    """, (user_id,))
    if row:
        return row
    _exec("INSERT INTO orders(user_id, status) VALUES (%s, 'draft')", (user_id,))
    return _fetchone("""
        SELECT * FROM orders
        WHERE user_id=%s AND status='draft'
        ORDER BY order_id DESC LIMIT 1
    """, (user_id,))

def add_order_item(order_id: int, product_id: int, qty: int, unit_price: int | float):
    _exec("""
        INSERT INTO order_items(order_id, product_id, qty, unit_price)
        VALUES (%s, %s, %s, %s)
    """, (order_id, product_id, qty, unit_price))

def set_order_status(order_id: int, status: str):
    _exec("UPDATE orders SET status=%s WHERE order_id=%s", (status, order_id))

def pay_order_with_wallet(order_id: int, user_id: int) -> tuple[bool, str]:
    """
    سادگی: کل مبلغ از کیف پول کسر می‌شود و سفارش به paid می‌رود.
    """
    order = _fetchone("SELECT total_amount FROM orders WHERE order_id=%s AND user_id=%s", (order_id, user_id))
    if not order:
        return False, "سفارش پیدا نشد."
    total = int(order["total_amount"])
    bal = wallet_balance(user_id)
    if bal < total:
        return False, "موجودی کافی نیست."
    # کسر مبلغ
    wallet_add(user_id, -total, {"order_id": order_id}, kind="order")
    # تغییر وضعیت -> تریگر کش‌بک فعال می‌شود
    set_order_status(order_id, "paid")
    return True, "پرداخت شد ✅"

# ابزار کوچک برای پارس متن «نام × تعداد»
def parse_item_text(text: str) -> tuple[str, int]:
    t = text.strip()
    if "×" in t:
        name, qty = t.split("×", 1)
    elif "x" in t.lower():
        i = t.lower().rfind("x")
        name, qty = t[:i], t[i+1:]
    else:
        return t, 1
    try:
        q = int(str(qty).strip())
    except Exception:
        q = 1
    return name.strip(), max(q, 1)

def add_item_by_text(user_id: int, text: str) -> tuple[bool, str]:
    name, qty = parse_item_text(text)
    prod = get_product_by_name(name)
    if not prod:
        return False, "کالایی با این نام پیدا نشد."
    order = get_or_create_draft_order(user_id)
    add_order_item(order["order_id"], prod["product_id"], qty, prod["price"])
    return True, f"✅ «{prod['name']} × {qty}» به سبد اضافه شد."
