# src/db.py
import os
import ssl
import psycopg2
import psycopg2.extras

# ====== اتصال به دیتابیس (Neon) ======
# نکته: Neon معمولاً SSL می‌خواهد. اگر در DATABASE_URL sslmode نبود، اضافه‌اش می‌کنیم.
def _ensure_sslmode(url: str) -> str:
    if "sslmode=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}sslmode=require"

DATABASE_URL = _ensure_sslmode(os.environ.get("DATABASE_URL", ""))

_conn = None
def get_conn():
    global _conn
    if _conn and _conn.closed == 0:
        return _conn
    _conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    _conn.autocommit = True
    return _conn

# ====== ساخت جداول ======
def init_db():
    conn = get_conn()
    with conn.cursor() as cur:
        # کاربران
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id               SERIAL PRIMARY KEY,
            telegram_id      BIGINT UNIQUE NOT NULL,
            name             TEXT,
            phone            TEXT,
            address          TEXT,
            wallet_balance   INTEGER NOT NULL DEFAULT 0,   -- تومان
            cashback_total   INTEGER NOT NULL DEFAULT 0,   -- مجموع کش‌بک
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

        # محصولات
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id            SERIAL PRIMARY KEY,
            title         TEXT NOT NULL,
            price         INTEGER NOT NULL,               -- تومان
            photo_url     TEXT,
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

        # سفارش‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id            SERIAL PRIMARY KEY,
            user_id       INTEGER NOT NULL REFERENCES users(id),
            status        TEXT NOT NULL DEFAULT 'draft',  -- draft, submitted, paid, canceled, delivered
            total_amount  INTEGER NOT NULL DEFAULT 0,
            cashback_applied INTEGER NOT NULL DEFAULT 0,
            address       TEXT,
            phone         TEXT,
            note          TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

        # آیتم‌های سفارش
        cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id            SERIAL PRIMARY KEY,
            order_id      INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id    INTEGER NOT NULL REFERENCES products(id),
            qty           INTEGER NOT NULL,
            price         INTEGER NOT NULL                   -- قیمت واحد در لحظه ثبت
        );
        """)

        # شارژهای کیف پول
        cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_topups (
            id            SERIAL PRIMARY KEY,
            user_id       INTEGER NOT NULL REFERENCES users(id),
            amount        INTEGER NOT NULL,
            method        TEXT NOT NULL,                    -- card2card / gateway
            ref           TEXT,                             -- شماره پیگیری (درگاه/رسید)
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

# ====== کاربران ======
def upsert_user(telegram_id: int, name: str):
    """
    اگر کاربر نبود بساز، اگر بود نام را آپدیت کن.
    خروجی: رکورد کاربر (id, telegram_id, name, wallet_balance, cashback_total)
    """
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users(telegram_id, name)
            VALUES (%s, %s)
            ON CONFLICT (telegram_id) DO UPDATE
              SET name = EXCLUDED.name
            RETURNING id, telegram_id, name, wallet_balance, cashback_total;
        """, (int(telegram_id), name))
        return cur.fetchone()

def get_user_by_tid(telegram_id: int):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE telegram_id = %s;", (int(telegram_id),))
        return cur.fetchone()

def update_user_contact(telegram_id: int, phone: str = None, address: str = None, name: str = None):
    sets, vals = [], []
    if phone is not None:
        sets.append("phone=%s"); vals.append(phone)
    if address is not None:
        sets.append("address=%s"); vals.append(address)
    if name is not None:
        sets.append("name=%s"); vals.append(name)
    if not sets:
        return get_user_by_tid(telegram_id)
    vals.append(int(telegram_id))
    sql = f"UPDATE users SET {', '.join(sets)} WHERE telegram_id=%s RETURNING *;"
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(sql, vals)
        return cur.fetchone()

# ====== کیف پول و کش‌بک ======
def get_wallet(telegram_id: int) -> int:
    u = get_user_by_tid(telegram_id)
    return int(u["wallet_balance"]) if u else 0

def add_wallet(telegram_id: int, amount: int):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users
               SET wallet_balance = wallet_balance + %s
             WHERE telegram_id = %s
         RETURNING wallet_balance;
        """, (int(amount), int(telegram_id)))
        row = cur.fetchone()
        return int(row["wallet_balance"]) if row else 0

def add_cashback(telegram_id: int, amount: int):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users
               SET cashback_total = cashback_total + %s,
                   wallet_balance = wallet_balance + %s
             WHERE telegram_id = %s
         RETURNING wallet_balance, cashback_total;
        """, (int(amount), int(amount), int(telegram_id)))
        return cur.fetchone()

