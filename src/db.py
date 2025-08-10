import os
from typing import Optional, Dict, Any

import psycopg2
import psycopg2.extras

# اگر base.py داری که اتصال می‌دهد، از آن استفاده می‌کنیم
try:
    from .base import get_conn  # type: ignore
except Exception:
    # اگر نبود، این fallback کار می‌کند
    def get_conn():
        url = os.environ["DATABASE_URL"]
        return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    """ساخت جداول در صورت نبودن‌شان (idempotent)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
          tg_id BIGINT PRIMARY KEY,
          first_name TEXT,
          last_name  TEXT,
          username   TEXT,
          wallet_cents INTEGER NOT NULL DEFAULT 0,
          is_admin  BOOLEAN NOT NULL DEFAULT FALSE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
          id SERIAL PRIMARY KEY,
          title TEXT NOT NULL,
          price_cents INTEGER NOT NULL,
          caption TEXT,
          photo_file_id TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)
        conn.commit()


def set_admins():
    """ADMIN_IDS را به‌صورت comma-separated می‌خواند و فلگ ادمین را ست می‌کند."""
    admins = os.getenv("ADMIN_IDS", "").strip()
    if not admins:
        return
    ids = [int(x) for x in admins.replace(" ", "").split(",") if x]
    if not ids:
        return

    with get_conn() as conn, conn.cursor() as cur:
        for tg_id in ids:
            # اگر نبود، بساز؛ اگر بود، فقط is_admin را True کن
            cur.execute("""
                INSERT INTO users (tg_id, is_admin)
                VALUES (%s, TRUE)
                ON CONFLICT (tg_id) DO UPDATE SET is_admin = EXCLUDED.is_admin;
            """, (tg_id,))
        conn.commit()


def get_or_create_user(tg_user: Dict[str, Any]) -> Dict[str, Any]:
    """
    کاربر را بر اساس tg_id برمی‌گرداند؛ اگر نبود می‌سازد.
    tg_user باید شامل id, first_name, last_name, username باشد (ممکن است برخی نباشند).
    """
    tg_id = int(tg_user.get("id"))
    first = tg_user.get("first_name")
    last = tg_user.get("last_name")
    uname = tg_user.get("username")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s", (tg_id,))
        row = cur.fetchone()
        if row:
            return dict(row)

        # ایجاد کاربر جدید
        cur.execute("""
            INSERT INTO users (tg_id, first_name, last_name, username)
            VALUES (%s, %s, %s, %s)
            RETURNING tg_id, wallet_cents, is_admin;
        """, (tg_id, first, last, uname))
        row = cur.fetchone()
        conn.commit()
        return dict(row)


def get_wallet(tg_id: int) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s", (tg_id,))
        row = cur.fetchone()
        return int(row["wallet_cents"]) if row else 0


def list_products():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, title, price_cents, caption, photo_file_id
            FROM products
            ORDER BY id DESC
            LIMIT 50;
        """)
        return [dict(r) for r in cur.fetchall()]


def add_product(title: str, price_cents: int, caption: Optional[str], photo_file_id: Optional[str]):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO products (title, price_cents, caption, photo_file_id)
            VALUES (%s, %s, %s, %s);
        """, (title, price_cents, caption, photo_file_id))
        conn.commit()
