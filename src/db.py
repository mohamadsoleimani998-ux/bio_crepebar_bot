# src/db.py
import os
import json
import decimal
from typing import List, Optional, Dict, Any, Tuple

import psycopg2
import psycopg2.extras

# -----------------------------
# اتصال به دیتابیس (Neon / Render)
# -----------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is required")

def get_conn():
    # Neon نیاز به SSL دارد؛ اگر در URL نبود، اجبارش می‌کنیم
    if "sslmode=" not in DATABASE_URL:
        dsn = DATABASE_URL + ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"
    else:
        dsn = DATABASE_URL
    return psycopg2.connect(dsn, cursor_factory=psycopg2.extras.DictCursor)


# -----------------------------
# راه‌اندازی/مهاجرت اسکیمـا
# -----------------------------
def init_db() -> None:
    ddl = [
        # کاربران
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            name TEXT,
            phone TEXT,
            address TEXT,
            wallet_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
            total_spent NUMERIC(18,2) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        # اگر users از قبل بود ولی ستون‌ها نبودند، اضافه کن
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS name TEXT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance NUMERIC(18,2) NOT NULL DEFAULT 0;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS total_spent NUMERIC(18,2) NOT NULL DEFAULT 0;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='idx_users_telegram_id') THEN CREATE UNIQUE INDEX idx_users_telegram_id ON users(telegram_id); END IF; END $$;",
        # محصولات
        """
        CREATE TABLE IF NOT EXISTS products (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price NUMERIC(18,2) NOT NULL,
            photo_url TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS photo_url TEXT;",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;",
        # سفارش‌ها
        """
        CREATE TABLE IF NOT EXISTS orders (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'new', -- new, paid, preparing, sent, done, cancelled
            total_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
            address TEXT,
            phone TEXT,
            meta JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        # آیتم‌های سفارش
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id BIGSERIAL PRIMARY KEY,
            order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id BIGINT NOT NULL REFERENCES products(id),
            qty INT NOT NULL DEFAULT 1,
            unit_price NUMERIC(18,2) NOT NULL
        );
        """,
        # تراکنش‌های کیف پول
        """
        CREATE TABLE IF NOT EXISTS wallet_tx (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount NUMERIC(18,2) NOT NULL, -- + شارژ / - برداشت
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        # تنظیمات (مثلاً درصد کش‌بک)
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """,
        # اگر کش‌بک تعریف نشده بود، از محیط بگیر یا 3 درصد
        """
        INSERT INTO settings(key, value)
        VALUES ('cashback_percent', COALESCE(NULLIF(%s,''),'3'))
        ON CONFLICT (key) DO NOTHING;
        """,
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            for i, q in enumerate(ddl):
                if "%s" in q:
                    cur.execute(q, [os.getenv("CASHBACK_PERCENT", "3")])
                else:
                    cur.execute(q)
        conn.commit()


# -----------------------------
# کمک‌ها
# -----------------------------
def _row_to_dict(row) -> Dict[str, Any]:
    return dict(row) if row else {}

def _to_decimal(v) -> decimal.Decimal:
    if isinstance(v, decimal.Decimal):
        return v
    return decimal.Decimal(str(v))


# -----------------------------
# کاربران
# -----------------------------
def upsert_user(telegram_id: int, name: Optional[str] = None) -> Dict[str, Any]:
    """
    اگر کاربر نبود می‌سازد؛ اگر بود، فقط name را به‌روزرسانی می‌کند.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (telegram_id, name)
            VALUES (%s, %s)
            ON CONFLICT (telegram_id) DO UPDATE
            SET name = COALESCE(EXCLUDED.name, users.name),
                updated_at = NOW()
            RETURNING *;
            """,
            (telegram_id, name),
        )
        row = cur.fetchone()
        return _row_to_dict(row)

def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE telegram_id=%s;", (telegram_id,))
        return _row_to_dict(cur.fetchone())

def set_user_contact(telegram_id: int, phone: Optional[str], address: Optional[str]) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET phone = COALESCE(%s, phone),
                address = COALESCE(%s, address),
                updated_at = NOW()
            WHERE telegram_id=%s;
            """,
            (phone, address, telegram_id),
        )

