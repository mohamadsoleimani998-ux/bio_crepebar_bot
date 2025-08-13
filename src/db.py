import contextlib
import psycopg2
import psycopg2.extras
from .base import DATABASE_URL, log, DEFAULT_CASHBACK

# ---- Connection helpers ----
def _conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

@contextlib.contextmanager
def _cursor():
    with _conn() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur

# ---- init & migrations (ایمن در برابر اجراهای تکراری) ----
DDL_CREATE = """
CREATE TABLE IF NOT EXISTS users(
    user_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_id  BIGINT UNIQUE NOT NULL,
    name         TEXT,
    phone        TEXT,
    address      TEXT,
    wallet       BIGINT NOT NULL DEFAULT 0,        -- به تومان
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products(
    product_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          TEXT NOT NULL,
    price         BIGINT NOT NULL,
    photo_file_id TEXT,
    description   TEXT,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders(
    order_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(user_id),
    product_id   BIGINT NOT NULL REFERENCES products(product_id),
    qty          INT NOT NULL DEFAULT 1,
    amount       BIGINT NOT NULL,
    cashback     INT NOT NULL DEFAULT {cb},
    status       TEXT NOT NULL DEFAULT 'NEW',   -- NEW/PAID/CANCELED
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wallet_tx(
    tx_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(user_id),
    kind        TEXT NOT NULL,                  -- TOPUP/PAYMENT/CASHBACK/ADJUST
    amount      BIGINT NOT NULL,                -- +/-
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""".format(cb=DEFAULT_CASHBACK)

# ستون‌های ضروری که ممکنه در DB قدیمی نباشند
DDL_ALTER_SAFE = [
    # users
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    # products
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS description TEXT",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
]

def init_db():
    log.info("init_db() running...")
    with _cursor() as cur:
        cur.execute(DDL_CREATE)
        for stmt in DDL_ALTER_SAFE:
            cur.execute(stmt)
    log.info("init_db() done.")

# ---- Users ----
def upsert_user(tg_id: int, name: str | None = None):
    sql = """
    INSERT INTO users(telegram_id, name)
    VALUES (%s, %s)
    ON CONFLICT (telegram_id)
    DO UPDATE SET name = COALESCE(EXCLUDED.name, users.name),
                  updated_at = NOW()
    RETURNING *;
    """
    with _cursor() as cur:
        cur.execute(sql, (tg_id, name))
        return cur.fetchone()

def set_user_profile(tg_id: int, name: str = None, phone: str = None, address: str = None):
    sql = """
    UPDATE users
       SET name = COALESCE(%s, name),
           phone = COALESCE(%s, phone),
           address = COALESCE(%s, address),
           updated_at = NOW()
     WHERE telegram_id = %s
    RETURNING *;
    """
    with _cursor() as cur:
        cur.execute(sql, (name, phone, address, tg_id))
        return cur.fetchone()

def get_user_by_tg(tg_id: int):
    with _cursor() as cur:
        cur.execute("SELECT * FROM users WHERE telegram_id=%s", (tg_id,))
        return cur.fetchone()

# ---- Wallet ----
def wallet_change(tg_id: int, amount: int, kind: str, note: str = None):
    user = get_user_by_tg(tg_id)
    if not user:
        user = upsert_user(tg_id)
    with _cursor() as cur:
        cur.execute("UPDATE users SET wallet = wallet + %s, updated_at=NOW() WHERE telegram_id=%s RETURNING user_id, wallet",
                    (amount, tg_id))
        u = cur.fetchone()
        cur.execute("INSERT INTO wallet_tx(user_id, kind, amount, note) VALUES (%s, %s, %s, %s)",
                    (u["user_id"], kind, amount, note))
        return u["wallet"]

# ---- Products ----
def add_product(name: str, price: int, photo_file_id: str | None, description: str | None):
    sql = """
    INSERT INTO products(name, price, photo_file_id, description)
    VALUES (%s, %s, %s, %s)
    RETURNING *;
    """
    with _cursor() as cur:
        cur.execute(sql, (name, price, photo_file_id, description))
        return cur.fetchone()

def list_products(limit: int = 50):
    with _cursor() as cur:
        cur.execute("SELECT * FROM products WHERE active=TRUE ORDER BY product_id DESC LIMIT %s", (limit,))
        return cur.fetchall()

# ---- Orders (ساده) ----
def create_order(tg_id: int, product_id: int, qty: int, price: int, cashback_pct: int):
    user = get_user_by_tg(tg_id)
    if not user:
        user = upsert_user(tg_id)
    amount = price * max(qty, 1)
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO orders(user_id, product_id, qty, amount, cashback) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (user["user_id"], product_id, qty, amount, cashback_pct),
        )
        return cur.fetchone()
