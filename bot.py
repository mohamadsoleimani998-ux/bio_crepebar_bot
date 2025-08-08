import os
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from aiohttp import web

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler, filters, ContextTypes
)

# ===================== لاگینگ =====================
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bio_crepebar")

# ===================== تنظیمات از ENV =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
INSTAGRAM_URL = os.getenv("INSTAGRAM_URL", "https://www.instagram.com/bio.crepebar")
CASHBACK_PERCENT = float(os.getenv("CASHBACK_PERCENT", "3"))  # مثلاً ۳٪

DATABASE_URL = os.getenv("DATABASE_URL")  # اگر نباشه میریم روی sqlite

# ===================== دیتابیس: Postgres یا SQLite =====================
import sqlite3
USE_PG = False
try:
    if DATABASE_URL:
        import psycopg2
        import psycopg2.extras
        USE_PG = True
except Exception as e:
    log.warning("psycopg2 not available, fallback to SQLite. %s", e)
    USE_PG = False

DB_PATH = os.path.join(os.path.dirname(__file__), "data.sqlite")

def db_connect():
    if USE_PG:
        return psycopg2.connect(DATABASE_URL)
    else:
        return sqlite3.connect(DB_PATH)

def db_exec(sql: str, params: Tuple = (), fetch: str = ""):
    """
    fetch: "" | "one" | "all"
    """
    conn = db_connect()
    conn.set_session(autocommit=True) if USE_PG else None
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        elif fetch == "all":
            return cur.fetchall()
        else:
            return None
    finally:
        conn.close()

