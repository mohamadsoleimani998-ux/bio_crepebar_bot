import os
import psycopg2
from psycopg2.extras import DictCursor

from .base import log, DATABASE_URL, CASHBACK_PERCENT

# -------------- connect helpers --------------
def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env is missing.")
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)

def _exec(sql_text: str, params=None):
    if not sql_text.strip():
        return
    with _conn() as cn, cn.cursor() as cur:
        cur.execute(sql_text, params or ())

# -------------- Schema (idempotent) --------------
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
INSERT INTO settings(key,value) VALUES ('cashback_percent', %s)
ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value;

-- categories
CREATE TABLE IF NOT EXISTS categories (
  category_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name         TEXT UNIQUE NOT NULL
);

-- products
CREATE TABLE IF NOT EXISTS products (
  product_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category       TEXT,
  name           TEXT NOT NULL,
  price          NUMERIC NOT NULL,
  photo_file_id  TEXT,
  description    TEXT,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- orders
CREATE TABLE IF NOT EXISTS orders (
  order_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'draft',
  total_amount    NUMERIC NOT NULL DEFAULT 0,
  cashback_amount NUMERIC NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- order items
CREATE TABLE IF NOT EXISTS order_items (
  item_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id    BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
  product_id  BIGINT NOT NULL REFERENCES products(product_id),
  qty         INTEGER NOT NULL DEFAULT 1,
  unit_price  NUMERIC NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items(order_id);

-- wallet tx
CREATE TABLE IF NOT EXISTS wallet_transactions (
  tx_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,   -- topup | order | refund | cashback | adjust
  amount      NUMERIC NOT NULL,
  meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_wallet_tx_user ON wallet_transactions(user_id);

-- topup requests
CREATE TABLE IF NOT EXISTS topup_requests (
  req_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  amount        NUMERIC NOT NULL,
  photo_file_id TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending', -- pending/approved/rejected
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- total recalc
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

-- items trigger
CREATE OR REPLACE FUNCTION trg_recalc_oi()
RETURNS TRIGGER AS $$
DECLARE v_order BIGINT;
BEGIN
  IF TG_OP='DELETE' THEN v_order:=OLD.order_id; ELSE v_order:=NEW.order_id; END IF;
  PERFORM fn_recalc_order_total(v_order);
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_recalc_after_change ON order_items;
CREATE TRIGGER trg_recalc_after_change
AFTER INSERT OR UPDATE OR DELETE ON order_items
FOR EACH ROW EXECUTE FUNCTION trg_recalc_oi();

-- cashback on paid
CREATE OR REPLACE FUNCTION fn_apply_cashback()
RETURNS TRIGGER AS $$
DECLARE percent NUMERIC := 0; amount NUMERIC := 0;
BEGIN
  IF NEW.status='paid' AND COALESCE(OLD.status,'') <> 'paid' THEN
    SELECT COALESCE(NULLIF(value,'')::NUMERIC,0) INTO percent
      FROM settings WHERE key='cashback_percent';
    amount := ROUND(NEW.total_amount * percent / 100.0, 0);
    NEW.cashback_amount := COALESCE(NEW.cashback_amount,0) + amount;
    INSERT INTO wallet_transactions(user_id, kind, amount, meta)
    VALUES(NEW.user_id,'cashback',amount,jsonb_build_object('order_id',NEW.order_id,'percent',percent));
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_cashback ON orders;
CREATE TRIGGER trg_apply_cashback
AFTER UPDATE OF status ON orders
FOR EACH ROW EXECUTE FUNCTION fn_apply_cashback();
"""

def init_db():
    log.info("init_db() running...")
    with _conn() as cn, cn.cursor() as cur:
        cur.execute(SCHEMA_SQL, (CASHBACK_PERCENT,))
    log.info("init_db() done.")

# ----------- Users -----------
def upsert_user(tg_id: int, name: str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO users(telegram_id,name)
            VALUES(%s,%s)
            ON CONFLICT(telegram_id) DO UPDATE SET name=EXCLUDED.name
        """, (tg_id, name))

def by_tg(tg_id: int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT user_id AS id, telegram_id, name, balance FROM users WHERE telegram_id=%s", (tg_id,))
        return cur.fetchone()

def all_users_ids():
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT telegram_id FROM users WHERE active=TRUE")
        return [r[0] for r in cur.fetchall()]

# ----------- Categories -----------
DEFAULT_CATEGORIES = [
    "اسپرسو بار گرم و سرد", "چای و دمنوش", "ترکیبی گرم", "موکتل ها",
    "اسمونی ها", "خنک", "دمی", "کرپ", "پنکیک", "رژیمی ها", "ماچا بار",
]
def ensure_categories():
    with _conn() as cn, cn.cursor() as cur:
        for c in DEFAULT_CATEGORIES:
            cur.execute("INSERT INTO categories(name) VALUES(%s) ON CONFLICT(name) DO NOTHING", (c,))

def list_categories():
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT name FROM categories ORDER BY category_id")
        return [r[0] for r in cur.fetchall()]

def add_category(name:str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("INSERT INTO categories(name) VALUES(%s) ON CONFLICT(name) DO NOTHING", (name,))

def del_category(name:str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("DELETE FROM categories WHERE name=%s", (name,))

# ----------- Products -----------
def add_product(name:str, price:float, category:str, desc:str=None, photo_file_id:str=None):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO products(name,price,category,description,photo_file_id,is_active)
                       VALUES(%s,%s,%s,%s,%s,TRUE)
                       RETURNING product_id""", (name, price, category, desc, photo_file_id))
        return cur.fetchone()[0]

def list_products(category:str, page:int=1, page_size:int=6):
    off = (page-1)*page_size
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT COUNT(*) FROM products WHERE is_active=TRUE AND (category=%s OR %s IS NULL)",
                    (category, category))
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT product_id AS id,name,price,category
              FROM products
             WHERE is_active=TRUE AND (category=%s OR %s IS NULL)
             ORDER BY product_id DESC
             LIMIT %s OFFSET %s
        """,(category,category,page_size,off))
        return cur.fetchall(), total

def list_products_admin(search:str=None, page:int=1, page_size:int=10):
    off=(page-1)*page_size
    q = "TRUE"
    args=[]
    if search:
        q = "LOWER(name) LIKE LOWER(%s)"
        args=[f"%{search}%"]
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(f"SELECT COUNT(*) FROM products WHERE {q}", args)
        total=cur.fetchone()[0]
        cur.execute(f"""SELECT product_id AS id, name, price, category, is_active
                        FROM products WHERE {q}
                        ORDER BY product_id DESC
                        LIMIT %s OFFSET %s""", args+[page_size, off])
        return cur.fetchall(), total

def get_product(pid:int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT product_id AS id,name,price,category,is_active FROM products WHERE product_id=%s", (pid,))
        return cur.fetchone()

def set_product_active(pid:int, active:bool):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE products SET is_active=%s WHERE product_id=%s", (active, pid))

def update_price(pid:int, new_price:float):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE products SET price=%s WHERE product_id=%s", (new_price, pid))

def delete_product(pid:int):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE product_id=%s", (pid,))

# ----------- Orders -----------
def open_draft(user_id:int)->int:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT order_id FROM orders WHERE user_id=%s AND status='draft'", (user_id,))
        r = cur.fetchone()
        if r: return r[0]
        cur.execute("INSERT INTO orders(user_id,status) VALUES(%s,'draft') RETURNING order_id", (user_id,))
        return cur.fetchone()[0]

def add_or_inc_item(order_id:int, pid:int, unit_price:float, inc:int=1):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO order_items(order_id,product_id,qty,unit_price)
                       VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (order_id,pid,inc,unit_price))
        cur.execute("""UPDATE order_items SET qty=qty+%s
                        WHERE order_id=%s AND product_id=%s""",
                    (inc,order_id,pid))
        cur.execute("SELECT fn_recalc_order_total(%s)", (order_id,))

def draft_with_items(user_id:int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM orders WHERE user_id=%s AND status='draft'", (user_id,))
        order = cur.fetchone()
        if not order: return None,[]
        oid = order["order_id"]
        cur.execute("""
            SELECT oi.product_id, p.name, oi.qty, oi.unit_price, (oi.qty*oi.unit_price) AS line_total
              FROM order_items oi JOIN products p ON p.product_id=oi.product_id
             WHERE oi.order_id=%s ORDER BY oi.item_id
        """, (oid,))
        return order, cur.fetchall()

def list_orders(status:str=None, page:int=1, page_size:int=10):
    off=(page-1)*page_size
    where="TRUE"; args=[]
    if status: where="status=%s"; args=[status]
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(f"SELECT COUNT(*) FROM orders WHERE {where}", args)
        total=cur.fetchone()[0]
        cur.execute(f"""SELECT order_id,user_id,status,total_amount,cashback_amount,created_at
                        FROM orders WHERE {where}
                        ORDER BY order_id DESC LIMIT %s OFFSET %s""", args+[page_size,off])
        return cur.fetchall(), total

def set_order_status(order_id:int, status:str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE orders SET status=%s WHERE order_id=%s", (status, order_id))

# ----------- Wallet / Topup -----------
def balance(user_id:int)->float:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,))
        r=cur.fetchone(); return float(r[0] or 0)

def credit(user_id:int, amount:float, kind:str="topup", meta:dict=None):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO wallet_transactions(user_id,kind,amount,meta)
                       VALUES(%s,%s,%s,%s)""", (user_id,kind,amount,meta or {}))

def create_topup_request(user_id:int, amount:float, photo_file_id:str)->int:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO topup_requests(user_id,amount,photo_file_id)
                       VALUES(%s,%s,%s) RETURNING req_id""", (user_id,amount,photo_file_id))
        return cur.fetchone()[0]

def set_topup_status(req_id:int, status:str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE topup_requests SET status=%s WHERE req_id=%s", (status,req_id))

def list_topups(status:str='pending', page:int=1, page_size:int=10):
    off=(page-1)*page_size
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT COUNT(*) FROM topup_requests WHERE status=%s", (status,))
        total=cur.fetchone()[0]
        cur.execute("""SELECT req_id,user_id,amount,photo_file_id,status,created_at
                       FROM topup_requests WHERE status=%s
                       ORDER BY req_id DESC LIMIT %s OFFSET %s""", (status,page_size,off))
        return cur.fetchall(), total

# ----------- Settings -----------
def set_cashback(percent:float):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO settings(key,value) VALUES('cashback_percent',%s)
                       ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value""", (percent,))
