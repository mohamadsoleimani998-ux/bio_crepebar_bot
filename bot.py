# -*- coding: utf-8 -*-
import os, math, threading, time
from http.server import SimpleHTTPRequestHandler, HTTPServer

import psycopg2
import psycopg2.extras
import telebot
from telebot import types

# ====================== CONFIG ======================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")

ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL is missing")

HTTP_PORT = int(os.environ.get("PORT", "5000"))  # Render will set PORT

PAGE_SIZE = 5           # تعداد آیتم در هر صفحه منو
CASHBACK_PERCENT = 3    # کش‌بک سفارش موفق (کیف پول)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ====================== DB ======================
def get_conn():
    # Neon URL already contains sslmode=require
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

def db_exec(q, args=(), fetch=None):
    """
    fetch=None: commit only
    fetch='one'|'all'
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q, args)
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
            return None

def db_init():
    db_exec("""
    CREATE TABLE IF NOT EXISTS products(
      id SERIAL PRIMARY KEY,
      name TEXT NOT NULL,
      price INTEGER NOT NULL,
      photo_id TEXT
    )""")
    db_exec("""
    CREATE TABLE IF NOT EXISTS users(
      user_id BIGINT PRIMARY KEY,
      name TEXT,
      phone TEXT,
      address TEXT,
      wallet INTEGER DEFAULT 0
    )""")
    db_exec("""
    CREATE TABLE IF NOT EXISTS orders(
      id SERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL,
      product_id INTEGER NOT NULL,
      status TEXT NOT NULL,              -- pending/approved/rejected
      receipt_photo TEXT,
      deliver_method TEXT,               -- delivery/pickup
      created_at TIMESTAMPTZ DEFAULT NOW()
    )""")
    db_exec("""
    CREATE TABLE IF NOT EXISTS topups(
      id SERIAL PRIMARY KEY,
      user_id BIGINT NOT NULL,
      amount INTEGER NOT NULL,
      status TEXT NOT NULL,              -- pending/approved/rejected
      receipt_photo TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
    )""")
    db_exec("""
    CREATE TABLE IF NOT EXISTS music(
      id SERIAL PRIMARY KEY,
      title TEXT NOT NULL,
      file_id TEXT NOT NULL
    )""")

db_init()

# ====================== HELPERS ======================
def ensure_user(uid: int):
    db_exec("INSERT INTO users(user_id) VALUES(%s) ON CONFLICT(user_id) DO NOTHING", (uid,))

def get_user(uid: int):
    return db_exec("SELECT * FROM users WHERE user_id=%s", (uid,), fetch="one")

def set_wallet(uid: int, amount: int):
    db_exec("""INSERT INTO users(user_id,wallet)
               VALUES(%s,%s)
               ON CONFLICT(user_id) DO UPDATE SET wallet=EXCLUDED.wallet""",
            (uid, amount))

def get_wallet(uid: int) -> int:
    row = db_exec("SELECT wallet FROM users WHERE user_id=%s", (uid,), fetch="one")
    return int(row["wallet"]) if row and row["wallet"] is not None else 0

def main_menu(is_admin=False):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("☕ منوی محصولات", "💸 کیف پول")
    kb.add("🎵 موزیک‌های کافه", "🎮 بازی")
    kb.add("📲 اینستاگرام")
    if is_admin:
        kb.add("🛠 پنل ادمین")
    return kb

def admin_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ افزودن محصول", "📋 لیست محصولات")
    kb.add("✏️ ویرایش محصول", "🗑 حذف محصول")
    kb.add("✅ تایید شارژها", "📦 سفارش‌های در انتظار")
    kb.add("🎵 افزودن موزیک", "🔙 بازگشت")
    return kb

# memory for small states
state = {}  # uid -> dict
def S(uid): return state.get(uid, {})
def SET(uid, **kw): d=state.get(uid, {}); d.update(kw); state[uid]=d
def CLR(uid): state.pop(uid, None)

# ====================== START / BASIC ======================
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    ensure_user(uid)
    bot.reply_to(msg, "به <b>بایو کِرِپ بار</b> خوش اومدی ☕️\nچطور می‌تونم کمکت کنم؟",
                 reply_markup=main_menu(uid == ADMIN_ID))

@bot.message_handler(commands=["dbping"])
def dbping(msg):
    try:
        db_exec("SELECT 1")
        bot.reply_to(msg, "✅ DB OK")
    except Exception as e:
        bot.reply_to(msg, f"❌ DB Error:\n{e}")

@bot.message_handler(func=lambda m: m.text=="📲 اینستاگرام")
def instagram(msg):
    bot.send_message(msg.chat.id, "اینستاگرام ما:\nhttps://www.instagram.com/bio.crepebar")

@bot.message_handler(func=lambda m: m.text=="🎮 بازی")
def games(msg):
    bot.send_message(msg.chat.id, "🎮 بخش بازی‌ها به‌زودی فعال می‌شود.\n"
                                  "ایده: لیگ هفتگی و جایزه شارژ کیف پول برای برنده‌ها ✨")

# ====================== MUSIC ======================
@bot.message_handler(func=lambda m: m.text=="🎵 موزیک‌های کافه")
def music_list(msg):
    rows = db_exec("SELECT id,title,file_id FROM music ORDER BY id DESC", fetch="all")
    if not rows:
        bot.reply_to(msg, "هنوز موزیکی ثبت نشده.")
        return
    for r in rows:
        try:
            bot.send_audio(msg.chat.id, r["file_id"], caption=f"🎵 {r['title']}")
        except Exception:
            bot.send_message(msg.chat.id, f"🎵 {r['title']} (فایل موجود نیست)")

@bot.message_handler(func=lambda m: m.text=="🎵 افزودن موزیک" and m.from_user.id==ADMIN_ID)
def music_add_start(msg):
    SET(msg.from_user.id, step="music_wait")
    bot.reply_to(msg, "فایل موسیقی را ارسال کن (Audio). می‌توانی Title را در کپشن بنویسی.")

@bot.message_handler(content_types=["audio"])
def music_add(msg):
    if msg.from_user.id==ADMIN_ID and S(msg.from_user.id).get("step")=="music_wait":
        file_id = msg.audio.file_id
        title = msg.caption or msg.audio.title or "بدون‌نام"
        db_exec("INSERT INTO music(title,file_id) VALUES(%s,%s)", (title, file_id))
        CLR(msg.from_user.id)
        bot.reply_to(msg, f"✅ موزیک «{title}» ذخیره شد.")
        return

# ====================== PRODUCTS (List + Pagination) ======================
def build_menu_page(page:int):
    total = db_exec("SELECT COUNT(*) AS c FROM products", fetch="one")["c"]
    max_page = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(1, page), max_page)
    offset = (page-1)*PAGE_SIZE
    rows = db_exec("SELECT id,name,price FROM products ORDER BY id DESC LIMIT %s OFFSET %s",
                   (PAGE_SIZE, offset), fetch="all")
    if not rows:
        text = "❌ هنوز محصولی ثبت نشده."
        ik = types.InlineKeyboardMarkup()
        return text, ik, page, max_page

    lines = [f"• <b>{r['name']}</b> — {r['price']:,} تومان (#{r['id']})" for r in rows]
    text = "☕ <b>منوی محصولات</b>\n" + "\n".join(lines) + f"\n\nصفحه {page} از {max_page}"

    ik = types.InlineKeyboardMarkup()
    for r in rows:
        pid = r["id"]
        row_btns = [
            types.InlineKeyboardButton("🖼 عکس", callback_data=f"ph:{pid}"),
            types.InlineKeyboardButton("🛒 سفارش", callback_data=f"or:{pid}")
        ]
        ik.add(*row_btns)
    nav = []
    if page>1: nav.append(types.InlineKeyboardButton("◀️ قبلی", callback_data=f"pg:{page-1}"))
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
    text, ik, *_ = build_menu_page(page)
    try:
        bot.edit_message_text(text, q.message.chat.id, q.message.message_id, reply_markup=ik)
    except Exception:
        bot.send_message(q.message.chat.id, text, reply_markup=ik)
    bot.answer_callback_query(q.id)

@bot.callback_query_handler(func=lambda q: q.data.startswith("ph:"))
def cb_photo(q):
    pid = int(q.data.split(":")[1])
    r = db_exec("SELECT name,price,photo_id FROM products WHERE id=%s", (pid,), fetch="one")
    if not r: return bot.answer_callback_query(q.id, "یافت نشد.")
    if r["photo_id"]:
        bot.send_photo(q.message.chat.id, r["photo_id"], caption=f"{r['name']}\n💵 {r['price']:,} تومان")
    else:
        bot.send_message(q.message.chat.id, f"برای «{r['name']}» عکس ثبت نشده.")
    bot.answer_callback_query(q.id)

# ====================== ADD / EDIT / DELETE (ADMIN) ======================
@bot.message_handler(func=lambda m: m.text=="🛠 پنل ادمین" and m.from_user.id==ADMIN_ID)
def open_admin(msg):
    bot.send_message(msg.chat.id, "پنل ادمین:", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text=="🔙 بازگشت" and m.from_user.id==ADMIN_ID)
def back_admin(msg):
    bot.send_message(msg.chat.id, "بازگشت به منوی اصلی.", reply_markup=main_menu(True))

# Add
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

@bot.message_handler(commands=["skip"])
def skip_photo(msg):
    uid = msg.from_user.id
    st = S(uid)
    if st.get("step")=="add_photo" and uid==ADMIN_ID:
        name, price = st["new_name"], st["new_price"]
        db_exec("INSERT INTO products(name,price,photo_id) VALUES(%s,%s,NULL)", (name, price))
        CLR(uid)
        bot.reply_to(msg, f"✅ «{name}» با قیمت {price:,} (بدون عکس) ثبت شد.")

@bot.message_handler(content_types=["photo"])
def on_photo(msg):
    uid = msg.from_user.id
    st = S(uid)

    # add photo flow
    if uid==ADMIN_ID and st.get("step")=="add_photo":
        name, price = st["new_name"], st["new_price"]
        photo_id = msg.photo[-1].file_id
        db_exec("INSERT INTO products(name,price,photo_id) VALUES(%s,%s,%s)", (name, price, photo_id))
        CLR(uid)
        bot.reply_to(msg, f"✅ «{name}» با قیمت {price:,} ثبت شد.")
        return

    # order receipt
    if st.get("step")=="order_receipt":
        pid = st.get("pid"); receipt = msg.photo[-1].file_id
        db_exec("""INSERT INTO orders(user_id,product_id,status,receipt_photo,deliver_method)
                   VALUES(%s,%s,'pending',%s,%s)""", (uid, pid, receipt, st.get("deliver_method","-")))
        CLR(uid)
        bot.reply_to(msg, "✅ رسید دریافت شد. سفارش در انتظار تایید است.")
        # notify admin
        row = db_exec("SELECT name,phone,address FROM users WHERE user_id=%s", (uid,), fetch="one")
        pname = db_exec("SELECT name,price FROM products WHERE id=%s", (pid,), fetch="one")
        try:
            caption = (f"سفارش جدید (در انتظار)\nکاربر: {uid}\n"
                       f"نام: {row.get('name')} | شماره: {row.get('phone')}\n"
                       f"آدرس: {row.get('address')}\n"
                       f"محصول: {pname['name']} — {pname['price']:,} تومان\n"
                       f"تحویل: {st.get('deliver_method','-')}")
            ik = types.InlineKeyboardMarkup()
            ik.add(types.InlineKeyboardButton("✅ تایید سفارش", callback_data="ord_ok"),
                   types.InlineKeyboardButton("❌ رد", callback_data="ord_rej"))
            bot.send_photo(ADMIN_ID, receipt, caption=caption, reply_markup=ik)
        except Exception:
            pass
        return

    # topup receipt
    if st.get("step")=="topup_receipt":
        amount = int(st.get("amount", 0))
        receipt = msg.photo[-1].file_id
        db_exec("INSERT INTO topups(user_id,amount,status,receipt_photo) VALUES(%s,%s,'pending',%s)",
                (uid, amount, receipt))
        CLR(uid)
        bot.reply_to(msg, "✅ درخواست شارژ ثبت شد؛ بعد از تایید ادمین به کیف پول می‌نشیند.")
        try:
            ik = types.InlineKeyboardMarkup()
            ik.add(types.InlineKeyboardButton("✅ تایید شارژ", callback_data="tu_ok"),
                   types.InlineKeyboardButton("❌ رد", callback_data="tu_rej"))
            bot.send_photo(ADMIN_ID, receipt,
                           caption=f"درخواست شارژ: {amount:,} تومان\nکاربر: {uid}", reply_markup=ik)
        except Exception:
            pass
        return

# Edit (choose product by id)
@bot.message_handler(func=lambda m: m.text=="✏️ ویرایش محصول" and m.from_user.id==ADMIN_ID)
def edit_product_start(msg):
    SET(msg.from_user.id, step="edit_ask_id")
    bot.reply_to(msg, "آیدی محصول (id) را بفرست. برای دیدن لیست: «📋 لیست محصولات»")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="edit_ask_id" and m.from_user.id==ADMIN_ID)
def edit_choose_field(msg):
    if not (msg.text or "").isdigit():
        return bot.reply_to(msg, "آیدی عددی بفرست.")
    pid = int(msg.text)
    r = db_exec("SELECT id,name,price FROM products WHERE id=%s", (pid,), fetch="one")
    if not r: return bot.reply_to(msg, "یافت نشد.")
    SET(msg.from_user.id, step="edit_menu", pid=pid)
    ik = types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("نام", callback_data="ed:name"),
           types.InlineKeyboardButton("قیمت", callback_data="ed:price"),
           types.InlineKeyboardButton("عکس", callback_data="ed:photo"))
    bot.reply_to(msg, f"ویرایش «{r['name']}» (#{pid}) — {r['price']:,} تومان", reply_markup=ik)

@bot.callback_query_handler(func=lambda q: q.data.startswith("ed:"))
def cb_edit_field(q):
    fld = q.data.split(":")[1]
    uid = q.from_user.id
    if uid != ADMIN_ID: return bot.answer_callback_query(q.id)
    if fld=="name":
        SET(uid, step="edit_name"); bot.send_message(q.message.chat.id, "نام جدید را بفرست:")
    elif fld=="price":
        SET(uid, step="edit_price"); bot.send_message(q.message.chat.id, "قیمت جدید (عدد):")
    elif fld=="photo":
        SET(uid, step="edit_photo"); bot.send_message(q.message.chat.id, "عکس جدید را Photo بفرست:")
    bot.answer_callback_query(q.id)

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="edit_name" and m.from_user.id==ADMIN_ID)
def do_edit_name(msg):
    pid = S(msg.from_user.id).get("pid")
    new = (msg.text or "").strip()
    db_exec("UPDATE products SET name=%s WHERE id=%s", (new, pid))
    CLR(msg.from_user.id)
    bot.reply_to(msg, "✅ نام محصول به‌روزرسانی شد.")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="edit_price" and m.from_user.id==ADMIN_ID)
def do_edit_price(msg):
    pid = S(msg.from_user.id).get("pid")
    if not (msg.text or "").isdigit(): return bot.reply_to(msg, "فقط عدد.")
    db_exec("UPDATE products SET price=%s WHERE id=%s", (int(msg.text), pid))
    CLR(msg.from_user.id)
    bot.reply_to(msg, "✅ قیمت محصول به‌روزرسانی شد.")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="edit_photo" and m.from_user.id==ADMIN_ID, content_types=["photo"])
def do_edit_photo(msg):
    pid = S(msg.from_user.id).get("pid")
    photo_id = msg.photo[-1].file_id
    db_exec("UPDATE products SET photo_id=%s WHERE id=%s", (photo_id, pid))
    CLR(msg.from_user.id)
    bot.reply_to(msg, "✅ عکس محصول به‌روزرسانی شد.")

# Delete
@bot.message_handler(func=lambda m: m.text=="🗑 حذف محصول" and m.from_user.id==ADMIN_ID)
def del_product_start(msg):
    SET(msg.from_user.id, step="del_ask_id")
    bot.reply_to(msg, "آیدی محصول برای حذف؟")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="del_ask_id" and m.from_user.id==ADMIN_ID)
def del_product_do(msg):
    if not (msg.text or "").isdigit(): return bot.reply_to(msg, "عدد بفرست.")
    pid = int(msg.text)
    db_exec("DELETE FROM products WHERE id=%s", (pid,))
    CLR(msg.from_user.id)
    bot.reply_to(msg, "🗑 حذف شد (اگر وجود داشت).")

# Admin list
@bot.message_handler(func=lambda m: m.text=="📋 لیست محصولات" and m.from_user.id==ADMIN_ID)
def admin_list(msg):
    rows = db_exec("SELECT id,name,price,COALESCE(photo_id,'-') AS ph FROM products ORDER BY id DESC", fetch="all")
    if not rows: return bot.reply_to(msg, "محصولی نیست.")
    txt = "\n".join([f"#{r['id']} • {r['name']} — {r['price']:,} | عکس:{'✅' if r['ph']!='-' else '❌'}" for r in rows])
    bot.reply_to(msg, txt)

# ====================== ORDER FLOW ======================
@bot.callback_query_handler(func=lambda q: q.data.startswith("or:"))
def cb_order(q):
    pid = int(q.data.split(":")[1])
    uid = q.from_user.id
    ensure_user(uid)
    # اگر اطلاعات کاربر کامل نیست، جمع‌آوری می‌کنیم
    u = get_user(uid)
    if not (u and u.get("name") and u.get("phone") and u.get("address")):
        SET(uid, step="profile_name", pid=pid)
        bot.send_message(q.message.chat.id, "📝 لطفاً اول نام خود را وارد کنید:")
        return bot.answer_callback_query(q.id)
    # انتخاب روش تحویل
    SET(uid, step="deliver", pid=pid)
    ik = types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("🚚 ارسال", callback_data="dlv:delivery"),
           types.InlineKeyboardButton("📥 حضوری", callback_data="dlv:pickup"))
    bot.send_message(q.message.chat.id, "روش تحویل سفارش را انتخاب کنید:", reply_markup=ik)
    bot.answer_callback_query(q.id)

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="profile_name")
def prof_name(msg):
    name = (msg.text or "").strip()
    uid = msg.from_user.id
    db_exec("""INSERT INTO users(user_id,name) VALUES(%s,%s)
               ON CONFLICT(user_id) DO UPDATE SET name=EXCLUDED.name""", (uid, name))
    SET(uid, step="profile_phone")
    bot.reply_to(msg, "📱 شماره تماس:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="profile_phone")
def prof_phone(msg):
    phone = (msg.text or "").strip()
    uid = msg.from_user.id
    db_exec("UPDATE users SET phone=%s WHERE user_id=%s", (phone, uid))
    SET(uid, step="profile_addr")
    bot.reply_to(msg, "📦 آدرس کامل:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="profile_addr")
def prof_addr(msg):
    addr = (msg.text or "").strip()
    uid = msg.from_user.id
    db_exec("UPDATE users SET address=%s WHERE user_id=%s", (addr, uid))
    # حالا می‌رویم سراغ انتخاب روش تحویل
    pid = S(uid).get("pid")
    SET(uid, step="deliver", pid=pid)
    ik = types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("🚚 ارسال", callback_data="dlv:delivery"),
           types.InlineKeyboardButton("📥 حضوری", callback_data="dlv:pickup"))
    bot.reply_to(msg, "روش تحویل سفارش را انتخاب کنید:", reply_markup=ik)

@bot.callback_query_handler(func=lambda q: q.data.startswith("dlv:"))
def cb_deliver(q):
    uid = q.from_user.id
    method = q.data.split(":")[1]  # delivery/pickup
    SET(uid, deliver_method=method, step="pay_method")
    # انتخاب روش پرداخت
    ik = types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("از کیف پول", callback_data="pay:wallet"),
           types.InlineKeyboardButton("کارت‌به‌کارت", callback_data="pay:card"))
    bot.edit_message_text("روش پرداخت را انتخاب کنید:", q.message.chat.id, q.message.message_id, reply_markup=ik)
    bot.answer_callback_query(q.id)

@bot.callback_query_handler(func=lambda q: q.data in ("pay:wallet","pay:card"))
def cb_pay(q):
    uid = q.from_user.id
    st = S(uid)
    pid = st.get("pid")
    pr = db_exec("SELECT name,price FROM products WHERE id=%s", (pid,), fetch="one")
    if not pr: return bot.answer_callback_query(q.id, "محصول یافت نشد.")
    name, price = pr["name"], pr["price"]

    if q.data == "pay:wallet":
        bal = get_wallet(uid)
        if bal >= price:
            set_wallet(uid, bal - price)
            db_exec("""INSERT INTO orders(user_id,product_id,status,deliver_method)
                       VALUES(%s,%s,'approved',%s)""", (uid, pid, st.get("deliver_method","-")))
            cashback = math.floor(price * CASHBACK_PERCENT / 100)
            if cashback>0:
                set_wallet(uid, get_wallet(uid)+cashback)
            CLR(uid)
            bot.edit_message_text(
                f"✅ سفارش «{name}» ثبت شد.\n💳 از کیف پول پرداخت شد.\n"
                f"🎁 کش‌بک {CASHBACK_PERCENT}%: <b>{cashback:,}</b> تومان واریز شد.",
                q.message.chat.id, q.message.message_id
            )
        else:
            bot.edit_message_text(
                f"❌ موجودی ناکافی. کمبود: <b>{(price-bal):,}</b> تومان.\n"
                f"از «💸 کیف پول» شارژ کن یا کارت‌به‌کارت را انتخاب کن.",
                q.message.chat.id, q.message.message_id
            )
    else:
        # کارت به کارت → رسید لازم
        SET(uid, step="order_receipt")
        bot.edit_message_text(
            f"💳 مبلغ <b>{price:,}</b> تومان را کارت‌به‌کارت کنید و <b>عکس رسید</b> را ارسال نمایید.",
            q.message.chat.id, q.message.message_id
        )
    bot.answer_callback_query(q.id)

# ====================== WALLET & TOPUP ======================
@bot.message_handler(func=lambda m: m.text=="💸 کیف پول")
def wallet(msg):
    uid = msg.from_user.id
    ensure_user(uid)
    bal = get_wallet(uid)
    ik = types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("📤 شارژ کیف پول", callback_data="wallet:topup"))
    bot.send_message(msg.chat.id, f"💰 موجودی: <b>{bal:,}</b> تومان", reply_markup=ik)

@bot.callback_query_handler(func=lambda q: q.data=="wallet:topup")
def wallet_topup(q):
    SET(q.from_user.id, step="topup_amount")
    bot.answer_callback_query(q.id)
    bot.send_message(q.message.chat.id, "مبلغ شارژ (تومان) را عددی بفرست:")

@bot.message_handler(func=lambda m: S(m.from_user.id).get("step")=="topup_amount")
def topup_amount(msg):
    if not (msg.text or "").isdigit():
        return bot.reply_to(msg, "فقط عدد ارسال کن.")
    SET(msg.from_user.id, step="topup_receipt", amount=int(msg.text))
    bot.reply_to(msg, "مبلغ را کارت‌به‌کارت کن و <b>عکس رسید</b> را بفرست.")

# ===== Admin approve topups & orders =====
@bot.message_handler(func=lambda m: m.text=="✅ تایید شارژها" and m.from_user.id==ADMIN_ID)
def list_topups(msg):
    rows = db_exec("SELECT id,user_id,amount FROM topups WHERE status='pending' ORDER BY id DESC", fetch="all")
    if not rows: return bot.reply_to(msg, "درخواستی نیست.")
    for r in rows:
        ik = types.InlineKeyboardMarkup()
        ik.add(types.InlineKeyboardButton("✅ تایید", callback_data=f"tu_ok:{r['id']}"),
               types.InlineKeyboardButton("❌ رد", callback_data=f"tu_rej:{r['id']}"))
        bot.send_message(msg.chat.id, f"#{r['id']} | {r['user_id']} • {r['amount']:,} تومان", reply_markup=ik)

@bot.message_handler(func=lambda m: m.text=="📦 سفارش‌های در انتظار" and m.from_user.id==ADMIN_ID)
def list_orders(msg):
    rows = db_exec("""SELECT o.id,o.user_id,p.name,p.price
                      FROM orders o JOIN products p ON p.id=o.product_id
                      WHERE o.status='pending' ORDER BY o.id DESC""", fetch="all")
    if not rows: return bot.reply_to(msg, "سفارشی در انتظار نیست.")
    for r in rows:
        ik = types.InlineKeyboardMarkup()
        ik.add(types.InlineKeyboardButton("✅ تایید", callback_data=f"ord_ok:{r['id']}"),
               types.InlineKeyboardButton("❌ رد", callback_data=f"ord_rej:{r['id']}"))
        bot.send_message(msg.chat.id, f"#{r['id']} | {r['user_id']} • {r['name']} — {r['price']:,}", reply_markup=ik)

@bot.callback_query_handler(func=lambda q: q.data.startswith(("tu_ok:","tu_rej:")) and q.from_user.id==ADMIN_ID)
def approve_topup(q):
    action, tid = q.data.split(":"); tid = int(tid)
    t = db_exec("SELECT user_id,amount,status FROM topups WHERE id=%s", (tid,), fetch="one")
    if not t or t["status"]!="pending":
        bot.answer_callback_query(q.id, "یافت نشد/قبلاً رسیدگی شده."); return
    if action=="tu_ok":
        new = get_wallet(t["user_id"]) + int(t["amount"])
        set_wallet(t["user_id"], new)
        db_exec("UPDATE topups SET status='approved' WHERE id=%s", (tid,))
        bot.answer_callback_query(q.id, "تایید شد.")
        bot.send_message(t["user_id"], f"✅ شارژ {int(t['amount']):,} تومان تایید شد. موجودی: {new:,}")
    else:
        db_exec("UPDATE topups SET status='rejected' WHERE id=%s", (tid,))
        bot.answer_callback_query(q.id, "رد شد.")
        bot.send_message(t["user_id"], "❌ شارژ شما رد شد. لطفاً با پشتیبانی در تماس باشید.")
    try:
        bot.edit_message_reply_markup(q.message.chat.id, q.message.message_id, reply_markup=None)
    except Exception:
        pass

@bot.callback_query_handler(func=lambda q: q.data.startswith(("ord_ok:","ord_rej:")) and q.from_user.id==ADMIN_ID)
def approve_order(q):
    action, oid = q.data.split(":"); oid = int(oid)
    o = db_exec("SELECT user_id,status FROM orders WHERE id=%s", (oid,), fetch="one")
    if not o or o["status"]!="pending":
        bot.answer_callback_query(q.id, "یافت نشد/قبلاً رسیدگی شده."); return
    if action=="ord_ok":
        db_exec("UPDATE orders SET status='approved' WHERE id=%s", (oid,))
        bot.answer_callback_query(q.id, "سفارش تایید شد.")
        bot.send_message(o["user_id"], "✅ سفارش شما تایید شد. ممنون از خریدتان ☕️")
    else:
        db_exec("UPDATE orders SET status='rejected' WHERE id=%s", (oid,))
        bot.answer_callback_query(q.id, "رد شد.")
        bot.send_message(o["user_id"], "❌ سفارش شما رد شد. هزینه در صورت پرداخت، ظرف 24ساعت عودت می‌شود.")
    try:
        bot.edit_message_reply_markup(q.message.chat.id, q.message.message_id, reply_markup=None)
    except Exception:
        pass

# ====================== HTTP server for Render ======================
class Ping(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type","text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

def run_http():
    srv = HTTPServer(("0.0.0.0", HTTP_PORT), Ping)
    print(f"[HTTP] listening on :{HTTP_PORT}")
    srv.serve_forever()

# ====================== MAIN ======================
if __name__ == "__main__":
    threading.Thread(target=run_http, daemon=True).start()
    time.sleep(0.3)
    print("[BOT] polling…")
    bot.infinity_polling(timeout=60, long_polling_timeout=40)
