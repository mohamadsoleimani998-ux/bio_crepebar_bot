# src/base.py
import os
import json
import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
import anyio

TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{TOKEN}"
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ---------- Telegram helpers ----------
async def tg_send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{BASE_URL}/sendMessage", data=payload)
        r.raise_for_status()

async def tg_send_photo(chat_id: int, file_id: str, caption: str = "", reply_markup: dict | None = None):
    data = {"chat_id": chat_id, "photo": file_id}
    if caption:
        data["caption"] = caption
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{BASE_URL}/sendPhoto", data=data)
        r.raise_for_status()

# ---------- DB helpers ----------
def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def _ensure_schema_sync():
    with _conn() as cn, cn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
          id SERIAL PRIMARY KEY,
          name TEXT NOT NULL,
          price BIGINT NOT NULL,
          description TEXT DEFAULT '',
          photo_file_id TEXT
        );
        CREATE TABLE IF NOT EXISTS users_wallet (
          user_id BIGINT PRIMARY KEY,
          balance BIGINT NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS wallet_tx (
          id SERIAL PRIMARY KEY,
          user_id BIGINT NOT NULL,
          amount BIGINT NOT NULL,
          note TEXT DEFAULT '',
          created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        cn.commit()

async def ensure_schema():
    await anyio.to_thread.run_sync(_ensure_schema_sync)

def _fetchall_sync(sql: str, params: tuple = ()):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()

def _exec_sync(sql: str, params: tuple = ()):
    with _conn() as cn, cn.cursor() as cur:
        cur.execute(sql, params)
        cn.commit()

async def db_fetchall(sql: str, params: tuple = ()):
    return await anyio.to_thread.run_sync(_fetchall_sync, sql, params)

async def db_exec(sql: str, params: tuple = ()):
    await anyio.to_thread.run_sync(_exec_sync, sql, params)

# ---------- Product ops ----------
async def add_product(name: str, price: int, description: str, photo_file_id: str | None):
    await db_exec(
        "INSERT INTO products(name, price, description, photo_file_id) VALUES (%s,%s,%s,%s)",
        (name, price, description, photo_file_id)
    )

async def list_products(limit: int = 10):
    return await db_fetchall("SELECT id, name, price, description, photo_file_id FROM products ORDER BY id DESC LIMIT %s", (limit,))

# ---------- Wallet ops ----------
async def wallet_get(user_id: int) -> int:
    rows = await db_fetchall("SELECT balance FROM users_wallet WHERE user_id=%s", (user_id,))
    if not rows:
        await db_exec("INSERT INTO users_wallet(user_id, balance) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        return 0
    return int(rows[0]["balance"])

async def wallet_add(user_id: int, amount: int, note: str = ""):
    await db_exec("INSERT INTO users_wallet(user_id, balance) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
    await db_exec("UPDATE users_wallet SET balance = balance + %s WHERE user_id=%s", (amount, user_id))
    await db_exec("INSERT INTO wallet_tx(user_id, amount, note) VALUES (%s,%s,%s)", (user_id, amount, note))
