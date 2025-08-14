import psycopg2
from psycopg2.extras import DictCursor
import os
from .base import log, DATABASE_URL

def _conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)

def _exec(sql, params=None):
    if not sql.strip():
        return
    with _conn() as cn, cn.cursor() as cur:
        cur.execute(sql, params or ())

SCHEMA_SQL = r"""
-- =============== users ===============
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

-- =============== settings ===============
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO settings(key,value) VALUES('cashback_percent','3')
ON CONFLICT (key) DO NOTHING;

-- =============== categories ===============
CREATE TABLE IF NOT EXISTS categories (
  category_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        TEXT UNIQUE NOT NULL
);

-- داده‌های دسته‌ها
INSERT INTO categories(name) VALUES
('اسپرسو بار گرم و سرد'),
('چای و دمنوش'),
('ترکیبی گرم'),
('موکتل ها'),
('اسمونی ها'),
('خنک'),
('دمی'),
('کرپ'),
('پنکیک'),
('رژیمی ها'),
('ماچا بار')
ON CONFLICT (name) DO NOTHING;

-- =============== products ===============
CREATE TABLE IF NOT EXISTS products (
  product_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category_id    BIGINT REFERENCES categories(category_id),
  name           TEXT NOT NULL,
  price          NUMERIC NOT NULL,
  photo_file_id  TEXT,
  description    TEXT,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- ایندکس برای جستجو
CREATE INDEX IF NOT EXISTS ix_products_cat_active ON products(category_id,is_active);

-- =============== orders / items ===============
CREATE TABLE IF NOT EXISTS orders (
  order_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'draft',  -- draft|submitted|paid|canceled|fulfilled
  pay_method      TEXT,                           -- wallet|card2card
  total_amount    NUMERIC NOT NULL DEFAULT 0,
  cashback_amount NUMERIC NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_items (
  item_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id    BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
  product_id  BIGINT NOT NULL REFERENCES products(product_id),
  qty         INTEGER NOT NULL DEFAULT 1,
  unit_price  NUMERIC NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_order_items_order ON order_items(order_id);

-- جمع سفارش
CREATE OR REPLACE FUNCTION fn_recalc_order_total(p_order_id BIGINT)
RETURNS VOID AS $$
BEGIN
  UPDATE orders o
     SET total_amount = COALESCE((
       SELECT SUM(oi.qty * oi.unit_price)::NUMERIC
         FROM order_items oi
        WHERE oi.order_id = p_order_id
     ),0)
   WHERE o.order_id = p_order_id;
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION trg_recalc_oi()
RETURNS TRIGGER AS $$
DECLARE v_order BIGINT;
BEGIN
  IF TG_OP='DELETE' THEN v_order := OLD.order_id; ELSE v_order := NEW.order_id; END IF;
  PERFORM fn_recalc_order_total(v_order);
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_recalc_after_change ON order_items;
CREATE TRIGGER trg_recalc_after_change
AFTER INSERT OR UPDATE OR DELETE ON order_items
FOR EACH ROW EXECUTE FUNCTION trg_recalc_oi();

-- =============== wallet ===============
CREATE TABLE IF NOT EXISTS wallet_transactions (
  tx_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,   -- topup|order|refund|cashback|adjust
  amount      NUMERIC NOT NULL,
  meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_wallet_user ON wallet_transactions(user_id);

CREATE OR REPLACE FUNCTION fn_apply_wallet_tx()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE users SET balance = COALESCE(balance,0) + NEW.amount WHERE user_id=NEW.user_id;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_wallet_tx ON wallet_transactions;
CREATE TRIGGER trg_apply_wallet_tx
AFTER INSERT ON wallet_transactions
FOR EACH ROW EXECUTE FUNCTION fn_apply_wallet_tx();

-- =============== cashback بعد از paid ===============
CREATE OR REPLACE FUNCTION fn_apply_cashback()
RETURNS TRIGGER AS $$
DECLARE pct NUMERIC := 0; amt NUMERIC := 0;
BEGIN
  IF NEW.status='paid' AND COALESCE(OLD.status,'')<>'paid' THEN
    SELECT COALESCE(NULLIF(value,'')::NUMERIC,0) INTO pct FROM settings WHERE key='cashback_percent';
    amt := ROUND(NEW.total_amount * pct / 100.0, 0);
    NEW.cashback_amount := COALESCE(NEW.cashback_amount,0) + amt;
    INSERT INTO wallet_transactions(user_id,kind,amount,meta)
      VALUES(NEW.user_id,'cashback',amt,jsonb_build_object('order_id',NEW.order_id,'percent',pct));
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_cashback ON orders;
CREATE TRIGGER trg_apply_cashback
AFTER UPDATE OF status ON orders
FOR EACH ROW EXECUTE FUNCTION fn_apply_cashback();

-- =============== card2card topup requests ===============
CREATE TABLE IF NOT EXISTS topup_requests (
  req_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  amount     NUMERIC NOT NULL,
  caption    TEXT,
  photo_file_id TEXT,
  status     TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

def init_db():
    log.info("init_db() running...")
    _exec(SCHEMA_SQL)
    log.info("init_db() done.")

# -------- users ----------
def upsert_user(tg_id:int, name:str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO users(telegram_id,name) VALUES(%s,%s)
            ON CONFLICT (telegram_id) DO UPDATE SET name=EXCLUDED.name
        """,(tg_id,name))

