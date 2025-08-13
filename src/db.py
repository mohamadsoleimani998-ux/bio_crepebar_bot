import os
import psycopg2
from psycopg2.extras import DictCursor
from .base import log

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("DB_URL")

# ---------- connection ----------
def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env is missing.")
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)

def _exec(sql_text: str, params=None):
    sql_text = (sql_text or "").strip()
    if not sql_text:
        return
    with _conn() as cn, cn.cursor() as cur:
        cur.execute(sql_text, params or ())

# ---------- schema (idempotent) ----------
SCHEMA_SQL = r"""
-- users
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
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_telegram_id ON users(telegram_id);

-- settings
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO settings(key, value)
VALUES ('cashback_percent','3') ON CONFLICT(key) DO NOTHING;

-- products
CREATE TABLE IF NOT EXISTS products (
  product_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name           TEXT NOT NULL,
  price          NUMERIC NOT NULL,
  photo_file_id  TEXT,
  description    TEXT,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
/* NOTE: unique index on LOWER(name) for active items is optional; not created here. */

-- orders
CREATE TABLE IF NOT EXISTS orders (
  order_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'draft',  -- draft|submitted|paid|canceled|fulfilled
  total_amount    NUMERIC NOT NULL DEFAULT 0,
  cashback_amount NUMERIC NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- order_items
CREATE TABLE IF NOT EXISTS order_items (
  item_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id    BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
  product_id  BIGINT NOT NULL REFERENCES products(product_id),
  qty         INTEGER NOT NULL DEFAULT 1,
  unit_price  NUMERIC NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items(order_id);

-- recalc order total
CREATE OR REPLACE FUNCTION fn_recalc_order_total(p_order_id BIGINT)
RETURNS VOID AS $$
BEGIN
  UPDATE orders o
     SET total_amount = COALESCE((
       SELECT SUM(oi.qty * oi.unit_price)::NUMERIC
         FROM order_items oi
        WHERE oi.order_id = p_order_id
     ), 0)
   WHERE o.order_id = p_order_id;
END;
$$ LANGUAGE plpgsql;

-- trigger wrapper
CREATE OR REPLACE FUNCTION trg_recalc_oi()
RETURNS TRIGGER AS $$
DECLARE v_order BIGINT;
BEGIN
  IF TG_OP = 'DELETE' THEN v_order := OLD.order_id; ELSE v_order := NEW.order_id; END IF;
  PERFORM fn_recalc_order_total(v_order);
  IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_recalc_after_change ON order_items;
CREATE TRIGGER trg_recalc_after_change
AFTER INSERT OR UPDATE OR DELETE ON order_items
FOR EACH ROW EXECUTE FUNCTION trg_recalc_oi();

-- wallet tx + trigger
CREATE TABLE IF NOT EXISTS wallet_transactions (
  tx_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,   -- topup|order|refund|cashback|adjust
  amount      NUMERIC NOT NULL,
  meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_wallet_tx_user ON wallet_transactions(user_id);

CREATE OR REPLACE FUNCTION fn_apply_wallet_tx()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE users SET balance = COALESCE(balance,0) + NEW.amount
   WHERE user_id = NEW.user_id;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_wallet_tx ON wallet_transactions;
CREATE TRIGGER trg_apply_wallet_tx
AFTER INSERT ON wallet_transactions
FOR EACH ROW EXECUTE FUNCTION fn_apply_wallet_tx();

-- cashback on first paid
CREATE OR REPLACE FUNCTION fn_apply_cashback()
RETURNS TRIGGER AS $$
DECLARE percent NUMERIC := 0; amount NUMERIC := 0;
BEGIN
  IF NEW.status='paid' AND COALESCE(OLD.status,'')<>'paid' THEN
    SELECT COALESCE(NULLIF(value,'')::NUMERIC,0) INTO percent FROM settings WHERE key='cashback_percent';
    amount := ROUND(NEW.total_amount * percent / 100.0, 0);
    NEW.cashback_amount := COALESCE(NEW.cashback_amount,0) + amount;
    INSERT INTO wallet_transactions(user_id,kind,amount,meta)
    VALUES(NEW.user_id,'cashback',amount,jsonb_build_object('order_id',NEW.order_id,'percent',percent));
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_cashback ON orders;
CREATE TRIGGER trg_apply_cashback
AFTER UPDATE OF status ON orders
FOR EACH ROW EXECUTE FUNCTION fn_apply_cashback();
"""

def init_db():
    log.info("init_db() running...")
    _exec(SCHEMA_SQL)
    log.info("init_db() done.")

