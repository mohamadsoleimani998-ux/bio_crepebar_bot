import os
import asyncio
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

import psycopg2
from psycopg2.extras import RealDictCursor

# ====== ENV ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")
EXTERNAL_URL = os.getenv("EXTERNAL_URL")  # e.g., https://your-service.onrender.com
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL is missing")
if not EXTERNAL_URL:
    raise RuntimeError("ENV EXTERNAL_URL is missing")

# ====== DB UTILS ======
def db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def db_execute(sql: str, params: tuple = ()):
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            try:
                rows = cur.fetchall()
            except psycopg2.ProgrammingError:
                rows = None
        conn.commit()
    return rows

def run_migrations():
    # users
    db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_id BIGINT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            address TEXT,
            wallet BIGINT DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    # products
    db_execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price BIGINT NOT NULL,
            descr TEXT,
            photo_file_id TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    # music
    db_execute("""
        CREATE TABLE IF NOT EXISTS music (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            file_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    # orders
    db_execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(tg_id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            delivery TEXT,
            total BIGINT DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    # order_items
    db_execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INT REFERENCES orders(id) ON DELETE CASCADE,
            product_id INT REFERENCES products(id) ON DELETE SET NULL,
            qty INT NOT NULL DEFAULT 1,
            price BIGINT NOT NULL DEFAULT 0
        );
    """)

# ====== STATES ======
(ASK_NAME, ASK_PHONE, ASK_ADDRESS) = range(3)
(ADD_P_NAME, ADD_P_PRICE, ADD_P_DESC, ADD_P_PHOTO) = range(10, 14)
(EDIT_MENU, EDIT_FIELD, EDIT_VALUE, EDIT_PHOTO) = range(20, 24)
(ORDER_WAIT_QTY, ORDER_DELIVERY) = range(30, 32)
(ADD_MUSIC_TITLE, ADD_MUSIC_FILE) = range(40, 42)
(WALLET_WAIT_AMOUNT,) = range(50, 51)

