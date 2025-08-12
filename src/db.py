import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from .base import DATABASE_URL, log

@contextmanager
def _conn():
    con = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield con
        con.commit()
    finally:
        con.close()

def _exec(sql: str, params=None, fetch: str | None = None):
    with _conn() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()

# ---------- bootstrap (بدون استارتاپ DDL حجیم) ----------
def init_db():
    # users
    _exec("""
    CREATE TABLE IF NOT EXISTS users(
        user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        telegram_id BIGINT NOT NULL,
        name TEXT,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT
