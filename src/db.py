import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, List, Dict, Tuple
from .base import DATABASE_URL, CASHBACK_PERCENT

def _conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db() -> None:
    with _conn() as con, con.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id     BIGINT PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            phone       TEXT,
            address     TEXT,
            wallet      BIGINT DEFAULT 0,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS products(
            id          BIGSERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            price       BIGINT NOT NULL,
            image_url   TEXT,
            available   BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS orders(
            id          BIGSERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL REFERENCES users(user_id),
            product_id  BIGINT NOT NULL REFERENCES products(id),
            qty         INT NOT NULL,
            total       BIGINT NOT NULL,
            cash_back   BIGINT NOT NULL DEFAULT 0,
            name        TEXT,
            phone       TEXT,
            address     TEXT,
            status      TEXT DEFAULT 'pending',
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS topups(
            id          BIGSERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL REFERENCES users(user_id),
            amount      BIGINT NOT NULL,
            method      TEXT NOT NULL,   -- 'card_to_card' | 'gateway'
            status      TEXT DEFAULT 'pending',
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
        """)
    # اندکس‌های سبک
    with _conn() as con, con.cursor() as cur:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);")

# ---- Users ----
def get_or_create_user(user_id:int, username:str, full_name:str) -> Dict:
    with _conn() as con, con.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE user_id=%s;", (user_id,))
        row = cur.fetchone()
        if row:
            return row
        cur.execute("""INSERT INTO users(user_id, username, full_name)
                       VALUES(%s,%s,%s) RETURNING *;""",
                    (user_id, username, full_name))
        return cur.fetchone()

def update_user_contact(user_id:int, phone:str=None, address:str=None, full_name:str=None):
    with _conn() as con, con.cursor() as cur:
        cur.execute("""
        UPDATE users SET
          phone = COALESCE(%s, phone),
          address = COALESCE(%s, address),
          full_name = COALESCE(%s, full_name)
        WHERE user_id=%s;""", (phone, address, full_name, user_id))

def get_wallet(user_id:int) -> int:
    with _conn() as con, con.cursor() as cur:
        cur.execute("SELECT wallet FROM users WHERE user_id=%s;", (user_id,))
        row = cur.fetchone()
        return int(row["wallet"]) if row else 0

def add_wallet(user_id:int, amount:int):
    with _conn() as con, con.cursor() as cur:
        cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id=%s;", (amount, user_id))

# ---- Products ----
def list_products(only_available:bool=True) -> List[Dict]:
    q = "SELECT * FROM products"
    if only_available:
        q += " WHERE available = TRUE"
    q += " ORDER BY id DESC"
    with _conn() as con, con.cursor() as cur:
        cur.execute(q)
        return list(cur.fetchall())

def get_product(pid:int) -> Optional[Dict]:
    with _conn() as con, con.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id=%s;", (pid,))
        return cur.fetchone()

def add_product(name:str, price:int, image_url:str=None, available:bool=True) -> int:
    with _conn() as con, con.cursor() as cur:
        cur.execute("""INSERT INTO products(name, price, image_url, available)
                       VALUES(%s,%s,%s,%s) RETURNING id;""",
                    (name, price, image_url, available))
        return int(cur.fetchone()["id"])

def edit_product(pid:int, name:str=None, price:int=None, image_url:str=None, available:bool=None):
    with _conn() as con, con.cursor() as cur:
        cur.execute("""
        UPDATE products SET
          name = COALESCE(%s, name),
          price = COALESCE(%s, price),
          image_url = COALESCE(%s, image_url),
          available = COALESCE(%s, available)
        WHERE id=%s;""", (name, price, image_url, available, pid))

def delete_product(pid:int):
    with _conn() as con, con.cursor() as cur:
        cur.execute("DELETE FROM products WHERE id=%s;", (pid,))

# ---- Orders ----
def create_order(user_id:int, product_id:int, qty:int, name:str, phone:str, address:str) -> Tuple[int, int, int]:
    prod = get_product(product_id)
    if not prod:
        raise ValueError("محصول پیدا نشد")
    total = int(prod["price"]) * int(qty)
    cash_back = (total * CASHBACK_PERCENT) // 100 if CASHBACK_PERCENT > 0 else 0
    with _conn() as con, con.cursor() as cur:
        cur.execute("""INSERT INTO orders(user_id, product_id, qty, total, cash_back, name, phone, address)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id;""",
                    (user_id, product_id, qty, total, cash_back, name, phone, address))
        order_id = int(cur.fetchone()["id"])
        # شارژ کش‌بک بعد از ایجاد سفارش (می‌توان بعد از تحویل هم اعمال کرد؛ اینجا ساده)
        if cash_back:
            cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id=%s;", (cash_back, user_id))
    return order_id, total, cash_back

# ---- Topup ----
def create_topup(user_id:int, amount:int, method:str) -> int:
    with _conn() as con, con.cursor() as cur:
        cur.execute("""INSERT INTO topups(user_id, amount, method)
                       VALUES(%s,%s,%s) RETURNING id;""", (user_id, amount, method))
        return int(cur.fetchone()["id"])
