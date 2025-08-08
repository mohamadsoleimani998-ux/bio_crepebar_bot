import os, sqlite3, json, asyncio
from contextlib import closing
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)

# ---------- تنظیمات ----------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN/TELEGRAM_BOT_TOKEN is missing")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
INSTAGRAM_URL = os.getenv("INSTAGRAM_URL", "https://www.instagram.com/bio.crepebar")

DB_PATH = os.getenv("SQLITE_PATH", "db.sqlite3")

# ---------- DB ----------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(db()) as conn, conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS products(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          price INTEGER NOT NULL,
          photo_file_id TEXT
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
          user_id INTEGER PRIMARY KEY,
          full_name TEXT,
          phone TEXT,
          address TEXT,
          wallet INTEGER DEFAULT 0
        )""")

# ---------- کمک‌تابع ----------
def is_admin(user_id: int) -> bool:
    return ADMIN_ID and user_id == ADMIN_ID

def main_keyboard(is_admin_flag=False):
    rows = [
        [KeyboardButton("منوی محصولات ☕️"), KeyboardButton("کیف پول 💸")],
        [KeyboardButton("اینستاگرام 📱➜")]
    ]
    if is_admin_flag:
        rows.append([KeyboardButton("افزودن محصول ✚")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    # ساخت/به‌روزرسانی کاربر
    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id, full_name) VALUES(?,?)",
            (u.id, (u.full_name or u.username or "")),
        )
    await update.message.reply_text(
        "☕️ به بایو کرپ بار خوش آمدی",
        reply_markup=main_keyboard(is_admin(u.id))
    )

async def open_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"اینستاگرام: {INSTAGRAM_URL}")

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with closing(db()) as conn:
        row = conn.execute("SELECT wallet FROM users WHERE user_id=?", (uid,)).fetchone()
    balance = row["wallet"] if row else 0
    await update.message.reply_text(f"موجودی کیف پول شما: {balance} تومان")

# ---------- لیست محصولات ----------
async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with closing(db()) as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()

    if not rows:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.")
        return

    # ارسال به‌صورت یکجا
    lines = []
    media = []
    for r in rows:
        lines.append(f"#{r['id']} • {r['name']} — {r['price']} تومان")
        if r["photo_file_id"]:
            try:
                media.append(InputMediaPhoto(media=r["photo_file_id"], caption=f"{r['name']} — {r['price']} تومان"))
            except Exception:
                pass

    await update.message.reply_text("\n".join(lines))
    if media:
        # آلبوم ۱۰تایی بفرستیم
        chunk = media[:10]
        try:
            await update.message.reply_media_group(chunk)
        except Exception:
            pass

# ---------- افزودن محصول (فقط ادمین) ----------
ASK_NAME, ASK_PRICE, ASK_PHOTO = range(3)

async def add_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ این بخش مخصوص مدیر است.")
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("نام محصول را وارد کن:", reply_markup=ReplyKeyboardRemove())
    return ASK_NAME

async def add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = (update.message.text or "").strip()
    if not context.user_data["name"]:
        await update.message.reply_text("نام معتبر وارد کن.")
        return ASK_NAME
    await update.message.reply_text("قیمت محصول (تومان) را وارد کن:")
    return ASK_PRICE

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").replace(",", "").strip()
    if not txt.isdigit():
        await update.message.reply_text("قیمت باید عدد باشد. دوباره بفرست.")
        return ASK_PRICE
    context.user_data["price"] = int(txt)
    await update.message.reply_text("عکس محصول را بفرست (یا «رد کردن» را تایپ کن):")
    return ASK_PHOTO

async def add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = None
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    elif (update.message.text or "").strip() == "رد کردن":
        photo_id = None
    else:
        await update.message.reply_text("یک تصویر بفرست یا بنویس «رد کردن».")
        return ASK_PHOTO

    with closing(db()) as conn, conn:
        conn.execute(
            "INSERT INTO products(name, price, photo_file_id) VALUES(?,?,?)",
            (context.user_data["name"], context.user_data["price"], photo_id),
        )

    await update.message.reply_text("✅ محصول با موفقیت ثبت شد.", reply_markup=main_keyboard(is_admin(update.effective_user.id)))
    return ConversationHandler.END

async def add_product_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=main_keyboard(is_admin(update.effective_user.id)))
    return ConversationHandler.END

# ---------- روت‌های ساده ----------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start")

# ---------- اجرای وبهوک روی Render ----------
async def run():
    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    # دستورات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))

    # کانورسیشن افزودن محصول
    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن محصول ✚$"), add_product_entry)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            ASK_PHOTO: [
                MessageHandler(filters.PHOTO, add_product_photo),
                MessageHandler(filters.Regex("^رد کردن$") | (filters.TEXT & ~filters.COMMAND), add_product_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_product_cancel)],
        name="add_product",
        persistent=False,
    )
    application.add_handler(add_conv)

    # منوها
    application.add_handler(MessageHandler(filters.Regex("^منوی محصولات ☕️$"), list_products))
    application.add_handler(MessageHandler(filters.Regex("^کیف پول 💸$"), show_wallet))
    application.add_handler(MessageHandler(filters.Regex("^اینستاگرام 📱➜$"), open_instagram))
    application.add_handler(MessageHandler(filters.Regex("^افزودن محصول ✚$"), add_product_entry))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, start))

    # آدرس پابلیک
    public_url = os.getenv("PUBLIC_URL")
    if not public_url:
        host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
        if not host:
            raise RuntimeError("PUBLIC_URL یا RENDER_EXTERNAL_HOSTNAME تنظیم نشده است.")
        public_url = f"https://{host}"

    port = int(os.getenv("PORT", "10000"))
    webhook_path = f"/webhook/{BOT_TOKEN}"

    # ست وبهوک و اجرا
    await application.bot.set_webhook(url=public_url + webhook_path)
    await application.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=public_url + webhook_path,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except RuntimeError as e:
        # برای موارد ری‌استارت سریع Render که loop بسته شده
        if "Event loop is closed" in str(e):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run())
        else:
            raise