def init_db():
    if not USE_PG and not os.path.exists(DB_PATH):
        open(DB_PATH, "a").close()

    # users
    db_exec("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            full_name TEXT,
            phone TEXT,
            address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # wallets
    db_exec("""
        CREATE TABLE IF NOT EXISTS wallets (
            user_id BIGINT PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
    """)
    # products
    db_exec("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            photo_file_id TEXT
        )
    """)
    # pending topups (کارت به کارت تا تأیید ادمین)
    db_exec("""
        CREATE TABLE IF NOT EXISTS topups (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount INTEGER NOT NULL,
            receipt TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # orders (ساده)
    db_exec("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            product_id INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            total INTEGER NOT NULL,
            status TEXT DEFAULT 'created',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

# ===================== کیبوردها =====================
def main_menu(is_admin: bool = False):
    rows = [
        ["منوی محصولات ☕️", "کیف پول 💸"],
        ["اینستاگرام 📲", "حساب من 👤"],
        ["🎵 موزیک‌های کافه", "🕹️ بازی‌ها"],
    ]
    if is_admin:
        rows.append(["➕ افزودن محصول", "✏️ ویرایش محصول"])
        rows.append(["✅ تأیید شارژها"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ===================== استیت‌های گفتگو =====================
(
    ADD_NAME, ADD_PRICE, ADD_PHOTO,
    EDIT_CHOOSE_ID, EDIT_CHOOSE_FIELD, EDIT_NEW_VALUE,
    PROFILE_NAME, PROFILE_PHONE, PROFILE_ADDRESS,
    TOPUP_AMOUNT, TOPUP_RECEIPT,
    ORDER_CHOOSE_QTY, ORDER_DELIVERY,
) = range(13)

# ===================== ابزارها =====================
def is_admin(user_id: int) -> bool:
    return ADMIN_ID and user_id == ADMIN_ID

def get_or_create_wallet(user_id: int) -> int:
    row = db_exec("SELECT balance FROM wallets WHERE user_id = %s" if USE_PG else
                  "SELECT balance FROM wallets WHERE user_id = ?", (user_id,), "one")
    if row:
        return int(row[0])
    db_exec("INSERT INTO wallets(user_id, balance) VALUES (%s, 0)" if USE_PG else
            "INSERT INTO wallets(user_id, balance) VALUES (?, 0)", (user_id,))
    return 0

def add_cashback(user_id: int, amount: int):
    if CASHBACK_PERCENT <= 0:
        return
    bonus = int(amount * CASHBACK_PERCENT / 100)
    db_exec("UPDATE wallets SET balance = balance + %s WHERE user_id = %s" if USE_PG else
            "UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (bonus, user_id))

async def ensure_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id
    row = db_exec("SELECT full_name, phone, address FROM users WHERE user_id = %s" if USE_PG else
                  "SELECT full_name, phone, address FROM users WHERE user_id = ?", (uid,), "one")
    if not row or not row[0] or not row[1] or not row[2]:
        await update.message.reply_text(
            "برای ادامه، لطفاً پروفایل‌ت رو تکمیل کن.\nاسم‌ت رو بفرست:", reply_markup=ReplyKeyboardRemove()
        )
        return False
    return True

# ===================== دستورات =====================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # ثبت کاربر
    db_exec("INSERT INTO users(user_id, full_name) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING" if USE_PG else
            "INSERT OR IGNORE INTO users(user_id, full_name) VALUES (?, ?)",
            (user.id, user.full_name or user.first_name))
    get_or_create_wallet(user.id)
    await update.message.reply_text(
        "به بایو کرپ بار خوش اومدی ☕️\nچطور می‌تونم کمک‌ت کنم؟",
        reply_markup=main_menu(is_admin(user.id))
    )

# ----------- منوها و دکمه‌های ساده
async def open_instagram(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"اینستاگرام ما:\n{INSTAGRAM_URL}")

async def my_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    row = db_exec("SELECT full_name, phone, address FROM users WHERE user_id = %s" if USE_PG else
                  "SELECT full_name, phone, address FROM users WHERE user_id = ?", (uid,), "one")
    name, phone, addr = (row or ("—","—","—"))
    bal = get_or_create_wallet(uid)
    await update.message.reply_text(
        f"👤 حساب شما\nنام: {name}\nتلفن: {phone}\nآدرس: {addr}\n\n💰 کیف‌پول: {bal} تومان"
    )

# ----------- لیست محصولات
async def show_products(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = db_exec("SELECT id, name, price, photo_file_id FROM products ORDER BY id DESC", fetch="all")
    if not rows:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.")
        return
    for pid, name, price, fid in rows:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("سفارش 🛒", callback_data=f"order:{pid}")],
            [InlineKeyboardButton("نمایش عکس 📷", callback_data=f"photo:{pid}") if fid else InlineKeyboardButton("—", callback_data="noop")]
        ])
        await update.message.reply_text(f"#{pid}\n{name}\nقیمت: {price:,} تومان", reply_markup=kb)

async def cb_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, pid = q.data.split(":")
    row = db_exec("SELECT name, photo_file_id FROM products WHERE id = %s" if USE_PG else
                  "SELECT name, photo_file_id FROM products WHERE id = ?", (int(pid),), "one")
    if row and row[1]:
        await q.message.reply_photo(row[1], caption=row[0])
    else:
        await q.message.reply_text("برای این محصول عکسی ثبت نشده.")

# ----------- سفارش (ساده)
async def cb_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, pid = q.data.split(":")
    ctx.user_data["order_pid"] = int(pid)
    await q.message.reply_text("تعداد رو بفرست (مثلاً 1 یا 2):")
    return ORDER_CHOOSE_QTY

async def order_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        assert 1 <= qty <= 10
    except:
        await update.message.reply_text("لطفاً یک عدد 1 تا 10 بفرست.")
        return ORDER_CHOOSE_QTY

    uid = update.effective_user.id
    # چک پروفایل
    row = db_exec("SELECT full_name, phone, address FROM users WHERE user_id = %s" if USE_PG else
                  "SELECT full_name, phone, address FROM users WHERE user_id = ?", (uid,), "one")
    if not row or not row[0] or not row[1] or not row[2]:
        await update.message.reply_text("برای تکمیل سفارش اول پروفایل رو تکمیل کنیم.\nاسم‌ت رو بفرست:", reply_markup=ReplyKeyboardRemove())
        ctx.user_data["pending_after_profile"] = ("order", qty)
        return PROFILE_NAME

    pid = ctx.user_data["order_pid"]
    prow = db_exec("SELECT price FROM products WHERE id = %s" if USE_PG else
                   "SELECT price FROM products WHERE id = ?", (pid,), "one")
    if not prow:
        await update.message.reply_text("محصول پیدا نشد.")
        return ConversationHandler.END
    total = int(prow[0]) * qty

    db_exec("INSERT INTO orders(user_id, product_id, qty, total) VALUES (%s,%s,%s,%s)" if USE_PG else
            "INSERT INTO orders(user_id, product_id, qty, total) VALUES (?,?,?,?)",
            (uid, pid, qty, total))

    await update.message.reply_text(
        f"سفارش ثبت شد ✅\nمبلغ قابل پرداخت: {total:,} تومان\n"
        "می‌خوای پرداخت رو با «کیف پول» بدی یا کارت‌به‌کارت؟\n"
        "برای کارت‌به‌کارت از منوی «کیف پول 💸» → «شارژ» استفاده کن."
    )
    add_cashback(uid, total)
    return ConversationHandler.END

# ----------- پروفایل: اسم/تلفن/آدرس
async def profile_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اسم‌ت رو بفرست:", reply_markup=ReplyKeyboardRemove())
    return PROFILE_NAME

async def profile_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("شماره موبایل:", reply_markup=ReplyKeyboardRemove())
    return PROFILE_PHONE

async def profile_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("آدرس:", reply_markup=ReplyKeyboardRemove())
    return PROFILE_ADDRESS

async def profile_address(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["address"] = update.message.text.strip()
    uid = update.effective_user.id
    db_exec(
        "INSERT INTO users(user_id, full_name, phone, address) VALUES (%s,%s,%s,%s) "
        "ON CONFLICT (user_id) DO UPDATE SET full_name=EXCLUDED.full_name, phone=EXCLUDED.phone, address=EXCLUDED.address"
        if USE_PG else
        "INSERT INTO users(user_id, full_name, phone, address) VALUES (?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET full_name=excluded.full_name, phone=excluded.phone, address=excluded.address",
        (uid, ctx.user_data["name"], ctx.user_data["phone"], ctx.user_data["address"])
    )
    await update.message.reply_text("پروفایل ذخیره شد ✅", reply_markup=main_menu(is_admin(uid)))

    # اگر به‌خاطر سفارش وارد شدیم
    if ctx.user_data.get("pending_after_profile"):
        kind, qty = ctx.user_data.pop("pending_after_profile")
        if kind == "order":
            await update.message.reply_text("حالا دوباره از «منوی محصولات» محصول‌ت رو انتخاب کن و سفارش بده.")
    return ConversationHandler.END

# ----------- کیف پول و شارژ کارت‌به‌کارت
async def wallet_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = get_or_create_wallet(uid)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("شارژ کیف پول 💳", callback_data="wallet:topup")],
    ])
    await update.message.reply_text(f"موجودی کیف پول: {bal:,} تومان", reply_markup=kb)

async def cb_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "wallet:topup":
        await q.message.reply_text("مبلغ شارژ (تومان) رو بفرست:")
        return TOPUP_AMOUNT

async def topup_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip())
        assert amount >= 10000
    except:
        await update.message.reply_text("لطفاً عدد معتبر (حداقل 10000) بفرست.")
        return TOPUP_AMOUNT

    ctx.user_data["topup_amount"] = amount
    await update.message.reply_text(
        "مبلغ رو کارت‌به‌کارت کن و **رسید/کد رهگیری** رو بفرست.\n"
        "کارت: 6037-xxxx-xxxx-xxxx",
        parse_mode="Markdown"
    )
    return TOPUP_RECEIPT

async def topup_receipt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    amount = int(ctx.user_data["topup_amount"])
    receipt = update.message.text.strip()
    db_exec("INSERT INTO topups(user_id, amount, receipt) VALUES (%s,%s,%s)" if USE_PG else
            "INSERT INTO topups(user_id, amount, receipt) VALUES (?,?,?)",
            (uid, amount, receipt))
    await update.message.reply_text("درخواست شارژ ثبت شد ✅\nپس از تأیید ادمین به کیف پول‌ت اضافه می‌شه.")
    # اطلاع به ادمین
    if ADMIN_ID:
        await update.get_bot().send_message(
            chat_id=ADMIN_ID,
            text=f"درخواست شارژ جدید:\nUser: {uid}\nAmount: {amount}\nReceipt: {receipt}\nبرای تأیید: /approve_{uid}_{amount}"
        )
    return ConversationHandler.END

async def approve_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # فقط ادمین
    if not is_admin(update.effective_user.id):
        return
    # فرمت: /approve_userid_amount
    try:
        _, uid, amount = update.message.text.strip().split("_")
        uid = int(uid); amount = int(amount)
    except:
        await update.message.reply_text("فرمت درست: /approve_<uid>_<amount>")
        return
    db_exec("UPDATE wallets SET balance = COALESCE(balance,0) + %s WHERE user_id = %s" if USE_PG else
            "UPDATE wallets SET balance = COALESCE(balance,0) + ? WHERE user_id = ?", (amount, uid))
    db_exec("UPDATE topups SET status='approved' WHERE user_id=%s AND amount=%s AND status='pending'" if USE_PG else
            "UPDATE topups SET status='approved' WHERE user_id=? AND amount=? AND status='pending'", (uid, amount))
    await update.message.reply_text("شارژ تأیید شد ✅")
    try:
        await ctx.bot.send_message(uid, f"شارژ شما به مبلغ {amount:,} تومان تأیید شد ✅")
    except:  # کاربر مسدود کرده باشد
        pass

# ----------- افزودن محصول (ادمین)
async def add_product_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("این بخش فقط برای ادمین است.")
        return ConversationHandler.END
    await update.message.reply_text("نام محصول را بفرست:", reply_markup=ReplyKeyboardRemove())
    return ADD_NAME

async def add_product_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان):")
    return ADD_PRICE

