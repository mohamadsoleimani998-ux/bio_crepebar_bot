import psycopg2, psycopg2.extras
from .base import DATABASE_URL, log

def _conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    """ایجاد جداول در صورت نبودن — سریع و idempotent"""
    ddl = """
    CREATE TABLE IF NOT EXISTS users(
      user_id    BIGINT PRIMARY KEY,
      telegram_id BIGINT UNIQUE,
      name       TEXT,
      phone      TEXT,
      address    TEXT,
      active     BOOLEAN DEFAULT TRUE,
      balance    BIGINT DEFAULT 0,           -- ریال
      created_at TIMESTAMPTZ DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS products(
      id BIGSERIAL PRIMARY KEY,
      name TEXT NOT NULL,
      price BIGINT NOT NULL,
      photo_file_id TEXT,
      description TEXT DEFAULT '',
      active BOOLEAN DEFAULT TRUE,
      created_at TIMESTAMPTZ DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS orders(
      id BIGSERIAL PRIMARY KEY,
      user_id BIGINT REFERENCES users(user_id),
      items JSONB NOT NULL,
      total BIGINT NOT NULL,
      cashback BIGINT NOT NULL DEFAULT 0,
      created_at TIMESTAMPTZ DEFAULT now()
    );
    """
    with _conn() as cx, cx.cursor() as cur:
        cur.execute(ddl)
    log.info("init_db() done")

def upsert_user(user_id:int, tg_id:int, name:str):
    sql = """
    INSERT INTO users(user_id, telegram_id, name, active)
    VALUES (%s,%s,%s,TRUE)
    ON CONFLICT (user_id) DO UPDATE SET name=EXCLUDED.name, active=TRUE
    RETURNING user_id, balance;
    """
    with _conn() as cx, cx.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (user_id, tg_id, name))
        return cur.fetchone()

def set_profile(user_id:int, name:str=None, phone:str=None, address:str=None):
    sql = "UPDATE users SET name=COALESCE(%s,name), phone=COALESCE(%s,phone), address=COALESCE(%s,address) WHERE user_id=%s"
    with _conn() as cx, cx.cursor() as cur:
        cur.execute(sql, (name, phone, address, user_id))

def get_balance(user_id:int) -> int:
    with _conn() as cx, cx.cursor() as cur:
        cur.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        return row[0] if row else 0

def add_balance(user_id:int, amount:int):
    with _conn() as cx, cx.cursor() as cur:
        cur.execute("UPDATE users SET balance=COALESCE(balance,0)+%s WHERE user_id=%s", (amount, user_id))

def add_product(name:str, price:int, photo_id:str|None, description:str):
    sql = "INSERT INTO products(name,price,photo_file_id,description) VALUES(%s,%s,%s,%s)"
    with _conn() as cx, cx.cursor() as cur:
        cur.execute(sql, (name, price, photo_id, description))

def list_products():
    with _conn() as cx, cx.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id,name,price,photo_file_id,description FROM products WHERE active=TRUE ORDER BY id DESC LIMIT 50")
        return cur.fetchall()
