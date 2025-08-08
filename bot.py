# -*- coding: utf-8 -*-
import os, sqlite3, threading, time, math
from http.server import SimpleHTTPRequestHandler, HTTPServer
import telebot
from telebot import types

# ========= Config =========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")

ADMIN_ID = int(os.environ.get("ADMIN_ID", "1606170079"))  # chat_id شما
HTTP_PORT = int(os.environ.get("PORT", 5000))
CASHBACK_PERCENT = 3  # کش‌بک ۳٪

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ========= DB =========
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

# ========= Helpers =========
def main_menu(is_admin: bool = False) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("☕ منوی محصولات", "💸 کیف پول")
    kb.add("🎵 موزیک‌های کافه", "📲 اینستاگرام")
    if is_admin:
        kb.add("🛠 پنل ادمین")
    return kb

def admin_menu_kb() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ افزودن محصول", "📋 لیست محصولات")
    kb.add("✅ تایید شارژها", "📦 سفارش‌های در انتظار")
    kb.add("🎵 افزودن موزیک", "🔙 بازگشت")
    return kb

def product_actions_inline(pid: int) -> types.InlineKeyboardMarkup:
    ik = types.InlineKeyboardMarkup()
    ik.add(
        types.InlineKeyboardButton("🖼️ عکس", callback_data=f"p:photo:{pid}"),
        types.InlineKeyboardButton("🛒 سفارش", callback_data=f"p:order:{pid}")
    )
    return ik

def approve_topup_kb(tid: int) -> types.InlineKeyboardMarkup:
    ik = types.InlineKeyboardMarkup()
    ik.add(
        types.InlineKeyboardButton("تایید ✅", callback_data=f"topup:ok:{tid}"),
        types.InlineKeyboardButton("رد ❌",  callback_data=f"topup:no:{tid}")
    )
    return ik

def approve_order_kb(oid: int) -> types.InlineKeyboardMarkup:
    ik = types.InlineKeyboardMarkup()
    ik.add(
        types.InlineKeyboardButton("تایید ✅", callback_data=f"order:ok:{oid}"),
        types.InlineKeyboardButton("رد ❌",  callback_data=f"order:no:{oid}")
    )
    return ik

def get_wallet(uid: int) -> int:
    row = cur.execute("SELECT wallet FROM users WHERE user_id=?", (uid,)).fetchone()
    return int(row[0]) if row else 0

def set_wallet(uid: int, new_amount: int):
    cur.execute("""INSERT INTO users(user_id,wallet)
                   VALUES(?,?)
                   ON CONFLICT(user_id) DO UPDATE SET wallet=excluded.wallet""", (uid, new_amount))
    conn.commit()

def ensure_user(uid: int):
    cur.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    conn.commit()

# حالت‌های کاربر
state = {}  # uid -> dict

def S(uid): return state.get(uid, {})
def SET(uid, **kwargs):
    s = state.get(uid, {})
    s.update(kwargs)
    state[uid] = s
def CLR(uid): state.pop(uid, None)

# ========= Start & static actions =========
@bot.message_handler(commands=["start"])
def start(msg: types.Message):
    uid = msg.from_user.id
    ensure_user(uid)
    bot.reply_to(msg, "به بایو کِرِپ بار خوش اومدی ☕️", reply_markup=main_menu(uid == ADMIN_ID))

@bot.message_handler(func=lambda m: m.text == "📲 اینستاگرام")
def instagram(msg: types.Message):
    bot.send_message(msg.chat.id, "اینستاگرام ما:\nhttps://www.instagram.com/bio.crepebar")

# ========= Menu (products list) =========
@bot.message_handler(func=lambda m: m.text == "☕ منوی محصولات")
def menu_list(msg: types.Message):
    rows = cur.execute("SELECT id,name,price FROM products ORDER BY id DESC").fetchall()
    if not rows:
        return bot.send_message(msg.chat.id, "هنوز محصولی ثبت نشده است.")
    for pid, name, price in rows:
        bot.send_message(msg.chat.id, f"• <b>{name}</b>\n💵 {price:,} تومان", reply_markup=product_actions_inline(pid))