# ========== domain queries ==========
# Products
def list_products(page:int=1, page_size:int=6):
    off = (page-1)*page_size
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT COUNT(*) FROM products WHERE is_active=TRUE")
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT product_id AS id, name, price
              FROM products
             WHERE is_active=TRUE
             ORDER BY product_id DESC
             LIMIT %s OFFSET %s
        """, (page_size, off))
        return cur.fetchall(), total

def get_product(product_id:int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("""SELECT product_id AS id, name, price
                         FROM products WHERE product_id=%s AND is_active=TRUE""",
                    (product_id,))
        return cur.fetchone()

# Users
def upsert_user(tg_id:int, name:str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO users(telegram_id,name)
            VALUES (%s,%s)
            ON CONFLICT (telegram_id) DO UPDATE SET name=EXCLUDED.name
        """,(tg_id,name))

def get_user(tg_id:int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("""SELECT user_id AS id, telegram_id, name, balance
                         FROM users WHERE telegram_id=%s""",(tg_id,))
        return cur.fetchone()

def get_balance(user_id:int)->float:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT balance FROM users WHERE user_id=%s",(user_id,))
        r = cur.fetchone()
        return float(r[0] or 0)

# Orders
def open_draft_order(user_id:int)->int:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT order_id FROM orders WHERE user_id=%s AND status='draft'",(user_id,))
        r = cur.fetchone()
        if r: return r[0]
        cur.execute("INSERT INTO orders(user_id,status) VALUES(%s,'draft') RETURNING order_id",(user_id,))
        return cur.fetchone()[0]

def add_or_increment_item(order_id:int, product_id:int, unit_price:float, inc:int=1):
    with _conn() as cn, cn.cursor() as cur:
        # اگر نبود، بساز؛ اگر بود، فقط qty افزایش می‌دهیم
        cur.execute("""
            INSERT INTO order_items(order_id,product_id,qty,unit_price)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
        """,(order_id,product_id,inc,unit_price))
        cur.execute("""
            UPDATE order_items SET qty = qty + %s
             WHERE order_id=%s AND product_id=%s
        """,(inc,order_id,product_id))
        cur.execute("SELECT fn_recalc_order_total(%s)",(order_id,))

def change_item_qty(order_id:int, product_id:int, delta:int)->bool:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            UPDATE order_items SET qty = qty + %s
             WHERE order_id=%s AND product_id=%s
         RETURNING qty
        """,(delta,order_id,product_id))
        r = cur.fetchone()
        if not r: return False
        if r[0] <= 0:
            cur.execute("DELETE FROM order_items WHERE order_id=%s AND product_id=%s",(order_id,product_id))
            cur.execute("SELECT fn_recalc_order_total(%s)",(order_id,))
            return False
        cur.execute("SELECT fn_recalc_order_total(%s)",(order_id,))
        return True

def remove_item(order_id:int, product_id:int):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("DELETE FROM order_items WHERE order_id=%s AND product_id=%s",(order_id,product_id))
        cur.execute("SELECT fn_recalc_order_total(%s)",(order_id,))

def get_draft_with_items(user_id:int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM orders WHERE user_id=%s AND status='draft'",(user_id,))
        order = cur.fetchone()
        if not order: return None,[]
        oid = order["order_id"]
        cur.execute("""
            SELECT oi.product_id, p.name, oi.qty, oi.unit_price,
                   (oi.qty * oi.unit_price) AS line_total
              FROM order_items oi
              JOIN products p ON p.product_id = oi.product_id
             WHERE oi.order_id=%s
             ORDER BY oi.item_id
        """,(oid,))
        return order, cur.fetchall()

def pay_with_wallet(user_id:int)->bool:
    """سفارش درفت را از موجودی کاربر پرداخت می‌کند. موفق/ناموفق"""
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM orders WHERE user_id=%s AND status='draft'",(user_id,))
        order = cur.fetchone()
        if not order: return False
        total = float(order["total_amount"] or 0)
        if total <= 0: return False
        cur.execute("SELECT balance FROM users WHERE user_id=%s",(user_id,))
        bal = float(cur.fetchone()[0] or 0)
        if bal < total: return False
        # کسر موجودی از طریق wallet_transactions
        cur.execute("""INSERT INTO wallet_transactions(user_id,kind,amount,meta)
                       VALUES (%s,'order',%s,jsonb_build_object('order_id',%s))""",
                       (user_id, -total, order["order_id"]))
        # تغییر وضعیت سفارش
        cur.execute("UPDATE orders SET status='paid' WHERE order_id=%s",(order["order_id"],))
        return True
