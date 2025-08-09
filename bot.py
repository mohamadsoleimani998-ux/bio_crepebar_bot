import os
import logging
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler, ContextTypes, filters
)

import psycopg2
from psycopg2.pool import SimpleConnectionPool

# ------------- Config -------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # توکن جدیدت
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))  # آیدی عددی ادمین
DATABASE_URL = os.environ.get("DATABASE_URL")    # PostgreSQL (Neon)
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")      # مثل https://your-service.onrender.com
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "supersecret-CHANGE")  # یه رشته تصادفی
PORT = int(os.environ.get("PORT", "10000"))      # Render می‌فرسته

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")

if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL is missing")

# ------------- Logging -------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar")

# ------------- DB Pool & Migrations -------------
DB: SimpleConnectionPool | None = None

MIGRATIONS = [
    # کاربران
    """
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        tg_id BIGINT UNIQUE NOT NULL,
        full_name TEXT,
        phone TEXT,
        address TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    # محصولات
    """
    CREATE TABLE IF NOT EXISTS products (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        price BIGINT NOT NULL,
        photo_file_id TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    # درخواست شارژ کیف پول (کارت به کارت)
    """
    CREATE TABLE IF NOT EXISTS wallet_topups (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(tg_id),
        amount BIGINT NOT NULL,
        proof_file_id TEXT,
        status TEXT NOT NULL DEFAULT 'pending', -- pending/approved/rejected
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    # کیف پول
    """
    CREATE TABLE IF NOT EXISTS wallets (
        user_id BIGINT PRIMARY KEY REFERENCES users(tg_id),
        balance BIGINT NOT NULL DEFAULT 0
    );
    """,
]

def db_get():
    assert DB is not None
    return DB.getconn()

def db_put(conn):
    assert DB is not None
    DB.putconn(conn)

def run_migrations():
    conn = db_get()
    try:
        with conn, conn.cursor() as cur:
            for sql in MIGRATIONS:
                cur.execute(sql)
    finally:
        db_put(conn)

# ------------- Helpers -------------
MAIN_KB = ReplyKeyboardMarkup(
    [
        ["منوی محصولات ☕️", "کیف پول 💸"],
        ["اینستاگرام 📱"],
        ["افزودن محصول ➕"]  # فقط برای ادمین نمایش می‌دهیم (در کد کنترل می‌کنیم)
    ],
    resize_keyboard=True
)

def main_kb_for(user_id: int):
    rows = [["منوی محصولات ☕️", "کیف پول 💸"],
            ["اینستاگرام 📱"]]
    if user_id == ADMIN_ID:
        rows.append(["افزودن محصول ➕"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ثبت کاربر در اولین تعامل"""
    u = update.effective_user
    conn = db_get()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE tg_id=%s", (u.id,))
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO users (tg_id, full_name) VALUES (%s,%s)",
                    (u.id, u.full_name or "")
                )
                # ایجاد کیف پول
                cur.execute(
                    "INSERT INTO wallets (user_id, balance) VALUES (%s, 0) ON CONFLICT DO NOTHING",
                    (u.id,)
                )
    finally:
        db_put(conn)

# ------------- Handlers -------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update, context)
    await update.message.reply_text("به بایو کِرِپ بار خوش اومدی ☕️\nچطور می‌تونم کمکت کنم؟",
                                    reply_markup=main_kb_for(update.effective_user.id))

# ---- محصولات: افزودن (ادمین) ----
ADD_NAME, ADD_PRICE, ADD_PHOTO = range(3)

async def add_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("این بخش فقط مخصوص ادمین است.")
    await update.message.reply_text("اسم محصول را بفرست:", reply_markup=ReplyKeyboardRemove())
    return ADD_NAME

async def add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_name"] = (update.message.text or "").strip()
    if not context.user_data["new_name"]:
        await update.message.reply_text("اسم نامعتبر است. دوباره بفرست.")
        return ADD_NAME
    await update.message.reply_text("قیمت (تومان) را بفرست (فقط عدد):")
    return ADD_PRICE

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if not txt.isdigit():
        await update.message.reply_text("فقط عدد بفرست.")
        return ADD_PRICE
    context.user_data["new_price"] = int(txt)
    await update.message.reply_text("در صورت تمایل عکس محصول را بفرست (یا بنویس: رد):")
    return ADD_PHOTO

async def add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif (update.message.text or "").strip() in ("رد", "skip", "no"):
        file_id = None
    else:
        await update.message.reply_text("عکس نامعتبر. دوباره عکس بفرست یا بنویس «رد».")
        return ADD_PHOTO

    name = context.user_data.pop("new_name")
    price = context.user_data.pop("new_price")
    conn = db_get()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO products (name, price, photo_file_id) VALUES (%s,%s,%s) RETURNING id",
                (name, price, file_id)
            )
            pid = cur.fetchone()[0]
    finally:
        db_put(conn)

    await update.message.reply_text(f"✅ محصول «{name}» ثبت شد (ID: {pid}).",
                                    reply_markup=main_kb_for(update.effective_user.id))
    return ConversationHandler.END