@bot.callback_query_handler(func=lambda q: q.data.startswith("p:photo:"))
def cb_photo(q: types.CallbackQuery):
    pid = int(q.data.split(":")[-1])
    row = cur.execute("SELECT name,price,photo_id FROM products WHERE id=?", (pid,)).fetchone()
    if not row: return bot.answer_callback_query(q.id, "محصول یافت نشد.")
    name, price, photo = row
    if photo:
        bot.send_photo(q.message.chat.id, photo, caption=f"{name}\n💵 {price:,} تومان")
    else:
        bot.send_message(q.message.chat.id, "برای این محصول هنوز عکسی ثبت نشده.")
    bot.answer_callback_query(q.id)

# ========= Order flow =========
@bot.callback_query_handler(func=lambda q: q.data.startswith("p:order:"))
def cb_order(q: types.CallbackQuery):
    pid = int(q.data.split(":")[-1])
    uid = q.from_user.id
    SET(uid, step="order_name", pid=pid)
    bot.answer_callback_query(q.id)
    bot.send_message(q.message.chat.id, "📝 نام خود را وارد کنید:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step") == "order_name")
def order_name(msg: types.Message):
    uid = msg.from_user.id
    SET(uid, step="order_phone", name=(msg.text or "").strip())
    bot.reply_to(msg, "📱 شماره تماس:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step") == "order_phone")
def order_phone(msg: types.Message):
    uid = msg.from_user.id
    SET(uid, step="order_addr", phone=(msg.text or "").strip())
    bot.reply_to(msg, "📦 آدرس کامل:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step") == "order_addr")
def order_addr(msg: types.Message):
    uid = msg.from_user.id
    SET(uid, step="order_pay", address=(msg.text or "").strip())
    # انتخاب روش پرداخت
    ik = types.InlineKeyboardMarkup()
    ik.add(
        types.InlineKeyboardButton("از کیف پول", callback_data="pay:wallet"),
        types.InlineKeyboardButton("کارت‌به‌کارت", callback_data="pay:card")
    )
    bot.reply_to(msg, "روش پرداخت را انتخاب کنید:", reply_markup=ik)

@bot.callback_query_handler(func=lambda q: q.data in ("pay:wallet", "pay:card"))
def cb_pay_method(q: types.CallbackQuery):
    uid = q.from_user.id
    st = S(uid)
    pid = st.get("pid")
    row = cur.execute("SELECT price,name FROM products WHERE id=?", (pid,)).fetchone()
    if not row:
        bot.answer_callback_query(q.id, "محصول یافت نشد.")
        return
    price, pname = row[0], row[1]

    if q.data == "pay:wallet":
        balance = get_wallet(uid)
        if balance >= price:
            # کسر و ثبت سفارش تأییدشده + کش‌بک
            set_wallet(uid, balance - price)
            cur.execute("INSERT INTO orders(user_id,product_id,status) VALUES(?,?,?)",
                        (uid, pid, "approved"))
            conn.commit()
            cashback = math.floor(price * CASHBACK_PERCENT / 100)
            if cashback > 0:
                set_wallet(uid, get_wallet(uid) + cashback)
            bot.edit_message_text(
                f"✅ سفارش «{pname}» با پرداخت از کیف پول ثبت شد.\n"
                f"💰 کش‌بک {CASHBACK_PERCENT}%: <b>{cashback:,}</b> تومان به کیف پول اضافه شد.",
                q.message.chat.id, q.message.message_id
            )
        else:
            need = price - balance
            bot.edit_message_text(
                f"❌ موجودی کافی نیست. کمبود: <b>{need:,}</b> تومان.\n"
                f"به منوی «💸 کیف پول» برو و شارژ کن، یا کارت‌به‌کارت انتخاب کن.",
                q.message.chat.id, q.message.message_id
            )
    else:
        # کارت به کارت
        SET(uid, step="order_receipt")
        bot.edit_message_text(
            f"💳 مبلغ <b>{price:,}</b> تومان را کارت‌به‌کارت کنید و <b>عکس رسید</b> را ارسال نمایید.",
            q.message.chat.id, q.message.message_id
        )
    bot.answer_callback_query(q.id)