# ====== HELPERS ======
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def main_menu_kb(is_admin_flag: bool) -> ReplyKeyboardMarkup:
    rows = [
        ["منوی محصولات ☕️", "کیف پول 💸"],
        ["موزیک 🎵", "بازی‌ها 🎮"],
        ["اینستاگرام 📲"]
    ]
    if is_admin_flag:
        rows.append(["افزودن محصول ➕", "مدیریت محصولات ✏️"])
        rows.append(["افزودن موزیک 🎶"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

async def ensure_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id
    u = db_execute("SELECT tg_id FROM users WHERE tg_id=%s", (uid,))
    return bool(u)

def format_price(x: int) -> str:
    return f"{x:,} تومان"

# ====== START / ONBOARDING ======
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    exists = await ensure_user(update, ctx)
    if not exists:
        await update.message.reply_text("به بایو کِرِپ بار خوش اومدی ☕️\nاول خودتو معرفی کن.\nاسم و فامیل؟")
        return ASK_NAME
    await update.message.reply_text("به بایو کِرِپ بار خوش اومدی ☕️\nچطور می‌تونم کمک کنم؟",
                                    reply_markup=main_menu_kb(is_admin(user.id)))
    return ConversationHandler.END

async def ask_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["name"] = update.message.text.strip()
    kb = ReplyKeyboardMarkup([[KeyboardButton("ارسال شماره 📞", request_contact=True)]],
                             resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("شماره موبایل لطفاً:", reply_markup=kb)
    return ASK_PHONE

async def got_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone = update.message.contact.phone_number if update.message.contact else update.message.text.strip()
    ctx.user_data["phone"] = phone
    await update.message.reply_text("آدرس کامل تحویل سفارش؟", reply_markup=ReplyKeyboardMarkup([["بی‌خیال"]], resize_keyboard=True))
    return ASK_ADDRESS

async def save_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    uid = update.effective_user.id
    name = ctx.user_data.get("name")
    phone = ctx.user_data.get("phone")
    db_execute("INSERT INTO users(tg_id,name,phone,address) VALUES(%s,%s,%s,%s) ON CONFLICT (tg_id) DO NOTHING",
               (uid, name, phone, address))
    await update.message.reply_text("ثبت نامت تکمیل شد ✅", reply_markup=main_menu_kb(is_admin(uid)))
    return ConversationHandler.END

async def cancel_onboarding(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("انصراف داده شد.", reply_markup=main_menu_kb(is_admin(update.effective_user.id)))
    return ConversationHandler.END

# ====== PRODUCTS (USER) ======
async def products_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = db_execute("SELECT id,name,price FROM products ORDER BY id DESC") or []
    if not rows:
        await update.message.reply_text("هنوز محصولی ثبت نشده.")
        return
    buttons = [[InlineKeyboardButton(f"{r['name']} — {format_price(r['price'])}", callback_data=f"prod_{r['id']}")] for r in rows]
    await update.message.reply_text("منوی محصولات:", reply_markup=InlineKeyboardMarkup(buttons))

async def product_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split("_")[1])
    r = db_execute("SELECT * FROM products WHERE id=%s", (pid,))
    if not r:
        await q.edit_message_text("محصول پیدا نشد.")
        return
    p = r[0]
    text = f"**{p['name']}**\n{p.get('descr') or ''}\nقیمت: {format_price(p['price'])}"
    buttons = [
        [InlineKeyboardButton("ثبت سفارش 🧾", callback_data=f"order_{pid}")],
    ]
    if is_admin(q.from_user.id):
        buttons.append([InlineKeyboardButton("ویرایش ✏️", callback_data=f"edit_{pid}")])
    if p["photo_file_id"]:
        try:
            await q.message.reply_photo(p["photo_file_id"], caption=text, parse_mode=ParseMode.MARKDOWN,
                                        reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

# ====== ORDER FLOW ======
async def order_start_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split("_")[1])
    ctx.user_data["order_pid"] = pid
    await q.message.reply_text("چه تعدادی؟ (یک عدد وارد کن)")
    return ORDER_WAIT_QTY

async def order_got_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("تعداد نامعتبره. یک عدد صحیح وارد کن.")
        return ORDER_WAIT_QTY
    ctx.user_data["order_qty"] = qty
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ارسال به آدرس 🛵", callback_data="dlv_send")],
        [InlineKeyboardButton("تحویل حضوری 🏪", callback_data="dlv_pickup")]
    ])
    await update.message.reply_text("روش تحویل رو انتخاب کن:", reply_markup=kb)
    return ORDER_DELIVERY

async def order_set_delivery_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    delivery = "ارسال" if q.data == "dlv_send" else "حضوری"
    uid = q.from_user.id
    pid = ctx.user_data.get("order_pid")
    qty = ctx.user_data.get("order_qty", 1)
    # قیمت محصول
    pr = db_execute("SELECT price,name FROM products WHERE id=%s", (pid,))
    if not pr:
        await q.edit_message_text("محصول پیدا نشد.")
        return ConversationHandler.END
    price = int(pr[0]["price"])
    total = price * qty
    # ساخت سفارش
    ord_row = db_execute("INSERT INTO orders(user_id,status,delivery,total) VALUES(%s,%s,%s,%s) RETURNING id",
                         (uid, "در انتظار پرداخت", delivery, total))
    order_id = ord_row[0]["id"]
    db_execute("INSERT INTO order_items(order_id,product_id,qty,price) VALUES(%s,%s,%s,%s)",
               (order_id, pid, qty, price))
    text = f"سفارش #{order_id}\nمحصول: {pr[0]['name']}\nتعداد: {qty}\nمبلغ کل: {format_price(total)}\nروش تحویل: {delivery}\n\n" \
           f"🔻 پرداخت کارت به کارت:\nشماره کارت: 6037-xxxx-xxxx-xxxx\nبه نام: BIO Crepebar\n" \
           f"سپس *رسید* را برای ادمین ارسال کنید. بعد از تأیید، سفارش شما انجام می‌شود."
    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    # اطلاع ادمین
    try:
        await q.bot.send_message(ADMIN_ID, f"سفارش جدید #{order_id} از {uid}، مبلغ {format_price(total)} — وضعیت: در انتظار پرداخت")
    except Exception:
        pass
    return ConversationHandler.END

# ====== WALLET ======
async def wallet_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    r = db_execute("SELECT wallet FROM users WHERE tg_id=%s", (uid,))
    bal = int(r[0]["wallet"]) if r else 0
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("درخواست شارژ 💳", callback_data="w_add")]])
    await update.message.reply_text(f"موجودی کیف پول: {format_price(bal)}", reply_markup=kb)

async def wallet_add_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("چه مبلغی شارژ کنم؟ (عدد تومان)")
    return WALLET_WAIT_AMOUNT

async def wallet_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("مبلغ نامعتبره.")
        return WALLET_WAIT_AMOUNT
    uid = update.effective_user.id
    await update.message.reply_text("درخواستت ثبت شد. بعد از واریز کارت به کارت رسید رو برای ادمین بفرست.")
    try:
        await update.get_bot().send_message(ADMIN_ID, f"درخواست شارژ کیف پول کاربر {uid} به مبلغ {format_price(amount)}")
    except Exception:
        pass
    return ConversationHandler.END

# ====== PRODUCTS (ADMIN) ======
async def add_product_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("نام محصول؟")
    return ADD_P_NAME