async def add_product_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=main_kb_for(update.effective_user.id))
    return ConversationHandler.END

# ---- منوی محصولات ----
def fetch_products():
    conn = db_get()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT id, name, price, photo_file_id FROM products ORDER BY id DESC LIMIT 50")
            return cur.fetchall()
    finally:
        db_put(conn)

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = fetch_products()
    if not items:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.")
        return
    # لیست متنی + دکمه مشاهده عکس
    lines = []
    kb_rows = []
    for pid, name, price, photo in items:
        lines.append(f"{pid}) {name} — {price:,} تومان")
        kb_rows.append([InlineKeyboardButton(f"عکس {pid}", callback_data=f"p:{pid}")])
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(kb_rows)
    )

async def product_photo_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    conn = db_get()
    row = None
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT name, photo_file_id FROM products WHERE id=%s", (pid,))
            row = cur.fetchone()
    finally:
        db_put(conn)
    if not row:
        return await q.edit_message_text("محصول پیدا نشد.")
    name, photo = row
    if photo:
        await q.message.reply_photo(photo, caption=f"📦 {name}")
    else:
        await q.edit_message_text(f"برای «{name}» عکسی ثبت نشده است.")

# ---- ویرایش محصول (ادمین) ----
EDIT_WAIT_ID, EDIT_CHOICE, EDIT_NEWVAL = range(3, 6)

async def edit_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("این بخش فقط مخصوص اdmین است.")
    await update.message.reply_text("ID محصولی که می‌خواهی ویرایش کنی را بفرست:")
    return EDIT_WAIT_ID

async def edit_product_got_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if not txt.isdigit():
        await update.message.reply_text("فقط عدد ID را بفرست.")
        return EDIT_WAIT_ID
    context.user_data["edit_id"] = int(txt)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ویرایش نام", callback_data="e:name"),
         InlineKeyboardButton("ویرایش قیمت", callback_data="e:price")],
        [InlineKeyboardButton("ویرایش عکس", callback_data="e:photo")]
    ])
    await update.message.reply_text("کدام را می‌خواهی ویرایش کنی؟", reply_markup=kb)
    return EDIT_CHOICE

async def edit_product_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    what = q.data.split(":")[1]
    context.user_data["edit_field"] = what
    if what == "name":
        await q.edit_message_text("نام جدید را بفرست:")
    elif what == "price":
        await q.edit_message_text("قیمت جدید (عدد) را بفرست:")
    else:
        await q.edit_message_text("عکس جدید را بفرست:")
    return EDIT_NEWVAL

async def edit_product_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.get("edit_id")
    field = context.user_data.get("edit_field")
    if field == "photo":
        if not update.message.photo:
            await update.message.reply_text("عکس نامعتبر. دوباره عکس بفرست.")
            return EDIT_NEWVAL
        newval = update.message.photo[-1].file_id
        sql = "UPDATE products SET photo_file_id=%s WHERE id=%s"
        params = (newval, pid)
    elif field == "price":
        txt = (update.message.text or "").strip()
        if not txt.isdigit():
            await update.message.reply_text("فقط عدد بفرست.")
            return EDIT_NEWVAL
        sql = "UPDATE products SET price=%s WHERE id=%s"
        params = (int(txt), pid)
    else:
        newname = (update.message.text or "").strip()
        if not newname:
            await update.message.reply_text("نام نامعتبر.")
            return EDIT_NEWVAL
        sql = "UPDATE products SET name=%s WHERE id=%s"
        params = (newname, pid)

    conn = db_get()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
    finally:
        db_put(conn)

    await update.message.reply_text("✅ ویرایش انجام شد.", reply_markup=main_kb_for(update.effective_user.id))
    context.user_data.pop("edit_id", None)
    context.user_data.pop("edit_field", None)
    return ConversationHandler.END

