from psycopg2 import connect
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from .base import DATABASE_URL, log, DEFAULT_CASHBACK_PERCENT

@contextmanager
def _conn():
    cn = connect(DATABASE_URL)
    cn.autocommit = True
    try:
        yield cn
    finally:
        cn.close()

def _exec(sql: str, params=None):
    if not sql.strip():
        return
    with _conn() as cn:
        with cn.cursor() as cur:
            cur.execute(sql, params or ())

def _fetch(sql: str, params=None, one=False):
    with _conn() as cn:
        with cn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return (cur.fetchone() if one else cur.fetchall())

SCHEMA_SQL = """
-- کاربران
CREATE TABLE IF NOT EXISTS users(
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  telegram_id  BIGINT UNIQUE NOT NULL,
  name         TEXT,
  phone        TEXT,
  address      TEXT,
  balance      NUMERIC NOT NULL DEFAULT 0,
  active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- تنظیمات
CREATE TABLE IF NOT EXISTS settings(
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO settings(key,value)
VALUES ('cashback_percent', %(cashback)s::text)
ON CONFLICT (key) DO NOTHING;

-- محصولات
CREATE TABLE IF NOT EXISTS products(
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name          TEXT NOT NULL,
  price         NUMERIC NOT NULL,
  photo_file_id TEXT,
  description   TEXT,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- سفارش‌ها
CREATE TABLE IF NOT EXISTS orders(
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'draft', -- draft|submitted|paid|canceled|fulfilled
  total_amount    NUMERIC NOT NULL DEFAULT 0,
  cashback_amount NUMERIC NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- اقلام سفارش
CREATE TABLE IF NOT EXISTS order_items(
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  order_id   BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id BIGINT NOT NULL REFERENCES products(id),
  qty        INTEGER NOT NULL DEFAULT 1,
  unit_price NUMERIC NOT NULL,
  line_total NUMERIC GENERATED ALWAYS AS (qty * unit_price) STORED
);
CREATE INDEX IF NOT EXISTS ix_order_items_order ON order_items(order_id);

-- تراکنش‌های کیف پول
CREATE TABLE IF NOT EXISTS wallet_transactions(
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL, -- topup|order|refund|cashback|adjust|direct
  amount     NUMERIC NOT NULL,
  meta       JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- تریگر بروزرسانی موجودی
CREATE OR REPLACE FUNCTION fn_apply_wallet_tx()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE users SET balance = COALESCE(balance,0) + NEW.amount
  WHERE id = NEW.user_id;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_wallet_tx ON wallet_transactions;
CREATE TRIGGER trg_apply_wallet_tx
AFTER INSERT ON wallet_transactions
FOR EACH ROW EXECUTE FUNCTION fn_apply_wallet_tx();

-- مجموع سفارش
CREATE OR REPLACE FUNCTION fn_recalc_total(p_id BIGINT)
RETURNS VOID AS $$
BEGIN
  UPDATE orders o
  SET total_amount = COALESCE((SELECT SUM(line_total) FROM order_items WHERE order_id=p_id),0)
  WHERE o.id = p_id;
END; $$ LANGUAGE plpgsql;

-- کش‌بک پس از PAID شدن
CREATE OR REPLACE FUNCTION fn_apply_cashback()
RETURNS TRIGGER AS $$
DECLARE percent NUMERIC := 0; amount NUMERIC := 0;
BEGIN
  IF NEW.status='paid' AND COALESCE(OLD.status,'') <> 'paid' THEN
     SELECT COALESCE(NULLIF(value,'')::NUMERIC,0) INTO percent
     FROM settings WHERE key='cashback_percent';
     amount := ROUND(NEW.total_amount * percent / 100.0, 0);
     NEW.cashback_amount := COALESCE(NEW.cashback_amount,0) + amount;
     INSERT INTO wallet_transactions(user_id,kind,amount,meta)
       VALUES (NEW.user_id,'cashback',amount,jsonb_build_object('order_id',NEW.id,'percent',percent));
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_apply_cashback ON orders;
CREATE TRIGGER trg_apply_cashback
AFTER UPDATE ON orders
FOR EACH ROW EXECUTE FUNCTION fn_apply_cashback();
"""

# پاکسازی تکثاری‌های فعال و ایندکس یکتا روی نام
DEDUP_AND_INDEX_SQL = """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
     WHERE schemaname = ANY(current_schemas(true))
       AND indexname = 'ux_products_name_active'
  ) THEN
    WITH d AS (
      SELECT LOWER(name) ln, MIN(id) keep_id
      FROM products WHERE is_active = TRUE
      GROUP BY LOWER(name)
    )
    UPDATE products p
       SET is_active = FALSE
      FROM d
     WHERE p.is_active = TRUE
       AND LOWER(p.name) = d.ln
       AND p.id <> d.keep_id;

    EXECUTE 'CREATE UNIQUE INDEX ux_products_name_active ON products (LOWER(name)) WHERE is_active = TRUE';
  END IF;
END $$;
"""

def init_db():
    log.info("init_db() running...")
    _exec(SCHEMA_SQL, {"cashback": DEFAULT_CASHBACK_PERCENT})
    _exec(DEDUP_AND_INDEX_SQL)

# ============ API ============