async def add_p_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان)؟")
    return ADD_P_PRICE

async def add_p_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
        if price <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("قیمت نامعتبره. فقط عدد.")
        return ADD_P_PRICE
    ctx.user_data["p_price"] = price
    await update.message.reply_text("توضیحات کوتاه؟ (یا «خالی»)")
    return ADD_P_DESC

async def add_p_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = update.message.text.strip()
    ctx.user_data["p_desc"] = "" if d == "خالی" else d
    await update.message.reply_text("عکس محصول را ارسال کن (می‌تونی رد کنی و ننویسی «بی‌عکس»).")
    return ADD_P_PHOTO

async def add_p_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.text and update.message.text.strip() == "بی‌عکس":
        file_id = None
    else:
        await update.message.reply_text("یا عکس بفرست یا بنویس «بی‌عکس».")
        return ADD_P_PHOTO
    name = ctx.user_data["p_name"]
    price = ctx.user_data["p_price"]
    desc = ctx.user_data["p_desc"]
    db_execute("INSERT INTO products(name,price,descr,photo_file_id) VALUES(%s,%s,%s,%s)",
               (name, price, desc, file_id))
    await update.message.reply_text("محصول با موفقیت ثبت شد ✅")
    return ConversationHandler.END

# مدیریت محصولات (ویرایش)
async def manage_products(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    rows = db_execute("SELECT id,name FROM products ORDER BY id DESC") or []
    if not rows:
        await update.message.reply_text("محصولی نداریم.")
        return
    buttons = [[InlineKeyboardButton(r["name"], callback_data=f"mprod_{r['id']}")] for r in rows]
    await update.message.reply_text("یک محصول برای ویرایش انتخاب کن:", reply_markup=InlineKeyboardMarkup(buttons))
    return EDIT_MENU

async def mprod_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split("_")[1])
    ctx.user_data["edit_pid"] = pid
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("نام", callback_data="ef_name"),
         InlineKeyboardButton("قیمت", callback_data="ef_price")],
        [InlineKeyboardButton("توضیح", callback_data="ef_descr"),
         InlineKeyboardButton("عکس", callback_data="ef_photo")]
    ])
    await q.edit_message_text("کدام فیلد را ویرایش کنیم؟", reply_markup=kb)
    return EDIT_FIELD

async def edit_field_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    f = q.data.split("_")[1]
    ctx.user_data["edit_field"] = f
    if f == "photo":
        await q.message.reply_text("عکس جدید را ارسال کن.")
        return EDIT_PHOTO
    prompt = {
        "name": "نام جدید؟",
        "price": "قیمت جدید (تومان)؟",
        "descr": "توضیح جدید؟"
    }[f]
    await q.message.reply_text(prompt)
    return EDIT_VALUE

async def edit_set_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pid = ctx.user_data.get("edit_pid")
    f = ctx.user_data.get("edit_field")
    val = update.message.text.strip()
    if f == "price":
        try:
            val = int(val)
        except Exception:
            await update.message.reply_text("قیمت نامعتبره.")
            return EDIT_VALUE
    db_execute(f"UPDATE products SET {f}=%s WHERE id=%s", (val, pid))
    await update.message.reply_text("ویرایش انجام شد ✅")
    return ConversationHandler.END

async def edit_set_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pid = ctx.user_data.get("edit_pid")
    if not update.message.photo:
        await update.message.reply_text("عکس نامعتبر.")
        return EDIT_PHOTO
    file_id = update.message.photo[-1].file_id
    db_execute("UPDATE products SET photo_file_id=%s WHERE id=%s", (file_id, pid))
    await update.message.reply_text("عکس بروزرسانی شد ✅")
    return ConversationHandler.END

# ====== MUSIC ======
async def music_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = db_execute("SELECT id,title FROM music ORDER BY id DESC") or []
    if not rows:
        await update.message.reply_text("فعلاً موزیکی ثبت نشده.")
        return
    buttons = [[InlineKeyboardButton(r["title"], callback_data=f"msc_{r['id']}")] for r in rows]
    await update.message.reply_text("موزیک‌های کافه:", reply_markup=InlineKeyboardMarkup(buttons))

async def music_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    mid = int(q.data.split("_")[1])
    r = db_execute("SELECT * FROM music WHERE id=%s", (mid,))
    if not r:
        await q.edit_message_text("موجود نیست.")
        return
    m = r[0]
    await q.message.reply_audio(m["file_id"], caption=m["title"])

async def add_music_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("عنوان موزیک؟")
    return ADD_MUSIC_TITLE

async def add_music_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["msc_title"] = update.message.text.strip()
    await update.message.reply_text("فایل صوتی را ارسال کن.")
    return ADD_MUSIC_FILE