async def edit_product_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=main_kb_for(update.effective_user.id))
    return ConversationHandler.END

# ---- کیف پول ----
TOPUP_WAIT_AMOUNT, TOPUP_WAIT_PROOF = range(6, 8)

def get_balance(tg_id: int) -> int:
    conn = db_get()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT balance FROM wallets WHERE user_id=%s", (tg_id,))
            row = cur.fetchone()
            return row[0] if row else 0
    finally:
        db_put(conn)

async def wallet_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = get_balance(update.effective_user.id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("درخواست شارژ", callback_data="w:topup")]
    ])
    await update.message.reply_text(f"💼 موجودی شما: {bal:,} تومان", reply_markup=kb)

async def wallet_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "w:topup":
        await q.message.reply_text("مبلغ شارژ (تومان) را بفرست:", reply_markup=ReplyKeyboardRemove())
        return TOPUP_WAIT_AMOUNT
    return ConversationHandler.END

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if not txt.isdigit():
        await update.message.reply_text("فقط عدد بفرست.")
        return TOPUP_WAIT_AMOUNT
    context.user_data["topup_amount"] = int(txt)
    await update.message.reply_text("رسید/عکس کارت‌به‌کارت را بفرست (اختیاری: بنویس رد):")
    return TOPUP_WAIT_PROOF

async def topup_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif (update.message.text or "").strip() in ("رد", "no", "skip"):
        file_id = None
    amount = context.user_data.pop("topup_amount")
    tg_id = update.effective_user.id

    conn = db_get()
    rid = None
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO wallet_topups (user_id, amount, proof_file_id) VALUES (%s,%s,%s) RETURNING id",
                (tg_id, amount, file_id)
            )
            rid = cur.fetchone()[0]
    finally:
        db_put(conn)

    await update.message.reply_text("✅ درخواست شارژ ثبت شد. پس از تأیید ادمین به موجودی اضافه می‌شود.",
                                    reply_markup=main_kb_for(tg_id))
    # اطلاع به ادمین
    if ADMIN_ID:
        text = f"🔔 درخواست شارژ #{rid}\nکاربر: {tg_id}\nمبلغ: {amount:,}"
        await context.bot.send_message(ADMIN_ID, text)
        if file_id:
            await context.bot.send_photo(ADMIN_ID, file_id, caption=f"رسید شارژ #{rid}")

    return ConversationHandler.END

# ادمین: تایید شارژ
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        return await update.message.reply_text("استفاده: /approve <id>")
    rid = context.args[0]
    conn = db_get()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT user_id, amount, status FROM wallet_topups WHERE id=%s", (rid,))
            row = cur.fetchone()
            if not row:
                return await update.message.reply_text("درخواست پیدا نشد.")
            user_id, amount, status = row
            if status != "pending":
                return await update.message.reply_text("این درخواست قبلاً بررسی شده.")
            # آپدیت
            cur.execute("UPDATE wallet_topups SET status='approved' WHERE id=%s", (rid,))
            cur.execute(
                "INSERT INTO wallets (user_id, balance) VALUES (%s,%s) ON CONFLICT (user_id) DO UPDATE SET balance=wallets.balance + EXCLUDED.balance",
                (user_id, amount)
            )
    finally:
        db_put(conn)

    await update.message.reply_text("✅ تایید شد.")
    try:
        await context.bot.send_message(user_id, f"✅ شارژ کیف پول شما به مبلغ {amount:,} تایید شد.")
    except Exception:
        pass

# ---- پروفایل ----
PROFILE_NAME, PROFILE_PHONE, PROFILE_ADDRESS = range(8, 11)