@bot.message_handler(content_types=["photo"])
def photo_router(msg: types.Message):
    uid = msg.from_user.id
    st = S(uid)

    # مرحله افزودن محصول (ادمین)
    if st.get("step") == "add_photo" and uid == ADMIN_ID:
        photo_id = msg.photo[-1].file_id
        name = st["new_name"]; price = st["new_price"]
        cur.execute("INSERT INTO products(name,price,photo_id) VALUES(?,?,?)", (name, price, photo_id))
        conn.commit(); CLR(uid)
        return bot.reply_to(msg, f"✅ «{name}» با قیمت {price:,} ثبت شد.")

    # رسید سفارش
    if st.get("step") == "order_receipt":
        pid = st.get("pid"); receipt = msg.photo[-1].file_id
        cur.execute("INSERT INTO orders(user_id,product_id,status,receipt_photo) VALUES(?,?,?,?)",
                    (uid, pid, "pending", receipt))
        conn.commit()
        bot.reply_to(msg, "✅ رسید دریافت شد. سفارش در انتظار تایید است.")
        # اطلاع به ادمین
        try:
            bot.send_photo(
                ADMIN_ID, receipt,
                caption=f"سفارش جدید (در انتظار تایید)\n"
                        f"کاربر: {uid}\nمحصول: #{pid}\n"
                        f"نام: {st.get('name')}\nشماره: {st.get('phone')}\nآدرس: {st.get('address')}",
                reply_markup=approve_order_kb(cur.execute("SELECT last_insert_rowid()").fetchone()[0])
            )
        except Exception: pass
        CLR(uid); return

    # رسید شارژ کیف پول
    if st.get("step") == "topup_receipt":
        amount = st.get("amount"); receipt = msg.photo[-1].file_id
        cur.execute("INSERT INTO topups(user_id,amount,status,receipt_photo) VALUES(?,?,?,?)",
                    (uid, amount, "pending", receipt))
        conn.commit()
        bot.reply_to(msg, "✅ درخواست شارژ ثبت شد. پس از تایید ادمین به کیف پول اضافه می‌شود.")
        tid = cur.execute("SELECT last_insert_rowid()").fetchone()[0]
        try:
            bot.send_photo(
                ADMIN_ID, receipt,
                caption=f"درخواست شارژ کیف پول\nکاربر: {uid}\nمبلغ: {amount:,} تومان",
                reply_markup=approve_topup_kb(tid)
            )
        except Exception: pass
        CLR(uid); return

# ========= Wallet =========
@bot.message_handler(func=lambda m: m.text == "💸 کیف پول")
def wallet_menu(msg: types.Message):
    uid = msg.from_user.id
    ensure_user(uid)
    bal = get_wallet(uid)
    ik = types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("📤 شارژ کیف پول", callback_data="wallet:topup"))
    bot.send_message(msg.chat.id, f"💰 موجودی: <b>{bal:,}</b> تومان", reply_markup=ik)

@bot.callback_query_handler(func=lambda q: q.data == "wallet:topup")
def cb_topup(q: types.CallbackQuery):
    uid = q.from_user.id
    bot.answer_callback_query(q.id)
    SET(uid, step="topup_amount")
    bot.send_message(q.message.chat.id, "مبلغ شارژ (تومان) را به صورت عدد ارسال کنید:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step") == "topup_amount")
def topup_amount(msg: types.Message):
    uid = msg.from_user.id
    if not (msg.text or "").isdigit():
        return bot.reply_to(msg, "فقط عدد ارسال کن.")
    SET(uid, step="topup_receipt", amount=int(msg.text))
    bot.reply_to(msg, "لطفاً مبلغ را کارت‌به‌کارت کرده و <b>عکس رسید</b> را ارسال نمایید.")

# ========= Admin panel =========
@bot.message_handler(func=lambda m: m.text == "🛠 پنل ادمین" and m.from_user.id == ADMIN_ID)
def open_admin(msg: types.Message):
    bot.send_message(msg.chat.id, "پنل ادمین:", reply_markup=admin_menu_kb())

@bot.message_handler(func=lambda m: m.text == "🔙 بازگشت" and m.from_user.id == ADMIN_ID)
def admin_back(msg: types.Message):
    bot.send_message(msg.chat.id, "بازگشت به منوی اصلی.", reply_markup=main_menu(True))

