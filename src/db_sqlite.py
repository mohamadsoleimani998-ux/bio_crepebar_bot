import os
import sqlite3
from contextlib import contextmanager
from typing import Optional, Tuple, List, Dict

from .base import log, CASHBACK_PERCENT

DB_PATH = os.environ.get("SQLITE_PATH", "data/db.sqlite3")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

@contextmanager
def _conn():
    cn = sqlite3.connect(DB_PATH)
    cn.row_factory = sqlite3.Row
    try:
        yield cn
        cn.commit()
    finally:
        cn.close()

# ---------- Schema ----------
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users(
  user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id INTEGER UNIQUE NOT NULL,
  name        TEXT,
  balance     INTEGER NOT NULL DEFAULT 0, -- به تومان
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings(
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO settings(key,value) VALUES('cashback_percent', ?);

CREATE TABLE IF NOT EXISTS categories(
  category_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products(
  product_id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES categories(category_id) ON DELETE CASCADE,
  name  TEXT NOT NULL,
  price INTEGER NOT NULL, -- تومان
  is_active INTEGER NOT NULL DEFAULT 1,
  UNIQUE(category_id, name)
);

CREATE TABLE IF NOT EXISTS orders(
  order_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id  INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  status   TEXT NOT NULL DEFAULT 'draft', -- draft|submitted|paid|canceled|fulfilled
  total_amount INTEGER NOT NULL DEFAULT 0,
  cashback_amount INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items(
  item_id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(product_id),
  qty INTEGER NOT NULL DEFAULT 1,
  unit_price INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_order_items_order ON order_items(order_id);

CREATE TABLE IF NOT EXISTS wallet_transactions(
  tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  kind TEXT NOT NULL,  -- topup|order|refund|cashback|adjust
  amount INTEGER NOT NULL, -- + افزایش - کاهش (تومان)
  meta TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
"""

def init_db():
    log.info("init_db() on SQLite: %s", DB_PATH)
    with _conn() as cn:
        cn.execute("PRAGMA journal_mode=WAL;")
        cn.executescript(SCHEMA, )
        cn.execute("UPDATE settings SET value=? WHERE key='cashback_percent'", (str(CASHBACK_PERCENT),))
    seed_categories()
    log.info("init_db() done.")

def seed_categories():
    names = [
        "اسپرسو بار گرم و سرد",
        "چای و دمنوش",
        "ترکیبی گرم",
        "موکتل ها",
        "اسمونی ها",
        "خنک",
        "دمی",
        "کرپ",
        "پنکیک",
        "رژیمی ها",
        "ماچا بار",
    ]
    with _conn() as cn:
        for n in names:
            cn.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (n,))

# ---------- Users ----------
def upsert_user(tg_id: int, name: str):
    with _conn() as cn:
        cur = cn.execute("SELECT user_id FROM users WHERE telegram_id=?", (tg_id,))
        row = cur.fetchone()
        if row:
            cn.execute("UPDATE users SET name=? WHERE user_id=?", (name, row["user_id"]))
            return row["user_id"]
        cur = cn.execute("INSERT INTO users(telegram_id,name) VALUES(?,?)", (tg_id, name))
        return cur.lastrowid

def get_user_by_tg(tg_id: int) -> Optional[sqlite3.Row]:
    with _conn() as cn:
        cur = cn.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,))
        return cur.fetchone()

def change_balance(user_id: int, delta: int, kind: str, meta: str = ""):
    with _conn() as cn:
        cn.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (delta, user_id))
        cn.execute("INSERT INTO wallet_transactions(user_id,kind,amount,meta) VALUES(?,?,?,?)",
                   (user_id, kind, delta, meta))

# ---------- Catalog ----------
def list_categories() -> List[sqlite3.Row]:
    with _conn() as cn:
        return list(cn.execute("SELECT * FROM categories ORDER BY category_id"))

def add_product(category_id: int, name: str, price: int) -> int:
    with _conn() as cn:
        cur = cn.execute("""INSERT INTO products(category_id,name,price) VALUES(?,?,?)""",
                         (category_id, name, price))
        return cur.lastrowid

def list_products(category_id: int) -> List[sqlite3.Row]:
    with _conn() as cn:
        return list(cn.execute("""SELECT * FROM products
                                  WHERE category_id=? AND is_active=1
                                  ORDER BY product_id DESC""", (category_id,)))

def get_product(product_id: int) -> Optional[sqlite3.Row]:
    with _conn() as cn:
        cur = cn.execute("SELECT * FROM products WHERE product_id=? AND is_active=1", (product_id,))
        return cur.fetchone()

# ---------- Orders ----------
def open_draft_order(user_id: int) -> int:
    with _conn() as cn:
        cur = cn.execute("SELECT order_id FROM orders WHERE user_id=? AND status='draft'", (user_id,))
        row = cur.fetchone()
        if row:
            return row["order_id"]
        cur = cn.execute("INSERT INTO orders(user_id,status) VALUES(?, 'draft')", (user_id,))
        return cur.lastrowid

def recalc_order(order_id: int):
    with _conn() as cn:
        cur = cn.execute("""SELECT SUM(qty*unit_price) AS total FROM order_items WHERE order_id=?""", (order_id,))
        total = cur.fetchone()["total"] or 0
        cn.execute("UPDATE orders SET total_amount=? WHERE order_id=?", (total, order_id))

def add_or_inc_item(order_id: int, product_id: int, unit_price: int, inc: int = 1):
    with _conn() as cn:
        cur = cn.execute("""SELECT item_id, qty FROM order_items WHERE order_id=? AND product_id=?""",
                         (order_id, product_id))
        row = cur.fetchone()
        if row:
            cn.execute("UPDATE order_items SET qty=? WHERE item_id=?", (row["qty"] + inc, row["item_id"]))
        else:
            cn.execute("""INSERT INTO order_items(order_id,product_id,qty,unit_price)
                          VALUES(?,?,?,?)""", (order_id, product_id, inc, unit_price))
    recalc_order(order_id)

def get_draft_with_items(user_id: int) -> Tuple[Optional[sqlite3.Row], List[sqlite3.Row]]:
    with _conn() as cn:
        cur = cn.execute("SELECT * FROM orders WHERE user_id=? AND status='draft'", (user_id,))
        order = cur.fetchone()
        if not order:
            return None, []
        items = list(cn.execute("""SELECT oi.*, p.name
                                  FROM order_items oi
                                  JOIN products p ON p.product_id=oi.product_id
                                  WHERE oi.order_id=? ORDER BY oi.item_id""", (order["order_id"],)))
        return order, items

def submit_order(order_id: int):
    with _conn() as cn:
        cn.execute("UPDATE orders SET status='submitted' WHERE order_id=?", (order_id,))

def pay_order_wallet(user_id: int, order_id: int) -> bool:
    with _conn() as cn:
        cur = cn.execute("SELECT total_amount FROM orders WHERE order_id=?", (order_id,))
        total = cur.fetchone()["total_amount"] or 0
        cur = cn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        bal = cur.fetchone()["balance"] or 0
    if bal < total:
        return False
    change_balance(user_id, -total, "order", f'order_id:{order_id}')
    # cashback
    cashback = (total * CASHBACK_PERCENT) // 100
    if cashback > 0:
        change_balance(user_id, cashback, "cashback", f'order_id:{order_id}')
    with _conn() as cn:
        cn.execute("UPDATE orders SET status='paid', cashback_amount=? WHERE order_id=?", (cashback, order_id))
    return True
