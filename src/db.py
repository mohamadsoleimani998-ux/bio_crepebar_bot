import os
import json
import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL".upper())
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# ------------- low-level helpers -------------
def _get_conn():
    # AUTOCOMMIT برای اجرای DDL پشت سر هم
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    conn.autocommit = True
    return conn

def _exec(sql: str, params: tuple | None = None):
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)

def _fetchone(sql: str, params: tuple | None = None):
    with _get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone()

def _fetchall(sql: str, params: tuple | None = None):
    with _get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()

# ------------- migrations -------------
def init_db():
    """
    اجرای خودکار مایگریشن‌ها؛
    اگر جدول/ایندکس/ستون نبود، می‌سازد. چند بار هم که صدا زده شود امن است.
    """
    ddl = """
    -- users
    CREATE TABLE IF NOT EXISTS users (
        id            SERIAL PRIMARY KEY,
        telegram_id   BIGINT NOT NULL,
        name          TEXT,
        phone         TEXT,
        address       TEXT,
        wallet_cents  BIGINT NOT NULL DEFAULT 0,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- اضافه کردن ستون‌ها در صورت نبودن
    ALTER TABLE users
        ADD COLUMN IF NOT EXISTS telegram_id BIGINT,
        ADD COLUMN IF NOT EXISTS name TEXT,
        ADD COLUMN IF NOT EXISTS phone TEXT,
        ADD COLUMN IF NOT EXISTS address TEXT,
        ADD COLUMN IF NOT EXISTS wallet_cents BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

    -- یونیک‌کردن telegram_id (برای ON CONFLICT)
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'users_telegram_id_key'
              AND conrelid = 'users'::regclass
        ) THEN
            ALTER TABLE users ADD CONSTRAINT users_telegram_id_key UNIQUE (telegram_id);
        END IF;
    END$$;

    -- products
    CREATE TABLE IF NOT EXISTS products (
        id           SERIAL PRIMARY KEY,
        name         TEXT NOT NULL,
        price_cents  INTEGER NOT NULL CHECK (price_cents >= 0),
        photo_url    TEXT,
        active       BOOLEAN NOT NULL DEFAULT TRUE,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- orders
    CREATE TABLE IF NOT EXISTS orders (
        id           SERIAL PRIMARY KEY,
        user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
        items        JSONB NOT NULL DEFAULT '[]'::jsonb,
        total_cents  INTEGER NOT NULL CHECK (total_cents >= 0),
        status       TEXT NOT NULL DEFAULT 'pending',
        address      TEXT,
        phone        TEXT,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- wallet transactions (topup / purchase / cashback / adjust)
    CREATE TABLE IF NOT EXISTS wallet_tx (
        id           SERIAL PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        amount_cents INTEGER NOT NULL,
        kind         TEXT NOT NULL,
        meta         JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK (kind IN ('topup','purchase','cashback','adjust'))
    );

    -- ایندکس‌های مفید
    CREATE INDEX IF NOT EXISTS idx_users_tid ON users(telegram_id);
    CREATE INDEX IF NOT EXISTS idx_products_active ON products(active);
    CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
    CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_tx(user_id);
    """
    _exec(ddl)

# ------------- users -------------
def upsert_user(telegram_id: int, name: str | None):
    """
    در صورت نبودن کاربر می‌سازد؛
    اگر باشد name را به‌روز می‌کند.
    """
    sql = """
    INSERT INTO users (telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id)
    DO UPDATE SET name = EXCLUDED.name
    RETURNING id, telegram_id, name, wallet_cents;
    """
    return _fetchone(sql, (int(telegram_id), name))

def get_user_by_tid(telegram_id: int):
    return _fetchone("SELECT * FROM users WHERE telegram_id = %s", (int(telegram_id),))

def add_wallet_tx(user_id: int, amount_cents: int, kind: str, meta: dict | None = None):
    # به‌روز کردن موجودی + ثبت تراکنش
    meta = meta or {}
    with _get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("UPDATE users SET wallet_cents = wallet_cents + %s WHERE id = %s RETURNING wallet_cents",
                    (amount_cents, user_id))
        bal = cur.fetchone()["wallet_cents"]
        cur.execute(
            "INSERT INTO wallet_tx(user_id, amount_cents, kind, meta) VALUES (%s,%s,%s,%s) RETURNING id",
            (user_id, amount_cents, kind, json.dumps(meta))
        )
        tx_id = cur.fetchone()["id"]
        return {"tx_id": tx_id, "balance": bal}

def get_wallet_balance_by_tid(telegram_id: int) -> int:
    row = _fetchone("SELECT wallet_cents FROM users WHERE telegram_id=%s", (int(telegram_id),))
    return int(row["wallet_cents"]) if row else 0

# ------------- products -------------
def add_product(name: str, price_cents: int, photo_url: str | None):
    sql = "INSERT INTO products(name, price_cents, photo_url) VALUES (%s,%s,%s) RETURNING id;"
    return _fetchone(sql, (name, int(price_cents), photo_url))["id"]

def update_product(product_id: int, name: str | None = None, price_cents: int | None = None,
                   photo_url: str | None = None, active: bool | None = None):
    sets = []
    params = []
    if name is not None:
        sets.append("name=%s"); params.append(name)
    if price_cents is not None:
        sets.append("price_cents=%s"); params.append(int(price_cents))
    if photo_url is not None:
        sets.append("photo_url=%s"); params.append(photo_url)
    if active is not None:
        sets.append("active=%s"); params.append(bool(active))
    if not sets:
        return
    params.append(int(product_id))
    _exec(f"UPDATE products SET {', '.join(sets)} WHERE id=%s", tuple(params))

def list_products(only_active: bool = True):
    if only_active:
        return _fetchall("SELECT * FROM products WHERE active = TRUE ORDER BY id DESC")
    return _fetchall("SELECT * FROM products ORDER BY id DESC")

def get_product(product_id: int):
    return _fetchone("SELECT * FROM products WHERE id=%s", (int(product_id),))

# ------------- orders -------------
def _get_or_create_user_id(telegram_id: int, name: str | None) -> int:
    return upsert_user(telegram_id, name)["id"]

def create_order_by_tid(telegram_id: int, name: str | None, items: list, total_cents: int,
                        address: str | None, phone: str | None):
    user_id = _get_or_create_user_id(telegram_id, name)
    sql = """
    INSERT INTO orders(user_id, items, total_cents, address, phone)
    VALUES (%s, %s::jsonb, %s, %s, %s)
    RETURNING id;
    """
    return _fetchone(sql, (user_id, json.dumps(items), int(total_cents), address, phone))["id"]

def mark_order_status(order_id: int, status: str):
    _exec("UPDATE orders SET status=%s WHERE id=%s", (status, int(order_id)))

# ------------- cashback helper -------------
def apply_cashback_percent(user_id: int, purchase_total_cents: int, percent: int):
    """
    افزودن کش‌بک به کیف پول (مثلاً percent=3 یعنی 3 درصد).
    """
    if percent and percent > 0:
        cashback = (purchase_total_cents * int(percent)) // 100
        if cashback > 0:
            return add_wallet_tx(user_id, cashback, "cashback", {"percent": percent})
    return {"tx_id": None, "balance": None}