# افزودن محصول
@bot.message_handler(func=lambda m: m.text == "➕ افزودن محصول" and m.from_user.id == ADMIN_ID)
def add_product_start(msg: types.Message):
    SET(msg.from_user.id, step="add_name")
    bot.reply_to(msg, "نام محصول؟")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step") == "add_name" and m.from_user.id == ADMIN_ID)
def add_product_name(msg: types.Message):
    SET(msg.from_user.id, step="add_price", new_name=(msg.text or "").strip())
    bot.reply_to(msg, "قیمت محصول (فقط عدد تومان):")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step") == "add_price" and m.from_user.id == ADMIN_ID)
def add_product_price(msg: types.Message):
    if not (msg.text or "").isdigit():
        return bot.reply_to(msg, "فقط عدد بفرست.")
    SET(msg.from_user.id, step="add_photo", new_price=int(msg.text))
    bot.reply_to(msg, "حالا <b>عکس محصول</b> را به صورت Photo بفرست.")

@bot.message_handler(func=lambda m: m.text == "📋 لیست محصولات" and m.from_user.id == ADMIN_ID)
def list_products_admin(msg: types.Message):
    rows = cur.execute("SELECT id,name,price FROM products ORDER BY id DESC").fetchall()
    if not rows:
        return bot.reply_to(msg, "هیچ محصولی نیست.")
    txt = "\n".join([f"#{i} • {n} — {p:,} تومان" for i,n,p in rows])
    bot.reply_to(msg, txt)

# سفارش‌های معلق
@bot.message_handler(func=lambda m: m.text == "📦 سفارش‌های در انتظار" and m.from_user.id == ADMIN_ID)
def pending_orders(msg: types.Message):
    rows = cur.execute("""SELECT o.id, o.user_id, p.name, p.price
                          FROM orders o JOIN products p ON p.id=o.product_id
                          WHERE o.status='pending' ORDER BY o.id DESC""").fetchall()
    if not rows:
        return bot.reply_to(msg, "سفارشی در انتظار نیست.")
    for oid, uid, pname, price in rows:
        bot.send_message(msg.chat.id, f"#{oid} از {uid}\n{pname} — {price:,} تومان",
                         reply_markup=approve_order_kb(oid))

# شارژهای معلق
@bot.message_handler(func=lambda m: m.text == "✅ تایید شارژها" and m.from_user.id == ADMIN_ID)
def pending_topups(msg: types.Message):
    rows = cur.execute("SELECT id,user_id,amount FROM topups WHERE status='pending' ORDER BY id DESC").fetchall()
    if not rows:
        return bot.reply_to(msg, "درخواستی در انتظار نیست.")
    for tid, uid, amount in rows:
        bot.send_message(msg.chat.id, f"شارژ #{tid} از {uid} — مبلغ {amount:,}",
                         reply_markup=approve_topup_kb(tid))

# تایید/رد شارژ
@bot.callback_query_handler(func=lambda q: q.data.startswith("topup:"))
def cb_topup_approve(q: types.CallbackQuery):
    _, action, tid_str = q.data.split(":")
    tid = int(tid_str)
    row = cur.execute("SELECT user_id,amount,status FROM topups WHERE id=?", (tid,)).fetchone()
    if not row: return bot.answer_callback_query(q.id, "پیدا نشد.")
    uid, amount, status = row
    if status != "pending":
        return bot.answer_callback_query(q.id, "قبلاً بررسی شده.")
    if action == "ok":
        set_wallet(uid, get_wallet(uid) + amount)
        cur.execute("UPDATE topups SET status='approved' WHERE id=?", (tid,))
        conn.commit()
        bot.edit_message_text(f"✅ شارژ #{tid} تایید شد و {amount:,} به کیف پول {uid} اضافه شد.",
                              q.message.chat.id, q.message.message_id)
        try: bot.send_message(uid, f"✅ شارژ شما تایید شد. موجودی فعلی: {get_wallet(uid):,} تومان")
        except Exception: pass
    else:
        cur.execute("UPDATE topups SET status='rejected' WHERE id=?", (tid,))
        conn.commit()
        bot.edit_message_text(f"❌ شارژ #{tid} رد شد.", q.message.chat.id, q.message.message_id)
        try: bot.send_message(uid, "❌ شارژ شما رد شد.")
        except Exception: pass
    bot.answer_callback_query(q.id)