def upsert_user(tg_id: int, name: str):
    sql = """
    INSERT INTO users(telegram_id,name) VALUES(%s,%s)
    ON CONFLICT (telegram_id)
      DO UPDATE SET name=COALESCE(EXCLUDED.name,users.name)
    RETURNING id, name, balance;
    """
    with _conn() as cn:
        with cn.cursor() as cur:
            cur.execute(sql, (tg_id, name))
            return cur.fetchone()

def set_user_profile(tg_id: int, name=None, phone=None, address=None):
    _exec(
        "UPDATE users SET name=COALESCE(%s,name), phone=COALESCE(%s,phone), address=COALESCE(%s,address) WHERE telegram_id=%s",
        (name, phone, address, tg_id),
    )

def get_user(tg_id: int):
    return _fetch("SELECT * FROM users WHERE telegram_id=%s", (tg_id,), one=True)

def wallet(tg_id: int):
    row = _fetch("SELECT balance FROM users WHERE telegram_id=%s", (tg_id,), one=True)
    return row["balance"] if row else 0

# محصولات
def list_products(limit=None, offset=0):
    q = "SELECT id,name,price,photo_file_id,description FROM products WHERE is_active=TRUE ORDER BY id DESC"
    if limit:
        q += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    return _fetch(q)

def count_products():
    return _fetch("SELECT COUNT(*) cnt FROM products WHERE is_active=TRUE", one=True)["cnt"]

def get_product(pid: int):
    return _fetch("SELECT id,name,price,photo_file_id,description FROM products WHERE id=%s AND is_active=TRUE", (pid,), one=True)

def add_product(name, price, photo_id=None, description=None):
    _exec(
        "INSERT INTO products(name,price,photo_file_id,description,is_active) VALUES(%s,%s,%s,%s,TRUE)",
        (name, price, photo_id, description),
    )

# سفارش‌ها
def open_draft_order(user_id: int):
    row = _fetch("SELECT id FROM orders WHERE user_id=%s AND status='draft' ORDER BY id DESC LIMIT 1", (user_id,), one=True)
    if row: return row["id"]
    with _conn() as cn:
        with cn.cursor() as cur:
            cur.execute("INSERT INTO orders(user_id,status) VALUES(%s,'draft') RETURNING id", (user_id,))
            return cur.fetchone()[0]

def add_or_increment_item(order_id: int, product_id: int, unit_price: float, inc: int = 1):
    row = _fetch("SELECT id,qty FROM order_items WHERE order_id=%s AND product_id=%s", (order_id, product_id), one=True)
    if row:
        new_qty = max(1, row["qty"] + inc)
        _exec("UPDATE order_items SET qty=%s WHERE id=%s", (new_qty, row["id"]))
    else:
        _exec("INSERT INTO order_items(order_id,product_id,qty,unit_price) VALUES(%s,%s,%s,%s)",
              (order_id, product_id, max(1, inc), unit_price))
    _exec("SELECT fn_recalc_total(%s)", (order_id,))

def get_order_details(order_id: int):
    items = _fetch("""
      SELECT oi.id, oi.product_id, p.name, oi.qty, oi.unit_price, oi.line_total
      FROM order_items oi
      JOIN products p ON p.id=oi.product_id
      WHERE oi.order_id=%s
      ORDER BY oi.id
    """, (order_id,))
    order = _fetch("SELECT id,status,total_amount,cashback_amount FROM orders WHERE id=%s", (order_id,), one=True)
    return order, items

def summarize_order(order_id: int):
    order, items = get_order_details(order_id)
    if not order: return "سبد خالی است.", 0
    lines = []
    for it in items:
        lines.append(f"• {it['name']} ×{it['qty']} — {int(it['line_total'])} تومان")
    total = int(order["total_amount"])
    txt = "🧾 <b>فاکتور</b>\n" + "\n".join(lines or ["(خالی)"]) + f"\n— — —\nجمع کل: <b>{total}</b> تومان"
    return txt, total

def submit_order(order_id: int):
    _exec("UPDATE orders SET status='submitted' WHERE id=%s", (order_id,))

def can_pay_with_wallet(user_id: int, order_id: int):
    bal = _fetch("SELECT balance FROM users WHERE id=%s", (user_id,), one=True)["balance"]
    total = _fetch("SELECT total_amount FROM orders WHERE id=%s", (order_id,), one=True)["total_amount"]
    return bal >= total, int(bal), int(total)

def pay_with_wallet(user_id: int, order_id: int):
    ok, bal, total = can_pay_with_wallet(user_id, order_id)
    if not ok:
        return False, bal, total
    _exec("INSERT INTO wallet_transactions(user_id,kind,amount,meta) VALUES(%s,'order',%s,jsonb_build_object('order_id',%s))",
          (user_id, -total, order_id))
    _exec("UPDATE orders SET status='paid' WHERE id=%s", (order_id,))
    return True, bal-total, total

def mark_paid_direct(user_id: int, order_id: int, ref: str):
    # بدون دست‌کاری موجودی؛ فقط ثبت ref برای گزارش/پیگیری
    _exec("UPDATE orders SET status='paid' WHERE id=%s", (order_id,))
    _exec("INSERT INTO wallet_transactions(user_id,kind,amount,meta) VALUES(%s,'direct',0,jsonb_build_object('order_id',%s,'ref',%s))",
          (user_id, order_id, ref))