async def add_product_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
    except:
        await update.message.reply_text("قیمت عددی بفرست.")
        return ADD_PRICE
    ctx.user_data["p_price"] = price
    await update.message.reply_text("عکس محصول را ارسال کن (یا «رد» بنویس تا بدون عکس ثبت شود).")
    return ADD_PHOTO

async def add_product_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fid = None
    if update.message.photo:
        fid = update.message.photo[-1].file_id
    elif update.message.text and update.message.text.strip() == "رد":
        fid = None
    else:
        await update.message.reply_text("یک عکس بفرست یا بنویس «رد».")
        return ADD_PHOTO

    name = ctx.user_data["p_name"]; price = ctx.user_data["p_price"]
    db_exec("INSERT INTO products(name, price, photo_file_id) VALUES (%s,%s,%s)" if USE_PG else
            "INSERT INTO products(name, price, photo_file_id) VALUES (?,?,?)", (name, price, fid))
    await update.message.reply_text("محصول با موفقیت ثبت شد ✅", reply_markup=main_menu(True))
    return ConversationHandler.END

# ----------- ویرایش محصول (ادمین)
async def edit_product_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("این بخش فقط برای ادمین است.")
        return ConversationHandler.END
    await update.message.reply_text("آی‌دی محصول را بفرست (شماره‌ای که کنار هر محصول می‌بینی).")
    return EDIT_CHOOSE_ID