def get_wallet(telegram_id: int) -> decimal.Decimal:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT wallet_balance FROM users WHERE telegram_id=%s;", (telegram_id,))
        row = cur.fetchone()
        return row["wallet_balance"] if row else decimal.Decimal("0.00")

def add_wallet(telegram_id: int, amount: decimal.Decimal, reason: str = "") -> decimal.Decimal:
    amount = _to_decimal(amount)
    with get_conn() as conn, conn.cursor() as cur:
        # ایجاد کاربر اگر نبود
        cur.execute(
            """
            INSERT INTO users(telegram_id)
            VALUES (%s) ON CONFLICT (telegram_id) DO NOTHING;
            """,
            (telegram_id,),
        )
        # تراکنش
        cur.execute(
            """
            INSERT INTO wallet_tx(user_id, amount, reason)
            SELECT id, %s, %s FROM users WHERE telegram_id=%s;
            """,
            (amount, reason, telegram_id),
        )
        # بروزرسانی موجودی
        cur.execute(
            """
            UPDATE users
            SET wallet_balance = wallet_balance + %s,
                updated_at = NOW()
            WHERE telegram_id=%s
            RETURNING wallet_balance;
            """,
            (amount, telegram_id),
        )
        return cur.fetchone()["wallet_balance"]


# -----------------------------
# تنظیمات (کش‌بک)
# -----------------------------
def get_cashback_percent() -> decimal.Decimal:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key='cashback_percent';")
        row = cur.fetchone()
        try:
            return _to_decimal(row["value"])
        except Exception:
            return decimal.Decimal("3")

def set_cashback_percent(p: decimal.Decimal) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO settings(key, value)
            VALUES ('cashback_percent', %s)
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value;
            """,
            (str(_to_decimal(p)),),
        )


# -----------------------------
# محصولات (منو)
# -----------------------------
def add_product(name: str, price: decimal.Decimal, photo_url: Optional[str] = None, is_active: bool = True) -> Dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO products(name, price, photo_url, is_active)
            VALUES (%s, %s, %s, %s)
            RETURNING *;
            """,
            (name, _to_decimal(price), photo_url, is_active),
        )
        return _row_to_dict(cur.fetchone())

