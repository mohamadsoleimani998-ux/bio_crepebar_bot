import os
import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL")

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing")
    # Neon و بسیاری از سرویس‌های PG به sslmode نیاز دارند
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    """ایجاد جداول پایه (idempotent)."""
    with _conn() as cn, cn.cursor() as cur:
        # جدول کاربران: id داخلی، tg_id از تلگرام
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            tg_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name  TEXT,
            wallet_cents INTEGER NOT NULL DEFAULT 0,
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        # محصولات
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price_cents INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        # سفارش‌ها (ساده)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            qty INTEGER NOT NULL DEFAULT 1,
            total_cents INTEGER NOT NULL,
            cashback_cents INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        # تراکنش‌های کیف پول (لاگ)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_txns (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount_cents INTEGER NOT NULL,  -- + و -
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        # تنظیمات ساده (برای کش‌بک)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        cn.commit()
    print("DB init OK")

# ---------------- users ----------------
def get_or_create_user(tg_id, first_name=None, last_name=None, username=None):
    """بر اساس tg_id کاربر را برمی‌گرداند یا می‌سازد. خروجی: dict شامل فیلد id (داخلی DB)."""
    with _conn() as cn, cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s;", (tg_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        cur.execute("""
            INSERT INTO users (tg_id, username, first_name, last_name)
            VALUES (%s, %s, %s, %s)
            RETURNING id, tg_id, wallet_cents, is_admin;
        """, (tg_id, username, first_name, last_name))
        return dict(cur.fetchone())

def get_wallet(user_id: int) -> int:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT wallet_cents FROM users WHERE id=%s;", (user_id,))
        row = cur.fetchone()
        return int(row[0]) if row else 0

def adjust_wallet(user_id: int, delta_cents: int) -> int:
    """تغییر موجودی کیف پول و برگرداندن موجودی جدید."""
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            UPDATE users SET wallet_cents = wallet_cents + %s
            WHERE id=%s
            RETURNING wallet_cents;
        """, (delta_cents, user_id))
        row = cur.fetchone()
        return int(row[0]) if row else 0

# ---------------- products ----------------
def add_product(name: str, price_cents: int) -> int:
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("INSERT INTO products (name, price_cents) VALUES (%s, %s) RETURNING id;", (name, price_cents))
        (pid,) = cur.fetchone()
        return pid

def list_products() -> list[dict]:
    with _conn() as cn, cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, name, price_cents FROM products WHERE is_active=TRUE ORDER BY id;")
        rows = cur.fetchall() or []
        return [dict(r) for r in rows]

def get_product(product_id: int) -> dict | None:
    with _conn() as cn, cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, name, price_cents FROM products WHERE id=%s AND is_active=TRUE;", (product_id,))
        row = cur.fetchone()
        return dict(row) if row else None

# ---------------- settings (cashback) ----------------
def get_cashback_percent() -> int:
    v = os.getenv("CASHBACK_PERCENT")
    if v and v.strip().isdigit():
        return int(v.strip())
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key='cashback_percent';")
        row = cur.fetchone()
        if row and str(row[0]).isdigit():
            return int(row[0])
    return 0

def set_cashback_percent(p: int) -> None:
    p = int(p)
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO settings(key, value) VALUES ('cashback_percent', %s)
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value;
        """, (str(p),))
        cn.commit()

# ---------------- orders + cashback ----------------
def create_order_with_cashback(user_id: int, product_id: int, qty: int) -> dict:
    """ثبت سفارش ساده و اعمال کش‌بک روی کیف پول. خروجی: جزییات سفارش برای نمایش."""
    qty = max(1, int(qty))
    prod = get_product(product_id)
    if not prod:
        raise ValueError("محصول یافت نشد.")

    total = int(prod["price_cents"]) * qty
    cb_percent = get_cashback_percent()
    cashback = (total * cb_percent) // 100 if cb_percent > 0 else 0

    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
            INSERT INTO orders (user_id, product_id, qty, total_cents, cashback_cents)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
        """, (user_id, product_id, qty, total, cashback))
        (order_id,) = cur.fetchone()

        if cashback > 0:
            # افزایش کیف پول
            cur.execute("UPDATE users SET wallet_cents = wallet_cents + %s WHERE id=%s;", (cashback, user_id))
            # لاگ تراکنش
            cur.execute("""
                INSERT INTO wallet_txns (user_id, amount_cents, reason)
                VALUES (%s, %s, %s);
            """, (user_id, cashback, f"cashback order #{order_id}"))

        cn.commit()

    return {
        "order_id": order_id,
        "total_cents": total,
        "cashback_cents": cashback,
        "product": prod,
        "qty": qty,
    }