def record_topup(telegram_id: int, amount: int, method: str, ref: str = None):
    user = get_user_by_tid(telegram_id)
    if not user:
        raise RuntimeError("user not found")
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO wallet_topups(user_id, amount, method, ref)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """, (user["id"], int(amount), method, ref))
        return cur.fetchone()["id"]

# ====== محصولات ======
def add_product(title: str, price: int, photo_url: str = None, is_active: bool = True):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO products(title, price, photo_url, is_active)
            VALUES (%s, %s, %s, %s)
            RETURNING *;
        """, (title, int(price), photo_url, bool(is_active)))
        return cur.fetchone()

def list_products(only_active: bool = True):
    conn = get_conn()
    with conn.cursor() as cur:
        if only_active:
            cur.execute("SELECT * FROM products WHERE is_active = TRUE ORDER BY id DESC;")
        else:
            cur.execute("SELECT * FROM products ORDER BY id DESC;")
        return cur.fetchall()

def update_product(pid: int, title: str = None, price: int = None, photo_url: str = None, is_active: bool = None):
    sets, vals = [], []
    if title is not None:
        sets.append("title=%s"); vals.append(title)
    if price is not None:
        sets.append("price=%s"); vals.append(int(price))
    if photo_url is not None:
        sets.append("photo_url=%s"); vals.append(photo_url)
    if is_active is not None:
        sets.append("is_active=%s"); vals.append(bool(is_active))
    if not sets:
        return get_product(pid)
    vals.append(int(pid))
    sql = f"UPDATE products SET {', '.join(sets)} WHERE id=%s RETURNING *;"
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(sql, vals)
        return cur.fetchone()

def get_product(pid: int):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id=%s;", (int(pid),))
        return cur.fetchone()

def delete_product(pid: int):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE id=%s;", (int(pid),))
        return cur.rowcount > 0

# ====== سفارش ======
def create_order(telegram_id: int, address: str = None, phone: str = None, note: str = None):
    user = get_user_by_tid(telegram_id)
    if not user:
        raise RuntimeError("user not found")
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO orders(user_id, address, phone, note)
            VALUES (%s, %s, %s, %s)
            RETURNING *;
        """, (user["id"], address, phone, note))
        return cur.fetchone()

def add_item(order_id: int, product_id: int, qty: int):
    p = get_product(product_id)
    if not p or not p["is_active"]:
        raise RuntimeError("product not available")
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO order_items(order_id, product_id, qty, price)
            VALUES (%s, %s, %s, %s)
            RETURNING *;
        """, (int(order_id), int(product_id), int(qty), int(p["price"])))
        _ = cur.fetchone()
        # آپدیت جمع کل
        cur.execute("""
            UPDATE orders o
               SET total_amount = COALESCE((
                    SELECT COALESCE(SUM(qty*price),0)
                      FROM order_items
                     WHERE order_id = o.id
               ),0)
             WHERE id=%s;
        """, (int(order_id),))

def submit_order(order_id: int, cashback_percent: int = 0):
    conn = get_conn()
    with conn.cursor() as cur:
        # وضعیت به submitted
        cur.execute("""
            UPDATE orders SET status='submitted' WHERE id=%s RETURNING total_amount, user_id;
        """, (int(order_id),))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("order not found")
        total = int(row["total_amount"])
        cashback = (total * int(cashback_percent)) // 100 if cashback_percent > 0 else 0

        # اعمال کش‌بک به کیف پول
        if cashback > 0:
            cur.execute("""
                UPDATE users SET
                    wallet_balance = wallet_balance + %s,
                    cashback_total = cashback_total + %s
                WHERE id=%s;
            """, (cashback, cashback, int(row["user_id"])))
            cur.execute("UPDATE orders SET cashback_applied=%s WHERE id=%s;", (cashback, int(order_id)))
        return {"total": total, "cashback": cashback}

def get_order(order_id: int):
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM orders WHERE id=%s;", (int(order_id),))
        order = cur.fetchone()
        if not order:
            return None
        cur.execute("SELECT * FROM order_items WHERE order_id=%s ORDER BY id;", (int(order_id),))
        items = cur.fetchall()
        order["items"] = items
        return order