def update_product(product_id: int, name: Optional[str] = None,
                   price: Optional[decimal.Decimal] = None,
                   photo_url: Optional[str] = None,
                   is_active: Optional[bool] = None) -> Dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE products
            SET name = COALESCE(%s, name),
                price = COALESCE(%s, price),
                photo_url = COALESCE(%s, photo_url),
                is_active = COALESCE(%s, is_active),
                updated_at = NOW()
            WHERE id=%s
            RETURNING *;
            """,
            (name, _to_decimal(price) if price is not None else None, photo_url, is_active, product_id),
        )
        return _row_to_dict(cur.fetchone())

def list_products(only_active: bool = True) -> List[Dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        if only_active:
            cur.execute("SELECT * FROM products WHERE is_active=TRUE ORDER BY id;")
        else:
            cur.execute("SELECT * FROM products ORDER BY id;")
        return [dict(r) for r in cur.fetchall()]

def get_product(product_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id=%s;", (product_id,))
        return _row_to_dict(cur.fetchone())


# -----------------------------
# سفارش
# -----------------------------
def create_order(telegram_id: int,
                 items: List[Tuple[int, int]],
                 address: Optional[str] = None,
                 phone: Optional[str] = None,
                 use_wallet: bool = False) -> Dict[str, Any]:
    """
    items: list of (product_id, qty)
    """
    if not items:
        raise ValueError("Items required")

    with get_conn() as conn:
        cur = conn.cursor()
        # اطمینان از وجود کاربر
        cur.execute("INSERT INTO users(telegram_id) VALUES (%s) ON CONFLICT DO NOTHING;", (telegram_id,))
        # گرفتن id کاربر
        cur.execute("SELECT id, wallet_balance FROM users WHERE telegram_id=%s;", (telegram_id,))
        u = cur.fetchone()
        user_id = u["id"]
        wallet_balance = _to_decimal(u["wallet_balance"])

        # محاسبه مبلغ
        total = decimal.Decimal("0")
        priced_items = []
        for pid, qty in items:
            cur.execute("SELECT price FROM products WHERE id=%s AND is_active=TRUE;", (pid,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Product {pid} not found/active")
            price = _to_decimal(row["price"])
            total += price * qty
            priced_items.append((pid, qty, price))

        # استفاده از کیف پول
        pay_from_wallet = decimal.Decimal("0")
        if use_wallet and wallet_balance > 0:
            pay_from_wallet = min(wallet_balance, total)

        order_total_after_wallet = total - pay_from_wallet

        # ایجاد سفارش
        cur.execute(
            """
            INSERT INTO orders(user_id, status, total_amount, address, phone, meta)
            VALUES (%s, 'new', %s, COALESCE(%s,''), COALESCE(%s,''), %s)
            RETURNING id, created_at;
            """,
            (user_id, total, address, phone, json.dumps({"use_wallet": bool(use_wallet), "wallet_used": str(pay_from_wallet)})),
        )
        order = cur.fetchone()
        order_id = order["id"]

        # آیتم‌ها
        for pid, qty, price in priced_items:
            cur.execute(
                """
                INSERT INTO order_items(order_id, product_id, qty, unit_price)
                VALUES (%s, %s, %s, %s);
                """,
                (order_id, pid, qty, price),
            )

        # کسر از کیف پول در صورت استفاده
        if pay_from_wallet > 0:
            cur.execute(
                """
                INSERT INTO wallet_tx(user_id, amount, reason)
                VALUES (%s, %s, %s);
                """,
                (user_id, -pay_from_wallet, f"پرداخت سفارش #{order_id}"),
            )
            cur.execute(
                "UPDATE users SET wallet_balance = wallet_balance - %s WHERE id=%s;",
                (pay_from_wallet, user_id),
            )

        # بروزرسانی مجموع هزینه کاربر
        cur.execute(
            "UPDATE users SET total_spent = total_spent + %s, updated_at=NOW() WHERE id=%s;",
            (order_total_after_wallet, user_id),
        )

        # اعمال کش‌بک روی مبلغ پرداختی واقعی (بعد از کیف پول)
        cur.execute("SELECT value FROM settings WHERE key='cashback_percent';")
        row = cur.fetchone()
        cb_percent = _to_decimal(row["value"]) if row else decimal.Decimal("3")
        cashback = (order_total_after_wallet * cb_percent / decimal.Decimal("100")).quantize(decimal.Decimal("0.01"))
        if cashback > 0:
            cur.execute(
                "INSERT INTO wallet_tx(user_id, amount, reason) VALUES (%s, %s, %s);",
                (user_id, cashback, f"کش‌بک سفارش #{order_id} ({cb_percent}%)"),
            )
            cur.execute(
                "UPDATE users SET wallet_balance = wallet_balance + %s WHERE id=%s;",
                (cashback, user_id),
            )

        conn.commit()

        return {
            "order_id": order_id,
            "total": str(total),
            "wallet_used": str(pay_from_wallet),
            "payable": str(order_total_after_wallet),
            "cashback": str(cashback),
            "created_at": str(order["created_at"]),
        }


# -----------------------------
# ابزار ادمین (ساده)
# -----------------------------
def admin_list_users(limit: int = 50) -> List[Dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users ORDER BY id DESC LIMIT %s;", (limit,))
        return [dict(r) for r in cur.fetchall()]

def admin_list_orders(limit: int = 50) -> List[Dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT o.*, u.telegram_id
            FROM orders o
            JOIN users u ON u.id = o.user_id
            ORDER BY o.id DESC
            LIMIT %s;
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
