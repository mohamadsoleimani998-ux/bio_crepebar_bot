import os
import psycopg2
import psycopg2.extras

_CONN = None

def _get_conn():
    """single connection with ssl, reused"""
    global _conn
    if '_conn' not in globals() or globals().get('_conn') is None:
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set")
        # force ssl
        if "sslmode" not in dsn:
            if "?" in dsn:
                dsn = dsn + "&sslmode=require"
            else:
                dsn = dsn + "?sslmode=require"
        globals()['_conn'] = psycopg2.connect(dsn)
        globals()['_conn'].autocommit = True
    return globals()['_conn']

def init_db():
    """create/align schema; safe to call multiple times"""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        # users
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id        BIGINT PRIMARY KEY,
                wallet_cents INTEGER NOT NULL DEFAULT 0,
                is_admin     BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)
        # columns safety (in case table existed with different shape)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_cents INTEGER NOT NULL DEFAULT 0;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;")
        # products
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                photo_file_id TEXT
            );
        """)
        print("DB schema ok")
    except Exception as e:
        # do not crash startup
        print("init_db error:", e)

def get_or_create_user(tg_id: int):
    """returns dict: {tg_id, wallet_cents, is_admin}"""
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT tg_id, wallet_cents, is_admin FROM users WHERE tg_id=%s;", (tg_id,))
            row = cur.fetchone()
            if row:
                return {"tg_id": row["tg_id"], "wallet_cents": row["wallet_cents"], "is_admin": row["is_admin"]}
            cur.execute("INSERT INTO users (tg_id) VALUES (%s) RETURNING tg_id, wallet_cents, is_admin;", (tg_id,))
            row = cur.fetchone()
            return {"tg_id": row["tg_id"], "wallet_cents": row["wallet_cents"], "is_admin": row["is_admin"]}
    except Exception as e:
        print("get_or_create_user err:", e)
        # keep bot alive
        return {"tg_id": tg_id, "wallet_cents": 0, "is_admin": False}

def get_wallet(tg_id: int) -> int:
    """returns wallet cents; 0 on error"""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT wallet_cents FROM users WHERE tg_id=%s;", (tg_id,))
            r = cur.fetchone()
            return r[0] if r else 0
    except Exception as e:
        print("get_wallet err:", e)
        return 0

def list_products():
    """list of dicts"""
    try:
        conn = _get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, name, price_cents, photo_file_id FROM products ORDER BY id DESC;")
            rows = cur.fetchall()
            return [
                {"id": r["id"], "name": r["name"], "price_cents": r["price_cents"], "photo_file_id": r["photo_file_id"]}
                for r in rows
            ]
    except Exception as e:
        print("list_products err:", e)
        return []

def add_product(name: str, price_cents: int, photo_file_id: str | None):
    """insert product; returns id or None"""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO products (name, price_cents, photo_file_id) VALUES (%s,%s,%s) RETURNING id;",
                (name, price_cents, photo_file_id),
            )
            r = cur.fetchone()
            return r[0] if r else None
    except Exception as e:
        print("add_product err:", e)
        return None
