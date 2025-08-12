from contextlib import contextmanager
import psycopg2, psycopg2.extras
from .base import DATABASE_URL, log, CASHBACK_PERCENT

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

def _exec(sql, params=None, fetch="none"):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            if fetch == "one":
                row = cur.fetchone()
                conn.commit()
                return row
            elif fetch == "all":
                rows = cur.fetchall()
                conn.commit()
                return rows
            conn.commit()

# ── ساخت/به‌روزرسانی اسکیما ────────────────────────────────────────────────
def init_db():
    log.info("init_db: ensuring tables/columns exist")

    # users
    _exec("""
    CREATE TABLE IF NOT EXISTS users (
        user_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        telegram_id    BIGINT UNIQUE,
        name           TEXT,
        phone          TEXT,
        address        TEXT,
        active         BOOLEAN DEFAULT TRUE,
        wallet_balance INTEGER  DEFAULT 0,
        is_admin       BOOLEAN  DEFAULT FALSE,
        created_at     TIMESTAMPTZ DEFAULT NOW()
    );""")

    # columns safeguard (برای دیتابیس‌های قبلاً ساخته‌شده)
    _exec("""ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT;""")
    _exec("""ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT;""")
    _exec("""ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance INTEGER DEFAULT 0;""")
    _exec("""ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;""")
    _exec("""ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE;""")
    _exec("""ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();""")

    # products
    _exec("""
    CREATE TABLE IF NOT EXISTS products (
        id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name          TEXT NOT NULL,
        price         INTEGER NOT NULL,
        photo_file_id TEXT,
        description   TEXT DEFAULT '',
        active        BOOLEAN DEFAULT TRUE,
        created_at    TIMESTAMPTZ DEFAULT NOW()
    );""")
    _exec("""ALTER TABLE products ADD COLUMN IF NOT EXISTS description TEXT DEFAULT '';""")
    _exec("""ALTER TABLE products ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE;""")

    # orders
    _exec("""
    CREATE TABLE IF NOT EXISTS orders (
        id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id    BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
        status     TEXT DEFAULT 'pending',
        total      INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""")

    # order_items
    _exec("""
    CREATE TABLE IF NOT EXISTS order_items (
        id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        order_id   BIGINT REFERENCES orders(id) ON DELETE CASCADE,
        product_id BIGINT REFERENCES products(id) ON DELETE RESTRICT,
        qty        INTEGER DEFAULT 1,
        price      INTEGER NOT NULL
    );""")

    # wallet transactions (شارژ/کسر/کش‌بک)
    _exec("""
    CREATE TABLE IF NOT EXISTS transactions (
        id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id    BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
        type       TEXT NOT NULL,  -- 'charge' | 'spend' | 'cashback'
        amount     INTEGER NOT NULL,
        note       TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );""")

# ── CRUD ساده ────────────────────────────────────────────────────────────────
def upsert_user(telegram_id: int, name: str | None = None, is_admin: bool = False):
    row = _exec(
        """INSERT INTO users(telegram_id, name, is_admin)
           VALUES (%s, %s, %s)
           ON CONFLICT (telegram_id) DO UPDATE
           SET name = COALESCE(EXCLUDED.name, users.name),
               is_admin = users.is_admin OR EXCLUDED.is_admin
           RETURNING *;""",
        (telegram_id, name, is_admin), fetch="one"
    )
    return row

def update_profile(telegram_id: int, name: str, phone: str, address: str):
    _exec("""UPDATE users SET name=%s, phone=%s, address=%s WHERE telegram_id=%s;""",
          (name, phone, address, telegram_id))

def get_user_by_tid(tid: int):
    return _exec("""SELECT * FROM users WHERE telegram_id=%s;""", (tid,), fetch="one")

def add_product(name: str, price: int, photo_file_id: str | None, description: str = ""):
    return _exec("""INSERT INTO products(name, price, photo_file_id, description)
                    VALUES(%s,%s,%s,%s) RETURNING *;""",
                 (name, price, photo_file_id, description), fetch="one")

def list_products(active_only=True):
    if active_only:
        return _exec("""SELECT * FROM products WHERE active IS TRUE ORDER BY id DESC;""", fetch="all")
    return _exec("""SELECT * FROM products ORDER BY id DESC;""", fetch="all")

def wallet_balance(tid: int) -> int:
    row = _exec("""SELECT wallet_balance FROM users WHERE telegram_id=%s;""", (tid,), fetch="one")
    return int(row["wallet_balance"]) if row else 0

def wallet_change(tid: int, amount: int, trx_type: str, note: str=""):
    _exec("""UPDATE users SET wallet_balance = wallet_balance + %s WHERE telegram_id=%s;""",
          (amount, tid))
    u = get_user_by_tid(tid)
    if u:
        _exec("""INSERT INTO transactions(user_id, type, amount, note)
                VALUES(%s,%s,%s,%s);""",
              (u["user_id"], trx_type, amount, note))

def apply_cashback(tid: int, paid_amount: int):
    if CASHBACK_PERCENT <= 0: 
        return 0
    reward = round(paid_amount * CASHBACK_PERCENT / 100)
    if reward > 0:
        wallet_change(tid, reward, "cashback", f"{CASHBACK_PERCENT}% cashback")
    return reward
