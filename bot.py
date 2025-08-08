# -*- coding: utf-8 -*-
import os, sqlite3, threading, time
from http.server import SimpleHTTPRequestHandler, HTTPServer

import telebot
from telebot import types

# ========= Config =========
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # در Render ست کن
ADMIN_ID = 1606170079                    # chat_id ادمین
HTTP_PORT = int(os.environ.get("PORT", 5000))  # Render این متغیر را می‌فرسته

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ========= DB =========
DB_PATH = "crepebar.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
    status TEXT NOT NULL,
    receipt_photo TEXT
)""")
conn.commit()

# ========= Helpers =========
def main_menu(is_admin: bool = False) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("☕ منوی محصولات", "💸 کیف پول")
    kb.add("📲 اینستاگرام")
    if is_admin:
        kb.add("➕ افزودن محصول")
    return kb

def admin_kb_inline(pid: int = None) -> types.InlineKeyboardMarkup:
    ik = types.InlineKeyboardMarkup()
    if pid:
        ik.add(
            types.InlineKeyboardButton("🖼️ عکس", callback_data=f"p:photo:{pid}"),
            types.InlineKeyboardButton("🛒 سفارش", callback_data=f"p:order:{pid}")
        )
    return ik

# هر کاربر در چه مرحله‌ای است
user_state = {}   # {uid: {"step": "...", "pid": 1, "tmp": {...}}}

def set_state(uid, step=None, **kwargs):
    st = user_state.get(uid, {})
    if step is not None:
        st["step"] = step
    st.update(kwargs)
    user_state[uid] = st

def clear_state(uid):
    user_state.pop(uid, None)

# ========= Commands & Menus =========
@bot.message_handler(commands=["start"])
def cmd_start(msg: types.Message):
    uid = msg.from_user.id
    cur.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    conn.commit()
    bot.reply_to(msg, "به بایو کِرِپ بار خوش اومدی ☕️", reply_markup=main_menu(uid == ADMIN_ID))

@bot.message_handler(func=lambda m: m.text == "📲 اینستاگرام")
def instagram(msg: types.Message):
    bot.reply_to(msg, "صفحه ما در اینستاگرام:\nhttps://www.instagram.com/bio.crepebar")

@bot.message_handler(func=lambda m: m.text == "💸 کیف پول")
def wallet(msg: types.Message):
    uid = msg.from_user.id
    row = cur.execute("SELECT wallet FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = row[0] if row else 0
    bot.reply_to(msg, f"💰 موجودی کیف پول: <b>{bal:,}</b> تومان")

@bot.message_handler(func=lambda m: m.text == "☕ منوی محصولات")
def show_menu(msg: types.Message):
    rows = cur.execute("SELECT id, name, price FROM products ORDER BY id DESC").fetchall()
    if not rows:
        return bot.reply_to(msg, "هنوز محصولی ثبت نشده است.")
    for pid, name, price in rows:
        bot.send_message(
            msg.chat.id, f"• <b>{name}</b>\n💵 قیمت: {price:,} تومان",
            reply_markup=admin_kb_inline(pid)
        )

# ========= Admin: add product (name -> price -> photo) =========
@bot.message_handler(func=lambda m: m.text == "➕ افزودن محصول" and m.from_user.id == ADMIN_ID)
def add_product_start(msg: types.Message):
    set_state(msg.from_user.id, step="add_name", tmp={})
    bot.reply_to(msg, "نام محصول را بفرست:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("step") == "add_name")
def add_product_name(msg: types.Message):
    uid = msg.from_user.id
    user_state[uid]["tmp"]["name"] = (msg.text or "").strip()
    set_state(uid, step="add_price")
    bot.reply_to(msg, "قیمت محصول را به صورت عدد (تومان) بفرست:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("step") == "add_price")
def add_product_price(msg: types.Message):
    uid = msg.from_user.id
    if not (msg.text or "").isdigit():
        return bot.reply_to(msg, "فقط عدد ارسال کن.")
    user_state[uid]["tmp"]["price"] = int(msg.text)
    set_state(uid, step="add_photo")
    bot.reply_to(msg, "حالا <b>عکس محصول</b> را به صورت «Photo» بفرست:")

@bot.message_handler(content_types=["photo"])
def add_product_photo_or_receipt(msg: types.Message):
    uid = msg.from_user.id
    st = user_state.get(uid, {})
    # مرحله افزودن محصول
    if st.get("step") == "add_photo" and uid == ADMIN_ID:
        photo_id = msg.photo[-1].file_id
        name = st["tmp"]["name"]
        price = st["tmp"]["price"]
        cur.execute("INSERT INTO products(name, price, photo_id) VALUES(?,?,?)", (name, price, photo_id))
        conn.commit()
        clear_state(uid)
        return bot.reply_to(msg, f"✅ «{name}» با قیمت {price:,} و عکس ثبت شد.")
    # مرحله دریافت رسید سفارش
    if st.get("step") == "order_receipt":
        receipt_id = msg.photo[-1].file_id
        pid = st.get("pid")
        cur.execute("INSERT INTO orders(user_id, product_id, status, receipt_photo) VALUES(?,?,?,?)",
                    (uid, pid, "در انتظار تایید", receipt_id))
        conn.commit()
        bot.reply_to(msg, "✅ رسید دریافت شد. سفارش در صف تایید است.")
        try:
            bot.send_photo(
                ADMIN_ID, receipt_id,
                caption=f"رسید جدید از {uid}\nمحصول #{pid}\n"
                        f"نام: {st.get('name')}\nشماره: {st.get('phone')}\nآدرس: {st.get('address')}"
            )
        except Exception:
            pass
        clear_state(uid)

# ========= Callbacks: photo / order =========
@bot.callback_query_handler(func=lambda q: q.data.startswith("p:photo:"))
def cb_photo(q: types.CallbackQuery):
    pid = int(q.data.split(":")[-1])
    row = cur.execute("SELECT name, price, photo_id FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        bot.answer_callback_query(q.id, "یافت نشد.")
        return
    name, price, photo_id = row
    if photo_id:
        bot.send_photo(q.message.chat.id, photo_id, caption=f"{name}\n💵 {price:,} تومان")
    else:
        bot.send_message(q.message.chat.id, "برای این محصول هنوز عکسی ثبت نشده.")
    bot.answer_callback_query(q.id)

@bot.callback_query_handler(func=lambda q: q.data.startswith("p:order:"))
def cb_order(q: types.CallbackQuery):
    pid = int(q.data.split(":")[-1])
    uid = q.from_user.id
    set_state(uid, step="order_name", pid=pid)
    bot.answer_callback_query(q.id)
    bot.send_message(q.message.chat.id, "📝 لطفاً <b>نام</b> خود را وارد کنید:")

# ========= Order text steps =========
@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("step") == "order_name")
def order_get_name(msg: types.Message):
    uid = msg.from_user.id
    set_state(uid, step="order_phone", name=(msg.text or "").strip())
    bot.reply_to(msg, "📱 شماره تماس را وارد کنید:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("step") == "order_phone")
def order_get_phone(msg: types.Message):
    uid = msg.from_user.id
    set_state(uid, step="order_address", phone=(msg.text or "").strip())
    bot.reply_to(msg, "📦 آدرس کامل را وارد کنید:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("step") == "order_address")
def order_get_address(msg: types.Message):
    uid = msg.from_user.id
    st = user_state.get(uid, {})
    address = (msg.text or "").strip()
    set_state(uid, step="order_receipt", address=address)
    # ذخیره پروفایل کاربر
    cur.execute("""INSERT INTO users(user_id,name,phone,address)
                   VALUES(?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     name=excluded.name, phone=excluded.phone, address=excluded.address""",
                (uid, st.get("name"), st.get("phone"), address))
    conn.commit()
    bot.reply_to(
        msg,
        "💳 پرداخت کارت‌به‌کارت:\n"
        "لطفاً مبلغ سفارش را کارت‌به‌کارت کنید و <b>عکس رسید</b> را ارسال نمایید.\n"
        "پس از تایید، سفارشتان ثبت نهایی می‌شود."
    )

# ========= Tiny HTTP server for Render =========
class PingHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # پاسخ ساده برای health check
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

def run_http_server():
    srv = HTTPServer(("0.0.0.0", HTTP_PORT), PingHandler)
    print(f"[HTTP] Listening on :{HTTP_PORT}")
    srv.serve_forever()

# ========= Main =========
if __name__ == "__main__":
    # وب‌سرور را قبل از polling بالا بیاور تا Render پورت را ببیند
    threading.Thread(target=run_http_server, daemon=True).start()
    time.sleep(0.5)
    print("[BOT] Starting polling…")
    bot.infinity_polling(timeout=60, long_polling_timeout=40, allowed_updates=telebot.util.update_types)