async def edit_product_choose_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        pid = int(update.message.text.strip())
    except:
        await update.message.reply_text("آی‌دی عددی بفرست.")
        return EDIT_CHOOSE_ID
    ctx.user_data["edit_pid"] = pid
    kb = ReplyKeyboardMarkup([["نام"], ["قیمت"], ["عکس"], ["انصراف"]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("کدام مورد را می‌خواهی ویرایش کنی؟", reply_markup=kb)
    return EDIT_CHOOSE_FIELD

async def edit_product_choose_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt == "نام":
        ctx.user_data["edit_field"] = "name"
        await update.message.reply_text("نام جدید:", reply_markup=ReplyKeyboardRemove())
        return EDIT_NEW_VALUE
    elif txt == "قیمت":
        ctx.user_data["edit_field"] = "price"
        await update.message.reply_text("قیمت جدید (تومان):", reply_markup=ReplyKeyboardRemove())
        return EDIT_NEW_VALUE
    elif txt == "عکس":
        ctx.user_data["edit_field"] = "photo"
        await update.message.reply_text("عکس جدید را بفرست:", reply_markup=ReplyKeyboardRemove())
        return EDIT_NEW_VALUE
    else:
        await update.message.reply_text("انجام نشد.", reply_markup=main_menu(True))
        return ConversationHandler.END

async def edit_product_new_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pid = ctx.user_data["edit_pid"]
    field = ctx.user_data["edit_field"]
    if field == "name":
        val = update.message.text.strip()
        db_exec("UPDATE products SET name=%s WHERE id=%s" if USE_PG else
                "UPDATE products SET name=? WHERE id=?", (val, pid))
    elif field == "price":
        try:
            val = int(update.message.text.strip())
        except:
            await update.message.reply_text("قیمت معتبر بفرست.")
            return EDIT_NEW_VALUE
        db_exec("UPDATE products SET price=%s WHERE id=%s" if USE_PG else
                "UPDATE products SET price=? WHERE id=?", (val, pid))
    elif field == "photo":
        if not update.message.photo:
            await update.message.reply_text("یک عکس بفرست.")
            return EDIT_NEW_VALUE
        fid = update.message.photo[-1].file_id
        db_exec("UPDATE products SET photo_file_id=%s WHERE id=%s" if USE_PG else
                "UPDATE products SET photo_file_id=? WHERE id=?", (fid, pid))

    await update.message.reply_text("ویرایش انجام شد ✅", reply_markup=main_menu(True))
    return ConversationHandler.END

# ----------- موزیک و بازی (ساده)
async def music_tab(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 لیست موزیک‌های کافه به‌زودی اینجا اضافه می‌شه.\nفعلاً می‌تونی موزیک دلخواهت رو همینجا آپلود کنی.")

async def games_tab(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🕹️ بخش بازی‌ها به‌زودی؛ بعداً لیگ هفتگی و جایزه کیف‌پول اضافه می‌کنیم.")

# ===================== کانورسیشن‌ها =====================
add_product_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^➕ افزودن محصول$"), add_product_start)],
    states={
        ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
        ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
        ADD_PHOTO: [
            MessageHandler(filters.PHOTO, add_product_photo),
            MessageHandler(filters.Regex("^رد$"), add_product_photo),
            MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_photo),
        ],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    name="add_product_conv",
    persistent=False,
)

edit_product_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^✏️ ویرایش محصول$"), edit_product_start)],
    states={
        EDIT_CHOOSE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_choose_id)],
        EDIT_CHOOSE_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_choose_field)],
        EDIT_NEW_VALUE: [
            MessageHandler(filters.PHOTO, edit_product_new_value),
            MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_new_value),
        ],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    name="edit_product_conv",
    persistent=False,
)

profile_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^حساب من 👤$"), profile_start)],
    states={
        PROFILE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_name)],
        PROFILE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_phone)],
        PROFILE_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_address)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
)

order_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(cb_order, pattern=r"^order:\d+$")],
    states={ORDER_CHOOSE_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_qty)]},
    fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
)

wallet_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^کیف پول 💸$"), wallet_menu),
                  CallbackQueryHandler(cb_wallet, pattern=r"^wallet:")],
    states={
        TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
        TOPUP_RECEIPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_receipt)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
)

# ===================== وب‌سرور سلامت برای Render =====================
async def health(_request):
    return web.Response(text="OK")

async def run_http_server():
    app = web.Application()
    app.add_routes([web.get("/", health), web.get("/healthz", health)])
    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"HTTP health server started on :{port}")

# ===================== MAIN =====================
async def run_bot():
    init_db()

    application: Application = ApplicationBuilder().token(BOT_TOKEN).build()

    # دستورات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^اینستاگرام 📲$"), open_instagram))
    application.add_handler(MessageHandler(filters.Regex("^منوی محصولات ☕️$"), show_products))
    application.add_handler(MessageHandler(filters.Regex("^🎵 موزیک‌های کافه$"), music_tab))
    application.add_handler(MessageHandler(filters.Regex("^🕹️ بازی‌ها$"), games_tab))

    application.add_handler(add_product_conv)
    application.add_handler(edit_product_conv)
    application.add_handler(profile_conv)
    application.add_handler(order_conv)
    application.add_handler(wallet_conv)

    application.add_handler(CallbackQueryHandler(cb_photo, pattern=r"^photo:\d+$"))
    application.add_handler(CommandHandler("approve", approve_cmd))  # /approve_uid_amount

    # منوی پیش‌فرض هنگام پیام‌های ناشناخته
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, start))

    # اجرای polling داخل همین پروسه
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    log.info("Bot polling started.")
    # زنده نگه داشتن
    await asyncio.Event().wait()

async def main():
    # همزمان هم health-server و هم ربات
    await asyncio.gather(run_http_server(), run_bot())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")
