import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ["DATABASE_URL"]

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    tg_id BIGINT PRIMARY KEY,
                    wallet_cents INT NOT NULL DEFAULT 0,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE
                );
            """)
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tg_id BIGINT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_cents INT NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;")
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes
                        WHERE tablename = 'users' AND indexname = 'users_tg_id_uq'
                    ) THEN
                        CREATE UNIQUE INDEX users_tg_id_uq ON users(tg_id);
                    END IF;
                END $$;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    price_cents INT NOT NULL,
                    caption TEXT,
                    photo_file_id TEXT
                );
            """)

def get_or_create_user(tg_id: int):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s;",
                (tg_id,),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO users (tg_id) VALUES (%s) ON CONFLICT (tg_id) DO NOTHING;",
                    (tg_id,),
                )
                cur.execute(
                    "SELECT tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s;",
                    (tg_id,),
                )
                row = cur.fetchone()
            return row

def get_wallet(tg_id: int) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s;", (tg_id,))
            r = cur.fetchone()
            return int(r[0]) if r else 0

def list_products():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, title, price_cents, caption, photo_file_id
                FROM products
                ORDER BY id DESC;
            """)
            return cur.fetchall()

def add_product(title: str, price_cents: int, caption: str | None, photo_file_id: str | None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO products (title, price_cents, caption, photo_file_id)
                VALUES (%s, %s, %s, %s);
                """,
                (title, price_cents, caption, photo_file_id),
            )

# تابعی که هندلر انتظار دارد
def set_admins(admin_ids: list[int]):
    """کاربرانی که در لیست هستند را ادمین می‌کند، بقیه را غیر ادمین."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            # همه را غیر ادمین کن
            cur.execute("UPDATE users SET is_admin=FALSE;")
            # این‌ها را ادمین کن
            for tg_id in admin_ids:
                cur.execute("""
                    INSERT INTO users (tg_id, is_admin)
                    VALUES (%s, TRUE)
                    ON CONFLICT (tg_id) DO UPDATE SET is_admin=TRUE;
                """, (tg_id,))
