# src/db.py
import os, json, decimal
from typing import List, Optional, Dict, Any, Tuple
import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is required")

def get_conn():
    dsn = DATABASE_URL
    if "sslmode=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return psycopg2.connect(dsn, cursor_factory=psycopg2.extras.DictCursor)

def _to_dec(x) -> decimal.Decimal:
    if isinstance(x, decimal.Decimal): return x
    return decimal.Decimal(str(x))

# ---------- Schema & migrations ----------
def init_db() -> None:
    ddl = [
        # users
        """
        CREATE TABLE IF NOT EXISTS users(
          id BIGSERIAL PRIMARY KEY,
          telegram_id BIGINT UNIQUE,
          name TEXT,
          phone TEXT,
          address TEXT,
          wallet_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS name TEXT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance NUMERIC(18,2) NOT NULL DEFAULT 0;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();",
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='idx_users_telegram_id') THEN CREATE UNIQUE INDEX idx_users_telegram_id ON users(telegram_id); END IF; END $$;",

        # products
        """
        CREATE TABLE IF NOT EXISTS products(
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

        # orders
        """
        CREATE TABLE IF NOT EXISTS orders(
          id BIGSERIAL PRIMARY KEY,
          user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          status TEXT NOT NULL DEFAULT 'new',
          total_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
          address TEXT,
          phone TEXT,
          meta JSONB,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,

        # order_items
        """
        CREATE TABLE IF NOT EXISTS order_items(
          id BIGSERIAL PRIMARY KEY,
          order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
          product_id BIGINT NOT NULL REFERENCES products(id),
          qty INT NOT NULL DEFAULT 1,
          unit_price NUMERIC(18,2) NOT NULL
        );
        """,

        # wallet transactions
        """
        CREATE TABLE IF NOT EXISTS wallet_tx(
          id BIGSERIAL PRIMARY KEY,
          user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          amount NUMERIC(18,2) NOT NULL,
          reason TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,

        # settings (cashback)
        """
        CREATE TABLE IF NOT EXISTS settings(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """,
        """
        INSERT INTO settings(key,value)
        VALUES ('cashback_percent', COALESCE(NULLIF(%s,''),'3'))
        ON CONFLICT (key) DO NOTHING;
        """,
    ]
    with get_conn() as conn, conn.cursor() as cur:
        for q in ddl:
            if "%s" in q:
                cur.execute(q, [os.getenv("CASHBACK_PERCENT", "3")])
            else:
                cur.execute(q)
        conn.commit()

# ---------- Users ----------
def upsert_user(telegram_id: int, name: Optional[str] = None) -> Dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users(telegram_id, name)
            VALUES (%s,%s)
            ON CONFLICT(telegram_id) DO UPDATE
              SET name = COALESCE(EXCLUDED.name, users.name),
                  updated_at = NOW()
            RETURNING *;
        """, (telegram_id, name))
        return dict(cur.fetchone())

def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE telegram_id=%s;", (telegram_id,))
        row = cur.fetchone()
        return dict(row) if row else None

def set_user_contact(telegram_id: int, phone: Optional[str], address: Optional[str], name: Optional[str]=None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE users
               SET phone=COALESCE(%s,phone),
                   address=COALESCE(%s,address),
                   name=COALESCE(%s,name),
                   updated_at=NOW()
             WHERE telegram_id=%s;
        """, (phone, address, name, telegram_id))
        conn.commit()

# ---------- Wallet ----------
def get_wallet(telegram_id: int) -> decimal.Decimal:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT wallet_balance FROM users WHERE telegram_id=%s;", (telegram_id,))
        row = cur.fetchone()
        return row["wallet_balance"] if row else decimal.Decimal("0")

def add_wallet(telegram_id: int, amount, reason: str="") -> decimal.Decimal:
    amount = _to_dec(amount)
    with get_conn() as conn, conn.cursor() as cur:
        # ensure user exists
        cur.execute("INSERT INTO users(telegram_id) VALUES (%s) ON CONFLICT DO NOTHING;", (telegram_id,))
        # tx
        cur.execute("INSERT INTO wallet_tx(user_id, amount, reason) SELECT id, %s, %s FROM users WHERE telegram_id=%s;",
                    (amount, reason, telegram_id))
        # apply
        cur.execute("""
            UPDATE users
               SET wallet_balance = wallet_balance + %s,
                   updated_at = NOW()
             WHERE telegram_id=%s
         RETURNING wallet_balance;
        """, (amount, telegram_id))
        bal = cur.fetchone()["wallet_balance"]
        conn.commit()
        return bal

def get_cashback_percent() -> decimal.Decimal:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key='cashback_percent';")
        row = cur.fetchone()
        try:
            return _to_dec(row["value"])
        except Exception:
            return decimal.Decimal("3")

# ---------- Products ----------
def add_product(name: str, price, photo_url: Optional[str]) -> Dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO products(name,price,photo_url,is_active)
            VALUES (%s,%s,%s,TRUE)
            RETURNING *;
        """, (name.strip(), _to_dec(price), photo_url))
        return dict(cur.fetchone())

def list_products(only_active: bool=True) -> List[Dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        if only_active:
            cur.execute("SELECT * FROM products WHERE is_active=TRUE ORDER BY id DESC;")
        else:
            cur.execute("SELECT * FROM products ORDER BY id DESC;")
        return [dict(r) for r in cur.fetchall()]

def get_product_by_name(name: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE name=%s AND is_active=TRUE;", (name.strip(),))
        row = cur.fetchone()
        return dict(row) if row else None

# ---------- Orders ----------
def create_order(telegram_id: int, items: List[Tuple[int,int]],
                 address: Optional[str], phone: Optional[str], use_wallet: bool=False) -> Dict[str, Any]:
    """
    items = [(product_id, qty), ...]
    """
    if not items: raise ValueError("items required")

    with get_conn() as conn, conn.cursor() as cur:
        # ensure user + get ids
        cur.execute("INSERT INTO users(telegram_id) VALUES (%s) ON CONFLICT DO NOTHING;", (telegram_id,))
        cur.execute("SELECT id, wallet_balance FROM users WHERE telegram_id=%s;", (telegram_id,))
        u = cur.fetchone()
        user_id = u["id"]; wallet_bal = _to_dec(u["wallet_balance"])

        # calc total
        total = decimal.Decimal("0")
        priced = []
        for pid, qty in items:
            cur.execute("SELECT price FROM products WHERE id=%s AND is_active=TRUE;", (pid,))
            row = cur.fetchone()
            if not row: raise ValueError(f"product {pid} not found/active")
            price = _to_dec(row["price"])
            priced.append((pid, qty, price))
            total += price * qty

        # wallet usage
        from_wallet = decimal.Decimal("0")
        if use_wallet and wallet_bal > 0:
            from_wallet = min(wallet_bal, total)
        payable = total - from_wallet

        # create order
        cur.execute("""
            INSERT INTO orders(user_id,status,total_amount,address,phone,meta)
            VALUES (%s,'new',%s,%s,%s,%s)
            RETURNING id, created_at;
        """, (user_id, total, address, phone, json.dumps({"use_wallet": bool(use_wallet), "wallet_used": str(from_wallet)})))
        o = cur.fetchone()
        order_id = o["id"]

        # items
        for pid, qty, price in priced:
            cur.execute("""
                INSERT INTO order_items(order_id,product_id,qty,unit_price)
                VALUES (%s,%s,%s,%s);
            """, (order_id, pid, qty, price))

        # apply wallet deduction
        if from_wallet > 0:
            cur.execute("INSERT INTO wallet_tx(user_id,amount,reason) VALUES (%s,%s,%s);",
                        (user_id, -from_wallet, f"پرداخت سفارش #{order_id}"))
            cur.execute("UPDATE users SET wallet_balance = wallet_balance - %s WHERE id=%s;",
                        (from_wallet, user_id))

        # cashback on payable
        cb_percent = get_cashback_percent()
        cashback = (payable * cb_percent / decimal.Decimal("100")).quantize(decimal.Decimal("0.01"))
        if cashback > 0:
            cur.execute("INSERT INTO wallet_tx(user_id,amount,reason) VALUES (%s,%s,%s);",
                        (user_id, cashback, f"کش‌بک {cb_percent}% سفارش #{order_id}"))
            cur.execute("UPDATE users SET wallet_balance = wallet_balance + %s WHERE id=%s;",
                        (cashback, user_id))

        conn.commit()
        return {
            "order_id": order_id,
            "total": str(total),
            "wallet_used": str(from_wallet),
            "payable": str(payable),
            "cashback": str(cashback),
            "created_at": str(o["created_at"]),
        }
