# src/db.py
import os
import psycopg2

DDL_SQL = """
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  tg_id BIGINT UNIQUE NOT NULL,
  first_name TEXT,
  last_name  TEXT,
  username   TEXT,
  wallet_balance NUMERIC(12,2) DEFAULT 0,
  cashback_percent INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS products (
  id BIGSERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  price NUMERIC(12,2) NOT NULL,
  photo_file_id TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  created_by BIGINT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS orders (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  total_amount NUMERIC(12,2) NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS order_items (
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id BIGINT NOT NULL REFERENCES products(id),
  quantity INTEGER NOT NULL DEFAULT 1,
  unit_price NUMERIC(12,2) NOT NULL
);
CREATE TABLE IF NOT EXISTS wallet_transactions (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount NUMERIC(12,2) NOT NULL,
  kind   TEXT NOT NULL,
  note   TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_users_tg_id     ON users(tg_id);
CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_wtx_user_time   ON wallet_transactions(user_id, created_at);
"""

def init_db():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set; skipping DB init", flush=True)
        return
    try:
        conn = psycopg2.connect(url)  # در Neon معمولاً sslmode=require داخل URL هست
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(DDL_SQL)
        conn.close()
        print("DB init OK", flush=True)
    except Exception as e:
        print("DB init error:", e, flush=True)
