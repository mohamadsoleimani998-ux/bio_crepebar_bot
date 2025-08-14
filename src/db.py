# -*- coding: utf-8 -*-
from __future__ import annotations

import psycopg2
from psycopg2.extras import DictCursor, Json

from .base import log, DATABASE_URL, CATEGORIES

def _conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)

def _exec(sql_text: str, params=None):
    if not sql_text.strip():
        return
    with _conn() as cn, cn.cursor() as cur:
        cur.execute(sql_text, params or ())

SCHEMA_SQL = r"""
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

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO settings(key,value) VALUES ('cashback_percent','3')
ON CONFLICT (key) DO NOTHING;

-- اگر جدول وجود نداشت با ساختار درست ساخته می‌شود.
CREATE TABLE IF NOT EXISTS categories (
  slug  TEXT PRIMARY KEY,
  title TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
  product_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name           TEXT NOT NULL,
  price          NUMERIC NOT NULL,
  category_slug  TEXT REFERENCES categories(slug) ON DELETE SET NULL,
  photo_file_id  TEXT,
  description    TEXT,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
  IF TG_OP='DELETE' THEN v_order := OLD.order_id; ELSE v_order := NEW.order_id; END IF;
  PERFORM fn_recalc_order_total(v_order);
  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_recalc_after_change ON order_items;
CREATE TRIGGER trg_recalc_after_change
AFTER INSERT OR UPDATE OR DELETE ON order_items
FOR EACH ROW EXECUTE FUNCTION trg_recalc_oi();

CREATE TABLE IF NOT EXISTS wallet_transactions (
  tx_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,
  amount      NUMERIC NOT NULL,
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

CREATE OR REPLACE FUNCTION fn_apply_cashback()
RETURNS TRIGGER AS $$
DECLARE percent NUMERIC := 0; amount NUMERIC := 0;
BEGIN
  IF NEW.status='paid' AND COALESCE(OLD.status,'') <> 'paid' THEN
    SELECT COALESCE(NULLIF(value,'')::NUMERIC, 0) INTO percent
      FROM settings WHERE key='cashback_percent';
    amount := ROUND(NEW.total_amount * percent / 100.0, 0);
    NEW.cashback_amount := COALESCE(NEW.cashback_amount,0) + amount;
    INSERT INTO wallet_transactions(user_id,kind,amount,meta)
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

def _col_exists(cur, table: str, col: str) -> bool:
    cur.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name=%s AND column_name=%s
        LIMIT 1
    """, (table, col))
    return cur.fetchone() is not None

def _table_exists(cur, table: str) -> bool:
    cur.execute("""
        SELECT 1 FROM information_schema.tables
         WHERE table_name=%s
        LIMIT 1
    """, (table,))
    return cur.fetchone() is not None

def _ensure_categories_schema():
    with _conn() as cn, cn.cursor() as cur:
        # اگر جدول نیست، ساختار کامل را بسازیم (CREATE IF NOT EXISTS در SCHEMA_SQL هم هست، اینجا جهت اطمینان)
        cur.execute("CREATE TABLE IF NOT EXISTS categories (slug TEXT PRIMARY KEY, title TEXT NOT NULL)")

        # اضافه‌کردن ستون‌ها اگر نبودند
        cur.execute("ALTER TABLE categories ADD COLUMN IF NOT EXISTS slug TEXT")
        cur.execute("ALTER TABLE categories ADD COLUMN IF NOT EXISTS title TEXT")

        # اگر قبلاً ستونی به نام name بوده، title را از آن پر کنیم
        has_name = _col_exists(cur, "categories", "name")
        if has_name:
            cur.execute("UPDATE categories SET title = COALESCE(title, name) WHERE (title IS NULL OR title='') AND name IS NOT NULL")

        # اگر slug خالی است، از title (یا name) بسازیم
        cur.execute("""
            UPDATE categories
               SET slug = COALESCE(slug,
                                    regexp_replace(lower(COALESCE(title, %s)), '\s+', '_', 'g'))
             WHERE slug IS NULL OR slug=''
        """, ("",))

        # ایندکس یکتا روی slug
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_slug ON categories(slug)")
        cn.commit()

def init_db():
    log.info("init_db() running...")
    _exec(SCHEMA_SQL)
    _ensure_categories_schema()

    # seed categories (به‌روزرسانی عنوان‌ها)
    with _conn() as cn, cn.cursor() as cur:
        for slug, title in CATEGORIES:
            cur.execute("""
                INSERT INTO categories(slug,title)
                VALUES(%s,%s)
                ON CONFLICT (slug) DO UPDATE SET title=EXCLUDED.title
            """, (slug, title))
    log.info("init_db() done.")

# ---------- users ----------
def upsert_user(tg_id: int, name: str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO users(telegram_id, name)
            VALUES (%s,%s)
            ON CONFLICT (telegram_id) DO UPDATE SET name=EXCLUDED.name
        """, (tg_id, name))

def get_user(tg_id: int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("""SELECT user_id AS id, telegram_id, name, balance
                         FROM users WHERE telegram_id=%s""", (tg_id,))
        return cur.fetchone()

# ---------- products ----------
def add_product(name: str, price: int, category_slug: str | None, photo_file_id: str | None, description: str | None):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO products(name,price,category_slug,photo_file_id,description,is_active)
                       VALUES(%s,%s,%s,%s,%s,TRUE) RETURNING product_id""",
                    (name, price, category_slug, photo_file_id, description or None))
        return cur.fetchone()[0]

def list_products_by_category(slug: str, page: int, page_size: int):
    off = (page-1) * page_size
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT COUNT(*) FROM products WHERE is_active=TRUE AND category_slug=%s", (slug,))
        total = cur.fetchone()[0]
        cur.execute("""SELECT product_id AS id, name, price
                         FROM products
                        WHERE is_active=TRUE AND category_slug=%s
                        ORDER BY product_id DESC
                        LIMIT %s OFFSET %s""", (slug, page_size, off))
        return cur.fetchall(), total

def get_product(prod_id: int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("""SELECT product_id AS id, name, price FROM products
                       WHERE product_id=%s AND is_active=TRUE""", (prod_id,))
        return cur.fetchone()

# ---------- orders ----------
def open_draft_order(user_id: int) -> int:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""SELECT order_id FROM orders WHERE user_id=%s AND status='draft'""", (user_id,))
        r = cur.fetchone()
        if r: return r[0]
        cur.execute("""INSERT INTO orders(user_id,status) VALUES(%s,'draft') RETURNING order_id""", (user_id,))
        return cur.fetchone()[0]

def add_or_increment_item(order_id: int, product_id: int, unit_price: int, inc: int = 1):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO order_items(order_id,product_id,qty,unit_price)
            VALUES(%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
        """, (order_id, product_id, inc, unit_price))
        cur.execute("""UPDATE order_items SET qty=qty+%s
                         WHERE order_id=%s AND product_id=%s""",
                    (inc, order_id, product_id))
        cur.execute("SELECT fn_recalc_order_total(%s)", (order_id,))

def get_draft_with_items(user_id: int):
    with _conn() as cn, cn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute("SELECT * FROM orders WHERE user_id=%s AND status='draft'", (user_id,))
        order = cur.fetchone()
        if not order:
            return None, []
        oid = order["order_id"]
        cur.execute("""
            SELECT oi.product_id, p.name, oi.qty, oi.unit_price, (oi.qty*oi.unit_price) AS line_total
              FROM order_items oi
              JOIN products p ON p.product_id = oi.product_id
             WHERE oi.order_id=%s
             ORDER BY oi.item_id
        """, (oid,))
        items = cur.fetchall()
        return order, items

def set_order_status(order_id: int, new_status: str):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("UPDATE orders SET status=%s WHERE order_id=%s", (new_status, order_id))

# ---------- wallet ----------
def get_balance(user_id: int) -> int:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,))
        r = cur.fetchone()
        return int(r[0] or 0)

def add_wallet_tx(user_id: int, kind: str, amount: int, meta: dict):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""INSERT INTO wallet_transactions(user_id,kind,amount,meta)
                       VALUES(%s,%s,%s,%s)""", (user_id, kind, amount, Json(meta)))