async def add_music_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.audio:
        await update.message.reply_text("لطفاً فایل صوتی بفرست.")
        return ADD_MUSIC_FILE
    file_id = update.message.audio.file_id
    title = ctx.user_data.get("msc_title", "بدون عنوان")
    db_execute("INSERT INTO music(title,file_id) VALUES(%s,%s)", (title, file_id))
    await update.message.reply_text("موزیک اضافه شد ✅")
    return ConversationHandler.END

# ====== GAMES (placeholder) ======
async def games(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("بخش بازی‌ها به‌زودی... 🎮\n(قراره لیگ هفتگی و جایزه شارژ کیف پول داشته باشیم)")

# ====== INSTAGRAM ======
async def instagram(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اینستاگرام ما: https://instagram.com/yourpage")

# ====== MAIN HANDLER ======
def conversation_flows(app: Application):
    # Onboarding
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_PHONE: [
                MessageHandler(filters.CONTACT, got_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_phone),
            ],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_user)],
        },
        fallbacks=[CommandHandler("cancel", cancel_onboarding)],
        name="onboarding",
        persistent=False,
    ))

    # Orders
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(order_start_cb, pattern=r"^order_\d+$")],
        states={
            ORDER_WAIT_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_got_qty)],
            ORDER_DELIVERY: [CallbackQueryHandler(order_set_delivery_cb, pattern=r"^dlv_")]
        },
        fallbacks=[],
        name="order",
        persistent=False,
    ))

    # Wallet
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(wallet_add_cb, pattern="^w_add$")],
        states={WALLET_WAIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_amount)]},
        fallbacks=[],
        name="wallet",
        persistent=False,
    ))

    # Add product
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن محصول ➕$"), add_product_entry)],
        states={
            ADD_P_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_p_name)],
            ADD_P_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_p_price)],
            ADD_P_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_p_desc)],
            ADD_P_PHOTO: [
                MessageHandler(filters.PHOTO, add_p_photo),
                MessageHandler(filters.Regex("^بی‌عکس$"), add_p_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_p_photo),
            ],
        },
        fallbacks=[],
        name="add_product",
        persistent=False,
    ))

    # Edit product
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^مدیریت محصولات ✏️$"), manage_products)],
        states={
            EDIT_MENU: [CallbackQueryHandler(mprod_pick, pattern=r"^mprod_\d+$")],
            EDIT_FIELD: [CallbackQueryHandler(edit_field_pick, pattern=r"^ef_")],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_set_value)],
            EDIT_PHOTO: [MessageHandler(filters.PHOTO, edit_set_photo)],
        },
        fallbacks=[],
        name="edit_product",
        persistent=False,
    ))

    # Add music
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن موزیک 🎶$"), add_music_entry)],
        states={
            ADD_MUSIC_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_music_title)],
            ADD_MUSIC_FILE: [MessageHandler(filters.AUDIO, add_music_file)],
        },
        fallbacks=[],
        name="add_music",
        persistent=False,
    ))

    # Simple menus
    app.add_handler(MessageHandler(filters.Regex("^منوی محصولات ☕️$"), products_menu))
    app.add_handler(CallbackQueryHandler(product_detail_cb, pattern=r"^prod_\d+$"))
    app.add_handler(MessageHandler(filters.Regex("^کیف پول 💸$"), wallet_entry))
    app.add_handler(MessageHandler(filters.Regex("^موزیک 🎵$"), music_menu))
    app.add_handler(CallbackQueryHandler(music_detail_cb, pattern=r"^msc_\d+$"))
    app.add_handler(MessageHandler(filters.Regex("^بازی‌ها 🎮$"), games))
    app.add_handler(MessageHandler(filters.Regex("^اینستاگرام 📲$"), instagram))

# ====== ENTRYPOINT ======
async def on_start(app: Application):
    # DB ready
    run_migrations()
    # ست‌کردن وب‌هوک
    url_path = BOT_TOKEN  # مسیر امن
    webhook_url = f"{EXTERNAL_URL}/{url_path}"
    await app.bot.set_webhook(webhook_url, allowed_updates=app.defaults.allowed_updates)
    print("Webhook set to:", webhook_url)

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # منوهای ساده روی /start هم کار کنند
    application.add_handler(CommandHandler("start", start))

    conversation_flows(application)

    # CallbackHandlers عمومی (باید بعد از add_handlerهای بالا باشند)
    # (چیز دیگری لازم نیست)

    # استارت
    application.post_init = on_start

    # سرور وب داخلی PTB (برای Render پورت باز می‌کند)
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,                # مسیر محلی
        webhook_url=f"{EXTERNAL_URL}/{BOT_TOKEN}",  # آدرس عمومی
    )

if __name__ == "__main__":
    main()