# تایید/رد سفارش
@bot.callback_query_handler(func=lambda q: q.data.startswith("order:"))
def cb_order_approve(q: types.CallbackQuery):
    _, action, oid_str = q.data.split(":")
    oid = int(oid_str)
    row = cur.execute("SELECT user_id,product_id,status FROM orders WHERE id=?", (oid,)).fetchone()
    if not row: return bot.answer_callback_query(q.id, "پیدا نشد.")
    uid, pid, status = row
    if status != "pending":
        return bot.answer_callback_query(q.id, "قبلاً بررسی شده.")
    price = cur.execute("SELECT price FROM products WHERE id=?", (pid,)).fetchone()[0]
    if action == "ok":
        # تایید + کش‌بک
        cur.execute("UPDATE orders SET status='approved' WHERE id=?", (oid,))
        conn.commit()
        cashback = math.floor(price * CASHBACK_PERCENT / 100)
        if cashback > 0:
            set_wallet(uid, get_wallet(uid) + cashback)
        bot.edit_message_text(f"✅ سفارش #{oid} تایید شد. کش‌بک {cashback:,} تومان اعمال شد.",
                              q.message.chat.id, q.message.message_id)
        try: bot.send_message(uid, f"✅ سفارش شما تایید شد. کش‌بک {cashback:,} تومان به کیف پول اضافه شد.")
        except Exception: pass
    else:
        cur.execute("UPDATE orders SET status='rejected' WHERE id=?", (oid,))
        conn.commit()
        bot.edit_message_text(f"❌ سفارش #{oid} رد شد.", q.message.chat.id, q.message.message_id)
        try: bot.send_message(uid, "❌ سفارش شما رد شد.")
        except Exception: pass
    bot.answer_callback_query(q.id)

# ========= Music =========
@bot.message_handler(func=lambda m: m.text == "🎵 موزیک‌های کافه")
def list_music(msg: types.Message):
    rows = cur.execute("SELECT id,title,file_id FROM music ORDER BY id DESC").fetchall()
    if not rows: return bot.reply_to(msg, "موزیکی ثبت نشده.")
    for _, title, fid in rows:
        bot.send_audio(msg.chat.id, fid, title=title)

@bot.message_handler(func=lambda m: m.text == "🎵 افزودن موزیک" and m.from_user.id == ADMIN_ID)
def add_music_title(msg: types.Message):
    SET(msg.from_user.id, step="music_title")
    bot.reply_to(msg, "عنوان موزیک را بفرست:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step") == "music_title" and m.from_user.id == ADMIN_ID)
def add_music_wait_file(msg: types.Message):
    SET(msg.from_user.id, step="music_file", music_title=(msg.text or "").strip())
    bot.reply_to(msg, "حالا فایل موزیک را ارسال کن (Audio).")

@bot.message_handler(content_types=["audio"])
def add_music_file(msg: types.Message):
    uid = msg.from_user.id
    if S(uid).get("step") == "music_file" and uid == ADMIN_ID:
        title = S(uid).get("music_title") or (msg.audio.title or "Track")
        fid = msg.audio.file_id
        cur.execute("INSERT INTO music(title,file_id) VALUES(?,?)", (title, fid))
        conn.commit(); CLR(uid)
        bot.reply_to(msg, "✅ موزیک ذخیره شد.")

# ========= Tiny HTTP server (for Render) =========
class Ping(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
        self.wfile.write(b"ok")

def run_http():
    srv = HTTPServer(("0.0.0.0", HTTP_PORT), Ping)
    print(f"[HTTP] Listening on :{HTTP_PORT}")
    srv.serve_forever()

# ========= Main =========
if __name__ == "__main__":
    threading.Thread(target=run_http, daemon=True).start()
    time.sleep(0.3)
    print("[BOT] Polling started …")
    bot.infinity_polling(timeout=60, long_polling_timeout=40)
