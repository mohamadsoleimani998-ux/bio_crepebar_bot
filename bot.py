# -*- coding: utf-8 -*-
import os, sqlite3, threading, time, math
from http.server import SimpleHTTPRequestHandler, HTTPServer
import telebot
from telebot import types

# ================= Config =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")

ADMIN_ID = int(os.environ.get("ADMIN_ID", "1606170079"))  # آیدی عددی ادمین
HTTP_PORT = int(os.environ.get("PORT", 5000))
CASHBACK_PERCENT = 3
PAGE_SIZE = 5  # تعداد محصول در هر صفحه

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ================= DB =================
DB = "crepebar.db"
conn = sqlite3.connect(DB, check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  price INTEGER NOT NULL,
  photo_id TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY,
  name TEXT, phone TEXT, address TEXT,
  wallet INTEGER DEFAULT 0
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  status TEXT NOT NULL,            -- pending/approved/rejected
  receipt_photo TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS topups(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  amount INTEGER NOT NULL,
  status TEXT NOT NULL,            -- pending/approved/rejected
  receipt_photo TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS music(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  file_id TEXT NOT NULL
)""")
conn.commit()

# ================= Helpers =================
def ensure_user(uid:int):
    cur.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    conn.commit()

def get_wallet(uid:int)->int:
    row = cur.execute("SELECT wallet FROM users WHERE user_id=?", (uid,)).fetchone()
    return int(row[0]) if row else 0

def set_wallet(uid:int, amount:int):
    cur.execute("""INSERT INTO users(user_id,wallet) VALUES(?,?)
                   ON CONFLICT(user_id) DO UPDATE SET wallet=excluded.wallet""", (uid, amount))
    conn.commit()

def main_menu(is_admin=False):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("☕ منوی محصولات", "💸 کیف پول")
    kb.add("🎵 موزیک‌های کافه", "📲 اینستاگرام")
    if is_admin:
        kb.add("🛠 پنل ادمین")
    return kb

def admin_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ افزودن محصول", "📋 لیست محصولات")
    kb.add("✅ تایید شارژها", "📦 سفارش‌های در انتظار")
    kb.add("🎵 افزودن موزیک", "🔙 بازگشت")
    return kb

# حالت‌های موقّت کاربر
state = {}  # uid -> dict
def S(uid): return state.get(uid, {})
def SET(uid, **kw): d=state.get(uid,{}); d.update(kw); state[uid]=d
def CLR(uid): state.pop(uid, None)

# ================= Start =================
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    ensure_user(uid)
    bot.reply_to(msg, "به بایو کِرِپ بار خوش اومدی ☕️", reply_markup=main_menu(uid==ADMIN_ID))

@bot.message_handler(func=lambda m: m.text=="📲 اینستاگرام")
def ig(msg): bot.send_message(msg.chat.id, "اینستاگرام ما:\nhttps://www.instagram.com/bio.crepebar")

# =============== PRODUCTS with Pagination ===============
def build_menu_page(page:int):
    # تعداد کل
    total = cur.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    max_page = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(1, page), max_page)
    offset = (page - 1) * PAGE_SIZE
    rows = cur.execute("SELECT id,name,price FROM products ORDER BY id DESC LIMIT ? OFFSET ?",
                       (PAGE_SIZE, offset)).fetchall()

    # متن لیست
    if not rows:
        text = "❌ هنوز محصولی ثبت نشده است."
        ik = types.InlineKeyboardMarkup()
        return text, ik, page, max_page

    lines = [f"• <b>{n}</b> — {p:,} تومان (#{pid})" for pid,n,p in rows]
    text = "☕ <b>منوی محصولات</b>\n" + "\n".join(lines) + f"\n\nصفحه {page} از {max_page}"

    # دکمه‌های هر محصول (عکس/سفارش)
    ik = types.InlineKeyboardMarkup()
    for pid, n, p in rows:
        ik.add(
            types.InlineKeyboardButton("🖼 عکس", callback_data=f"ph:{pid}"),
            types.InlineKeyboardButton("🛒 سفارش", callback_data=f"or:{pid}")
        )
    # ناوبری
    nav = []
    if page>1:  nav.append(types.InlineKeyboardButton("◀️ قبلی", callback_data=f"pg:{page-1}"))
    if page<max_page: nav.append(types.InlineKeyboardButton("بعدی ▶️", callback_data=f"pg:{page+1}"))
    if nav: ik.add(*nav)
    return text, ik, page, max_page

@bot.message_handler(func=lambda m: m.text=="☕ منوی محصولات")
def products_menu(msg):
    text, ik, _, _ = build_menu_page(1)
    bot.send_message(msg.chat.id, text, reply_markup=ik)

@bot.callback_query_handler(func=lambda q: q.data.startswith("pg:"))
def cb_page(q):
    page = int(q.data.split(":")[1])
    text, ik, _, _ = build_menu_page(page)
    try:
        bot.edit_message_text(text, q.message.chat.id, q.message.message_id, reply_markup=ik)
    except Exception:
        bot.send_message(q.message.chat.id, text, reply_markup=ik)
    bot.answer_callback_query(q.id)

@bot.callback_query_handler(func=lambda q: q.data.startswith("ph:"))
def cb_photo(q):
    pid = int(q.data.split(":")[1])
    row = cur.execute("SELECT name,price,photo_id FROM products WHERE id=?", (pid,)).fetchone()
    if not row: return bot.answer_callback_query(q.id, "یافت نشد.")
    name, price, photo = row
    if photo:
        bot.send_photo(q.message.chat.id, photo, caption=f"{name}\n💵 {price:,} تومان")
    else:
        bot.send_message(q.message.chat.id, f"برای «{name}» هنوز عکسی ثبت نشده.")
    bot.answer_callback_query(q.id)

# =============== ORDER FLOW ===============
@bot.callback_query_handler(func=lambda q: q.data.startswith("or:"))
def cb_order(q):
    pid = int(q.data.split(":")[1])
    uid = q.from_user.id
    SET(uid, step="order_name", pid=pid)
    bot.answer_callback_query(q.id)
    bot.send_message(q.message.chat.id, "📝 نام خود را وارد کنید:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="order_name")
def order_name(msg):
    uid = msg.from_user.id
    SET(uid, step="order_phone", name=(msg.text or "").strip())
    bot.reply_to(msg, "📱 شماره تماس:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="order_phone")
def order_phone(msg):
    uid = msg.from_user.id
    SET(uid, step="order_addr", phone=(msg.text or "").strip())
    bot.reply_to(msg, "📦 آدرس کامل:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="order_addr")
def order_addr(msg):
    uid = msg.from_user.id
    SET(uid, step="order_pay", address=(msg.text or "").strip())
    ik = types.InlineKeyboardMarkup()
    ik.add(
        types.InlineKeyboardButton("از کیف پول", callback_data="pay:wallet"),
        types.InlineKeyboardButton("کارت‌به‌کارت", callback_data="pay:card")
    )
    bot.reply_to(msg, "روش پرداخت را انتخاب کنید:", reply_markup=ik)

@bot.callback_query_handler(func=lambda q: q.data in ("pay:wallet","pay:card"))
def cb_pay(q):
    uid = q.from_user.id
    st = S(uid)
    pid = st.get("pid")
    row = cur.execute("SELECT price,name FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        bot.answer_callback_query(q.id, "محصول یافت نشد."); return
    price, pname = row

    if q.data=="pay:wallet":
        bal = get_wallet(uid)
        if bal >= price:
            set_wallet(uid, bal - price)
            cur.execute("INSERT INTO orders(user_id,product_id,status) VALUES(?,?,?)",
                        (uid, pid, "approved"))
            conn.commit()
            cashback = math.floor(price*CASHBACK_PERCENT/100)
            if cashback>0: set_wallet(uid, get_wallet(uid)+cashback)
            bot.edit_message_text(
                f"✅ سفارش «{pname}» ثبت شد.\n"
                f"💰 کش‌بک {CASHBACK_PERCENT}%: <b>{cashback:,}</b> تومان اضافه شد.",
                q.message.chat.id, q.message.message_id
            )
        else:
            bot.edit_message_text(
                f"❌ موجودی ناکافی. کمبود: <b>{(price-bal):,}</b> تومان.\n"
                f"از «💸 کیف پول» شارژ کن یا کارت‌به‌کارت را انتخاب کن.",
                q.message.chat.id, q.message.message_id
            )
    else:
        SET(uid, step="order_receipt")
        bot.edit_message_text(
            f"💳 مبلغ <b>{price:,}</b> تومان را کارت‌به‌کارت کنید و <b>عکس رسید</b> را ارسال نمایید.",
            q.message.chat.id, q.message.message_id
        )
    bot.answer_callback_query(q.id)

@bot.message_handler(content_types=["photo"])
def photo_router(msg):
    uid = msg.from_user.id
    st = S(uid)

    # مرحله افزودن محصول
    if st.get("step")=="add_photo" and uid==ADMIN_ID:
        photo_id = msg.photo[-1].file_id
        name = st["new_name"]; price = st["new_price"]
        cur.execute("INSERT INTO products(name,price,photo_id) VALUES(?,?,?)", (name, price, photo_id))
        conn.commit(); CLR(uid)
        return bot.reply_to(msg, f"✅ «{name}» با قیمت {price:,} ثبت شد.")

    # رسید سفارش
    if st.get("step")=="order_receipt":
        pid = st.get("pid"); receipt = msg.photo[-1].file_id
        cur.execute("INSERT INTO orders(user_id,product_id,status,receipt_photo) VALUES(?,?,?,?)",
                    (uid, pid, "pending", receipt))
        conn.commit()
        bot.reply_to(msg, "✅ رسید دریافت شد. سفارش در انتظار تایید است.")
        try:
            oid = cur.execute("SELECT last_insert_rowid()").fetchone()[0]
            bot.send_photo(ADMIN_ID, receipt,
                caption=f"سفارش جدید در انتظار تأیید\nکاربر: {uid}\nمحصول: #{pid}\n"
                        f"نام: {st.get('name')}\nشماره: {st.get('phone')}\nآدرس: {st.get('address')}")
        except Exception: pass
        CLR(uid); return

    # رسید شارژ کیف پول
    if st.get("step")=="topup_receipt":
        amount = st.get("amount"); receipt = msg.photo[-1].file_id
        cur.execute("INSERT INTO topups(user_id,amount,status,receipt_photo) VALUES(?,?,?,?)",
                    (uid, amount, "pending", receipt))
        conn.commit()
        bot.reply_to(msg, "✅ درخواست شارژ ثبت شد؛ ادمین تأیید می‌کند.")
        try:
            tid = cur.execute("SELECT last_insert_rowid()").fetchone()[0]
            bot.send_photo(ADMIN_ID, receipt,
                caption=f"درخواست شارژ\nکاربر: {uid}\nمبلغ: {amount:,} تومان")
        except Exception: pass
        CLR(uid); return

# =============== Wallet ===============
@bot.message_handler(func=lambda m: m.text=="💸 کیف پول")
def wallet_menu(msg):
    uid = msg.from_user.id; ensure_user(uid)
    bal = get_wallet(uid)
    ik = types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("📤 شارژ کیف پول", callback_data="wallet:topup"))
    bot.send_message(msg.chat.id, f"💰 موجودی: <b>{bal:,}</b> تومان", reply_markup=ik)

@bot.callback_query_handler(func=lambda q: q.data=="wallet:topup")
def cb_topup(q):
    bot.answer_callback_query(q.id)
    SET(q.from_user.id, step="topup_amount")
    bot.send_message(q.message.chat.id, "مبلغ شارژ (تومان) را عددی بفرست:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="topup_amount")
def topup_amount(msg):
    uid = msg.from_user.id
    if not (msg.text or "").isdigit():
        return bot.reply_to(msg, "فقط عدد ارسال کن.")
    SET(uid, step="topup_receipt", amount=int(msg.text))
    bot.reply_to(msg, "مبلغ را کارت‌به‌کارت کن و <b>عکس رسید</b> را بفرست.")

# =============== Admin panel ===============
@bot.message_handler(func=lambda m: m.text=="🛠 پنل ادمین" and m.from_user.id==ADMIN_ID)
def open_admin(msg): bot.send_message(msg.chat.id, "پنل ادمین:", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text=="🔙 بازگشت" and m.from_user.id==ADMIN_ID)
def back_admin(msg): bot.send_message(msg.chat.id, "بازگشت به منوی اصلی.", reply_markup=main_menu(True))

# افزودن محصول
@bot.message_handler(func=lambda m: m.text=="➕ افزودن محصول" and m.from_user.id==ADMIN_ID)
def add_product(msg):
    SET(msg.from_user.id, step="add_name")
    bot.reply_to(msg, "نام محصول؟")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="add_name" and m.from_user.id==ADMIN_ID)
def add_name(msg):
    SET(msg.from_user.id, step="add_price", new_name=(msg.text or "").strip())
    bot.reply_to(msg, "قیمت (تومان) را عددی بفرست:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="add_price" and m.from_user.id==ADMIN_ID)
def add_price(msg):
    if not (msg.text or "").isdigit():
        return bot.reply_to(msg, "فقط عدد بفرست.")
    SET(msg.from_user.id, step="add_photo", new_price=int(msg.text))
    bot.reply_to(msg, "حالا <b>عکس محصول</b> را به صورت Photo بفرست. (یا /skip برای بدون عکس)")

# اجازه ثبت بدون عکس برای تست
@bot.message_handler(commands=["skip"])
def skip_photo(msg):
    uid = msg.from_user.id
    st = S(uid)
    if st.get("step")=="add_photo" and uid==ADMIN_ID:
        name = st["new_name"]; price = st["new_price"]
        cur.execute("INSERT INTO products(name,price,photo_id) VALUES(?,?,NULL)", (name, price))
        conn.commit(); CLR(uid)
        bot.reply_to(msg, f"✅ «{name}» با قیمت {price:,} (بدون عکس) ثبت شد.")

# لیست محصولات (ادمین)
@bot.message_handler(func=lambda m: m.text=="📋 لیست محصولات" and m.from_user.id==ADMIN_ID)
def admin_list(msg):
    rows = cur.execute("SELECT id,name,price,COALESCE(photo_id,'-') FROM products ORDER BY id DESC").fetchall()
    if not rows: return bot.reply_to(msg, "محصولی نیست.")
    txt = "\n".join([f"#{i} • {n} — {p:,} | عکس:{'✅' if ph!='-' else '❌'}" for i,n,p,ph in rows])
    bot.reply_to(msg, txt)

# سفارش‌ها و شارژها (لیست ساده برای بررسی)
@bot.message_handler(func=lambda m: m.text=="📦 سفارش‌های در انتظار" and m.from_user.id==ADMIN_ID)
def pending_orders(msg):
    rows = cur.execute("""SELECT o.id, o.user_id, p.name, p.price
                          FROM orders o JOIN products p ON p.id=o.product_id
                          WHERE o.status='pending' ORDER BY o.id DESC""").fetchall()
    if not rows: return bot.reply_to(msg, "سفارشی در انتظار نیست.")
    for oid, uid, pname, price in rows:
        bot.send_message(msg.chat.id, f"#{oid} از {uid}\n{pname} — {price:,} تومان")

@bot.message_handler(func=lambda m: m.text=="✅ تایید شارژها" and m.from_user.id==ADMIN_ID)
def pending_topups(msg):
    rows = cur.execute("SELECT id,user_id,amount FROM topups WHERE status='pending' ORDER BY id DESC").fetchall()
    if not rows: return bot.reply_to(msg, "درخواستی نیست.")
    for tid, uid, amount in rows:
        bot.send_message(msg.chat.id, f"شارژ #{tid} از {uid} — {amount:,} تومان")

# =============== DEBUG (فقط ادمین) ===============
@bot.message_handler(commands=["dbg"])
def dbg(msg):
    if msg.from_user.id != ADMIN_ID: return
    rows = cur.execute("SELECT id,name,price,COALESCE(photo_id,'-') FROM products").fetchall()
    if not rows: bot.reply_to(msg,"DB→ products: 0"); return
    lines = [f"#{i} {n} {p:,} photo:{'y' if ph!='-' else 'n'}" for i,n,p,ph in rows]
    bot.reply_to(msg, "DB→ products:\n" + "\n".join(lines))

# =============== Tiny HTTP server (Render) ===============
class Ping(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type","text/plain; charset=utf-8"); self.end_headers()
        self.wfile.write(b"ok")

def run_http():
    srv = HTTPServer(("0.0.0.0", HTTP_PORT), Ping)
    print(f"[HTTP] Listening on :{HTTP_PORT}")
    srv.serve_forever()

# =============== Main ===============
if __name__ == "__main__":
    threading.Thread(target=run_http, daemon=True).start()
    time.sleep(0.3)
    print("[BOT] Polling…")
    bot.infinity_polling(timeout=60, long_polling_timeout=40)
