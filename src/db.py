import psycopg2
from psycopg2.extras import DictCursor, Json
from .base import log, DATABASE_URL

# --------------------------
def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env is missing.")
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)

def _exec(sql_text: str, params=None):
    if not sql_text.strip():
        return
    with _conn() as cn, cn.cursor() as cur:
        cur.execute(sql_text, params or ())

# --------------------------
# SCHEMA
# --------------------------
SCHEMA_SQL = r"""
-- ========= users =========
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

-- ========= settings =========
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO settings(key, value) VALUES ('cashback_percent','3')
ON CONFLICT (key) DO NOTHING;

-- ========= categories =========
CREATE TABLE IF NOT EXISTS categories (
  category_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug        TEXT UNIQUE NOT NULL,
  title       TEXT NOT NULL,
  sort_order  INTEGER NOT NULL DEFAULT 100,
  is_active   BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_slug ON categories(slug);

-- ========= products =========
CREATE TABLE IF NOT EXISTS products (
  product_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category_id    BIGINT NOT NULL REFERENCES categories(category_id) ON DELETE RESTRICT,
  name           TEXT NOT NULL,
  price          NUMERIC NOT NULL,
  photo_file_id  TEXT,
  description    TEXT,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ========= orders / items =========
CREATE TABLE IF NOT EXISTS orders (
  order_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'draft',
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
CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items(order_id);

-- calc total
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

-- ========= wallet =========
CREATE TABLE IF NOT EXISTS wallet_transactions (
  tx_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,   -- topup | order | refund | cashback | adjust
  amount      NUMERIC NOT NULL, -- +increase, -decrease
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

-- ========= cashback on paid =========
CREATE OR REPLACE FUNCTION fn_apply_cashback()
RETURNS TRIGGER AS $$
DECLARE percent NUMERIC := 0; amount NUMERIC := 0;
BEGIN
  IF NEW.status='paid' AND COALESCE(OLD.status,'')<>'paid' THEN
    SELECT COALESCE(NULLIF(value,'')::NUMERIC,0) INTO percent
      FROM settings WHERE key='cashback_percent';
    amount := ROUND(NEW.total_amount * percent / 100.0, 0);
    NEW.cashback_amount := COALESCE(NEW.cashback_amount,0) + amount;
    INSERT INTO wallet_transactions(user_id, kind, amount, meta)
    VALUES(NEW.user_id, 'cashback', amount, jsonb_build_object('order_id',NEW.order_id,'percent',percent));
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_cashback ON orders;
CREATE TRIGGER trg_apply_cashback
AFTER UPDATE OF status ON orders
FOR EACH ROW EXECUTE FUNCTION fn_apply_cashback();

-- ========= topup requests =========
CREATE TABLE IF NOT EXISTS topup_requests (
  req_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  amount       NUMERIC NOT NULL,
  status       TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected
  user_msg_id  BIGINT,
  admin_msg_id BIGINT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# در صورت تفاوت نام ستون‌ها، مایگریشن سبک
MIGRATE_SQL = r"""
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_name='products' AND column_name='id'
  )
  AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_name='products' AND column_name='product_id'
  ) THEN
    EXECUTE 'ALTER TABLE products RENAME COLUMN id TO product_id';
  END IF;
END $$;
"""

# --------------------------
def init_db():
    log.info("init_db() running...")
    _exec(SCHEMA_SQL)
    _exec(MIGRATE_SQL)
    # seed categories (idempotent)
    seed = [
        ("espresso", "اسپرسو بار گرم و سرد", 100),
        ("tea", "چای و دمنوش", 110),
        ("mixhot", "ترکیبی گرم", 120),
        ("mocktail", "موکتل ها", 130),
        ("sky", "اسمونی ها", 140),
        ("cool", "خنک", 150),
        ("semi", "دمی", 160),
        ("crepe", "کرپ", 170),
        ("pancake", "پنکیک", 180),
        ("diet", "رژیمی ها", 190),
        ("matcha", "ماچا بار", 200),
    ]
    with _conn() as cn, cn.cursor() as cur:
        for slug, title, sort in seed:
            cur.execute("""
                INSERT INTO categories(slug,title,sort_order,is_active)
                VALUES(%s,%s,%s,TRUE)
                ON CONFLICT (slug) DO UPDATE SET title=EXCLUDED.title, sort_order=EXCLUDED.sort_order, is_active=TRUE
            """, (slug, title, sort))
    log.info("init_db() done.")

# --------------------------
# Domain queries
# --------------------------

# Users
def upsert_user(tg_id: int, name: str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO users(telegram_id, name)
            VALUES (%s,%s)
            ON CONFLICT (telegram_id) DO UPDATE SET name=EXCLUDED.name
        """, (tg_id, name))