def get_user_by_tg(tg_id:int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT user_id,telegram_id,name,balance FROM users WHERE telegram_id=%s",(tg_id,))
        return cur.fetchone()

def get_balance(user_id:int)->float:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT balance FROM users WHERE user_id=%s",(user_id,))
        v = cur.fetchone()[0] or 0
        return float(v)

# -------- categories & products ----------
def list_categories():
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT category_id,name FROM categories ORDER BY category_id")
        return cur.fetchall()

def add_product(category_id:int, name:str, price:float, desc:str=None, photo_id:str=None):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO products(category_id,name,price,description,photo_file_id)
                       VALUES(%s,%s,%s,%s,%s)""",
                    (category_id,name,price,desc,photo_id))

def list_products_by_cat(cat_id:int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("""SELECT product_id,name,price,is_active
                         FROM products
                        WHERE category_id=%s AND is_active=TRUE
                        ORDER BY product_id DESC""",(cat_id,))
        return cur.fetchall()

def get_product(pid:int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("""SELECT product_id,name,price,photo_file_id FROM products
                        WHERE product_id=%s AND is_active=TRUE""",(pid,))
        return cur.fetchone()

# -------- orders ----------
def open_draft_order(user_id:int)->int:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT order_id FROM orders WHERE user_id=%s AND status='draft'",(user_id,))
        r=cur.fetchone()
        if r: return r[0]
        cur.execute("INSERT INTO orders(user_id,status) VALUES(%s,'draft') RETURNING order_id",(user_id,))
        return cur.fetchone()[0]

def add_or_inc_item(order_id:int, product_id:int, unit_price:float, inc:int=1):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO order_items(order_id,product_id,qty,unit_price)
                       VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (order_id,product_id,inc,unit_price))
        cur.execute("""UPDATE order_items SET qty=qty+%s
                        WHERE order_id=%s AND product_id=%s""",(inc,order_id,product_id))
        cur.execute("SELECT fn_recalc_order_total(%s)",(order_id,))

def get_draft_with_items(user_id:int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM orders WHERE user_id=%s AND status='draft'",(user_id,))
        order = cur.fetchone()
        if not order: return None,[]
        cur.execute("""SELECT oi.product_id,p.name,oi.qty,oi.unit_price,(oi.qty*oi.unit_price) AS line_total
                         FROM order_items oi JOIN products p ON p.product_id=oi.product_id
                        WHERE oi.order_id=%s ORDER BY oi.item_id""",(order["order_id"],))
        return order, cur.fetchall()

def set_order_status(order_id:int, status:str, method:str=None):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE orders SET status=%s, pay_method=COALESCE(%s,pay_method) WHERE order_id=%s",
                    (status, method, order_id))

# -------- wallet / topup ----------
def add_wallet_tx(user_id:int, kind:str, amount:float, meta:dict):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO wallet_transactions(user_id,kind,amount,meta)
                       VALUES(%s,%s,%s,%s)""",(user_id,kind,amount,meta))

def create_topup_request(user_id:int, amount:float, caption:str, photo_id:str):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("""INSERT INTO topup_requests(user_id,amount,caption,photo_file_id)
                       VALUES(%s,%s,%s,%s) RETURNING req_id""",(user_id,amount,caption,photo_id))
        return cur.fetchone()["req_id"]

def set_topup_status(req_id:int, status:str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE topup_requests SET status=%s WHERE req_id=%s",(status,req_id))