async def ask_profile_if_needed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اگر کاربر مشخصات نداده، بعد از /start ازش می‌گیریم"""
    u = update.effective_user
    conn = db_get()
    need = False
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT full_name, phone, address FROM users WHERE tg_id=%s", (u.id,))
            full_name, phone, addr = cur.fetchone()
            need = not (full_name and phone and addr)
    finally:
        db_put(conn)

    if need:
        await update.message.reply_text("لطفاً نام و نام‌خانوادگی را بفرست:")
        return PROFILE_NAME
    return ConversationHandler.END

async def prof_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pf_name"] = (update.message.text or "").strip()
    await update.message.reply_text("شماره تماس را بفرست:")
    return PROFILE_PHONE

async def prof_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pf_phone"] = (update.message.text or "").strip()
    await update.message.reply_text("آدرس را بفرست:")
    return PROFILE_ADDRESS

async def prof_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.pop("pf_name")
    phone = context.user_data.pop("pf_phone")
    addr = (update.message.text or "").strip()
    conn = db_get()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET full_name=%s, phone=%s, address=%s WHERE tg_id=%s",
                (name, phone, addr, update.effective_user.id)
            )
    finally:
        db_put(conn)
    await update.message.reply_text("✅ مشخصات ثبت شد.", reply_markup=main_kb_for(update.effective_user.id))
    return ConversationHandler.END

# ---- اینستاگرام (لینک) ----
async def instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("صفحه اینستاگرام: https://instagram.com/yourpage")

# ---- Route by text buttons ----
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt == "منوی محصولات ☕️":
        return await show_menu(update, context)
    if txt == "کیف پول 💸":
        return await wallet_entry(update, context)
    if txt == "اینستاگرام 📱":
        return await instagram(update, context)
    if txt == "افزودن محصول ➕":
        return await add_product_entry(update, context)
    # سایر متن‌ها نادیده
    return

# ------------- Main / Webhook -------------
async def on_startup(app: Application):
    global DB
    DB = SimpleConnectionPool(1, 5, dsn=DATABASE_URL, sslmode="require")
    run_migrations()
    log.info("DB ready & migrations applied.")

def build_app() -> Application:
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

    # start + پروفایل
    application.add_handler(CommandHandler("start", start))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start_profile", ask_profile_if_needed)],
        states={
            PROFILE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, prof_name)],
            PROFILE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, prof_phone)],
            PROFILE_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, prof_address)],
        },
        fallbacks=[CommandHandler("cancel", add_product_cancel)],
        name="profile",
        persistent=False,
    ))

    # افزودن محصول
    application.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن محصول ➕$"), add_product_entry)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            ADD_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, add_product_photo)],
        },
        fallbacks=[CommandHandler("cancel", add_product_cancel)],
        name="add_product",
        persistent=False,
    ))

    # ویرایش محصول
    application.add_handler(CommandHandler("edit", edit_product_entry))
    application.add_handler(ConversationHandler(
        entry_points=[],
        states={
            EDIT_WAIT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_got_id)],
            EDIT_CHOICE: [CallbackQueryHandler(edit_product_choose, pattern=r"^e:")],
            EDIT_NEWVAL: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, edit_product_apply)],
        },
        fallbacks=[CommandHandler("cancel", edit_product_cancel)],
        name="edit_product",
        persistent=False,
    ))

    # منو/عکس محصول
    application.add_handler(MessageHandler(filters.Regex("^منوی محصولات ☕️$"), show_menu))
    application.add_handler(CallbackQueryHandler(product_photo_cb, pattern=r"^p:\d+$"))

    # کیف پول
    application.add_handler(MessageHandler(filters.Regex("^کیف پول 💸$"), wallet_entry))
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(wallet_cb, pattern=r"^w:")],
        states={
            TOPUP_WAIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
            TOPUP_WAIT_PROOF: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, topup_proof)],
        },
        fallbacks=[CommandHandler("cancel", add_product_cancel)],
        name="wallet_topup",
        persistent=False,
    ))
    application.add_handler(CommandHandler("approve", approve))

    # دکمه‌های منو
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    return application

if __name__ == "__main__":
    app = build_app()
    # Webhook؛ پورت باز می‌شود و Render دیگر Port Scan Timeout نمی‌دهد.
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/{WEBHOOK_SECRET}",
        webhook_path=f"/{WEBHOOK_SECRET}",
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
