import os
import logging
from flask import Flask, request
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
import psycopg2
from psycopg2.extras import RealDictCursor

# ----------------- Logging -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- ENV Vars -----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# ----------------- DB Init -----------------
def init_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        user_id BIGINT UNIQUE,
        name TEXT,
        phone TEXT,
        address TEXT,
        wallet INT DEFAULT 0
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name TEXT,
        price INT,
        photo_id TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS music (
        id SERIAL PRIMARY KEY,
        title TEXT,
        file_id TEXT
    );
    """)
    conn.commit()
    cur.close()
    conn.close()

def db_query(query, params=None, fetch=False):
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute(query, params or ())
    data = None
    if fetch:
        data = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()
    return data

# ----------------- Bot Handlers -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db_query("SELECT * FROM users WHERE user_id=%s", (user_id,), fetch=True)
    if not user:
        await update.message.reply_text("👋 خوش آمدید! لطفاً اسم خود را وارد کنید:")
        context.user_data["register_step"] = "name"
        return
    menu = [["📋 منو محصولات", "💰 کیف پول"], ["🎵 موزیک کافه", "ℹ️ اطلاعات من"]]
    if user_id == ADMIN_ID:
        menu.append(["➕ افزودن محصول", "🎼 افزودن موزیک"])
    await update.message.reply_text("منو اصلی:", reply_markup=ReplyKeyboardMarkup(menu, resize_keyboard=True))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    # ثبت کاربر جدید
    if context.user_data.get("register_step") == "name":
        context.user_data["name"] = text
        await update.message.reply_text("📞 شماره تماس خود را بفرستید:")
        context.user_data["register_step"] = "phone"
        return
    elif context.user_data.get("register_step") == "phone":
        context.user_data["phone"] = text
        await update.message.reply_text("🏠 آدرس خود را وارد کنید:")
        context.user_data["register_step"] = "address"
        return
    elif context.user_data.get("register_step") == "address":
        context.user_data["address"] = text
        db_query(
            "INSERT INTO users (user_id, name, phone, address) VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO NOTHING",
            (user_id, context.user_data["name"], context.user_data["phone"], context.user_data["address"])
        )
        await update.message.reply_text("✅ ثبت نام شما تکمیل شد. /start")
        context.user_data.clear()
        return

    # منو
    if text == "📋 منو محصولات":
        products = db_query("SELECT * FROM products", fetch=True)
        if not products:
            await update.message.reply_text("❌ هیچ محصولی ثبت نشده.")
        for p in products:
            if p["photo_id"]:
                await update.message.reply_photo(p["photo_id"], caption=f"{p['name']} - {p['price']} تومان")
            else:
                await update.message.reply_text(f"{p['name']} - {p['price']} تومان")

    elif text == "➕ افزودن محصول" and user_id == ADMIN_ID:
        await update.message.reply_text("نام محصول را وارد کنید:")
        context.user_data["add_product"] = {}
        context.user_data["step"] = "name"

    elif text == "🎵 موزیک کافه":
        music_list = db_query("SELECT * FROM music", fetch=True)
        if not music_list:
            await update.message.reply_text("❌ موزیکی ثبت نشده.")
        for m in music_list:
            await update.message.reply_audio(m["file_id"], caption=m["title"])

    elif text == "🎼 افزودن موزیک" and user_id == ADMIN_ID:
        await update.message.reply_text("عنوان موزیک را وارد کنید:")
        context.user_data["add_music"] = {}
        context.user_data["step"] = "music_title"

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo_id = update.message.photo[-1].file_id

    if context.user_data.get("step") == "photo" and "add_product" in context.user_data:
        context.user_data["add_product"]["photo_id"] = photo_id
        p = context.user_data["add_product"]
        db_query("INSERT INTO products (name, price, photo_id) VALUES (%s, %s, %s)",
                 (p["name"], p["price"], p["photo_id"]))
        await update.message.reply_text("✅ محصول با موفقیت ثبت شد.")
        context.user_data.clear()

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") == "music_file" and "add_music" in context.user_data:
        file_id = update.message.audio.file_id
        m = context.user_data["add_music"]
        db_query("INSERT INTO music (title, file_id) VALUES (%s, %s)", (m["title"], file_id))
        await update.message.reply_text("✅ موزیک ثبت شد.")
        context.user_data.clear()

async def handle_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if context.user_data.get("step") == "price" and "add_product" in context.user_data:
        context.user_data["add_product"]["price"] = int(text)
        await update.message.reply_text("📷 حالا عکس محصول را ارسال کنید:")
        context.user_data["step"] = "photo"
    elif context.user_data.get("step") == "music_title" and "add_music" in context.user_data:
        context.user_data["add_music"]["title"] = text
        await update.message.reply_text("🎵 حالا فایل موزیک را بفرستید:")
        context.user_data["step"] = "music_file"

# ----------------- Flask App -----------------
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), app.telegram_app.bot)
    app.telegram_app.update_queue.put(update)
    return "OK"

# ----------------- Main -----------------
def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    app.telegram_app = application

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    application.add_handler(MessageHandler(filters.Regex(r"^\d+$"), handle_number))

    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path="webhook",
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    main()