def get_user_by_tg(tg_id: int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("""SELECT user_id AS id, telegram_id, name, balance FROM users WHERE telegram_id=%s""", (tg_id,))
        return cur.fetchone()

def get_balance(user_id: int) -> float:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        return float(row[0] or 0)

# Categories / Products
def list_categories():
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("""SELECT category_id AS id, slug, title FROM categories WHERE is_active=TRUE ORDER BY sort_order, category_id""")
        return cur.fetchall()

def list_products_by_category(cat_id: int, page: int=1, page_size: int=6):
    off = (page-1)*page_size
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT COUNT(*) FROM products WHERE is_active=TRUE AND category_id=%s", (cat_id,))
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT product_id AS id, name, price, description, photo_file_id
              FROM products
             WHERE is_active=TRUE AND category_id=%s
             ORDER BY product_id DESC
             LIMIT %s OFFSET %s
        """, (cat_id, page_size, off))
        return cur.fetchall(), total

def get_product_by_id(pid: int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("""
            SELECT product_id AS id, name, price, description, photo_file_id, category_id, is_active
              FROM products
             WHERE product_id=%s
        """, (pid,))
        return cur.fetchone()

def add_product(cat_id: int, name: str, price: float, description: str|None, photo_file_id: str|None):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO products(category_id,name,price,description,photo_file_id,is_active)
            VALUES(%s,%s,%s,%s,%s,TRUE)
            RETURNING product_id
        """, (cat_id, name, price, description, photo_file_id))
        return cur.fetchone()[0]

# Orders
def open_draft_order(user_id: int) -> int:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""SELECT order_id FROM orders WHERE user_id=%s AND status='draft'""", (user_id,))
        row = cur.fetchone()
        if row: return row[0]
        cur.execute("""INSERT INTO orders(user_id,status) VALUES(%s,'draft') RETURNING order_id""", (user_id,))
        return cur.fetchone()[0]

def add_or_increment_item(order_id: int, product_id: int, unit_price: float, inc: int=1):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO order_items(order_id,product_id,qty,unit_price)
            VALUES(%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
        """, (order_id, product_id, inc, unit_price))
        cur.execute("""UPDATE order_items SET qty=qty+%s WHERE order_id=%s AND product_id=%s""", (inc, order_id, product_id))
        cur.execute("SELECT fn_recalc_order_total(%s)", (order_id,))

def change_item_qty(order_id: int, product_id: int, delta: int) -> bool:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            UPDATE order_items SET qty=qty+%s
             WHERE order_id=%s AND product_id=%s
         RETURNING qty
        """, (delta, order_id, product_id))
        row = cur.fetchone()
        if not row: return False
        if row[0] <= 0:
            cur.execute("DELETE FROM order_items WHERE order_id=%s AND product_id=%s", (order_id, product_id))
            cur.execute("SELECT fn_recalc_order_total(%s)", (order_id,))
            return False
        cur.execute("SELECT fn_recalc_order_total(%s)", (order_id,))
        return True

def remove_item(order_id: int, product_id: int):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("DELETE FROM order_items WHERE order_id=%s AND product_id=%s", (order_id, product_id))
        cur.execute("SELECT fn_recalc_order_total(%s)", (order_id,))

def get_draft_with_items(user_id: int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM orders WHERE user_id=%s AND status='draft'", (user_id,))
        order = cur.fetchone()
        if not order: return None, []
        oid = order["order_id"]
        cur.execute("""
            SELECT oi.product_id, p.name, oi.qty, oi.unit_price, (oi.qty*oi.unit_price) AS line_total
              FROM order_items oi JOIN products p ON p.product_id = oi.product_id
             WHERE oi.order_id=%s ORDER BY oi.item_id
        """, (oid,))
        items = cur.fetchall()
        return order, items

def submit_order(order_id: int):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE orders SET status='submitted' WHERE order_id=%s", (order_id,))

def mark_order_paid(order_id: int):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE orders SET status='paid' WHERE order_id=%s", (order_id,))

# Wallet
def add_wallet_tx(user_id: int, kind: str, amount: float, meta: dict):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO wallet_transactions(user_id,kind,amount,meta) VALUES(%s,%s,%s,%s)""",
                    (user_id, kind, amount, Json(meta)))

# Topup
def create_topup_request(user_id: int, amount: float, user_msg_id: int) -> int:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO topup_requests(user_id,amount,status,user_msg_id)
                       VALUES(%s,%s,'pending',%s) RETURNING req_id""", (user_id, amount, user_msg_id))
        return cur.fetchone()[0]

def set_topup_admin_msg(req_id: int, admin_msg_id: int):
    _exec("UPDATE topup_requests SET admin_msg_id=%s WHERE req_id=%s", (admin_msg_id, req_id))

def decide_topup(req_id: int, approve: bool):
    newst = 'approved' if approve else 'rejected'
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("UPDATE topup_requests SET status=%s WHERE req_id=%s RETURNING user_id, amount", (newst, req_id))
        row = cur.fetchone()
        return row
