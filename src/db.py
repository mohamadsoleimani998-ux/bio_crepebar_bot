import os
import psycopg2
import psycopg2.extras

# ===== Connection helpers =====
def _get_conn():
    """
    Connect to Postgres using DATABASE_URL.
    Neon usually needs sslmode=require; add if missing.
    """
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    if dsn and "sslmode=" not in dsn:
        if "?" in dsn:
            dsn += "&sslmode=require"
        else:
            dsn += "?sslmode=require"
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(dsn)


def _fetchone_dict(cur):
    row = cur.fetchone()
    return dict(row) if row else None


def _fetchall_dict(cur):
    rows = cur.fetchall()
    return [dict(r) for r in rows]


# ===== Schema bootstrapping =====
def init_db():
    """
    Create tables if not exists and ensure required columns exist.
    Safe/no-op if already present.
    """
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            # users table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    tg_id TEXT UNIQUE NOT NULL,
                    first_name TEXT,
                    last_name  TEXT,
                    username   TEXT,
                    wallet_cents BIGINT NOT NULL DEFAULT 0,
                    is_admin   BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            # Make sure columns exist (idempotent)
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tg_id TEXT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name  TEXT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username   TEXT;")
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_cents BIGINT NOT NULL DEFAULT 0;"
            )
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;"
            )
            # Ensure uniqueness of tg_id if constraint not present
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conrelid = 'users'::regclass
                          AND contype = 'u'
                          AND conname = 'users_tg_id_key'
                    ) THEN
                        ALTER TABLE users ADD CONSTRAINT users_tg_id_key UNIQUE (tg_id);
                    END IF;
                END$$;
                """
            )

            # products table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    price_cents BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS name TEXT;")
            cur.execute(
                "ALTER TABLE products ADD COLUMN IF NOT EXISTS price_cents BIGINT;"
            )
        print("DB init OK")
    finally:
        conn.close()


# ===== Users =====
def get_or_create_user(tg_id: str, first_name=None, last_name=None, username=None):
    """
    Returns dict: {'id': ..., 'tg_id': ..., 'wallet_cents': ..., 'is_admin': ...}
    Creates user if not exists (idempotent).
    """
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Try fetch
            cur.execute(
                "SELECT id, tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s",
                (tg_id,),
            )
            row = _fetchone_dict(cur)
            if row:
                return row

            # Insert new user
            cur.execute(
                """
                INSERT INTO users (tg_id, first_name, last_name, username)
                VALUES (%s, %s, %s, %s)
                RETURNING id, tg_id, wallet_cents, is_admin
                """,
                (tg_id, first_name, last_name, username),
            )
            return _fetchone_dict(cur)
    finally:
        conn.close()


def get_wallet(user_id: int) -> int:
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT wallet_cents FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    finally:
        conn.close()


def set_admins(tg_ids):
    """
    Set is_admin = TRUE for given tg_ids list (strings/ints).
    Does not forcibly demote others (safe).
    """
    if not tg_ids:
        return
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            for tg in tg_ids:
                cur.execute(
                    "UPDATE users SET is_admin=TRUE WHERE tg_id=%s",
                    (str(tg),),
                )
    finally:
        conn.close()


# ===== Products =====
def list_products():
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name, price_cents FROM products ORDER BY id DESC LIMIT 100"
            )
            return _fetchall_dict(cur)
    finally:
        conn.close()


def add_product(name: str, price_cents: int):
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO products (name, price_cents) VALUES (%s, %s)",
                (name, int(price_cents)),
            )
    finally:
        conn.close()
