import os
import logging
from flask import Flask, request
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app for webhook
app = Flask(__name__)

# DB Connection
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# Start command
async def start(update: Update, context: CallbackContext):
    user = update.message.from_user
    await update.message.reply_text(
        f"سلام {user.first_name} 🌟\n"
        "به ربات کافی‌شاپ خوش اومدی!"
    )

# Add product (admin only)
async def add_product(update: Update, context: CallbackContext):
    if str(update.message.from_user.id) != os.getenv("ADMIN_ID"):
        await update.message.reply_text("⛔ فقط ادمین می‌تواند محصول اضافه کند.")
        return
    try:
        name = context.args[0]
        price = context.args[1]
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO products (name, price) VALUES (%s, %s)", (name, price))
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text("✅ محصول اضافه شد.")
    except:
        await update.message.reply_text("❌ خطا در افزودن محصول. فرمت: /addproduct اسم قیمت")

# List products
async def list_products(update: Update, context: CallbackContext):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products")
    products = cur.fetchall()
    cur.close()
    conn.close()
    if not products:
        await update.message.reply_text("📭 محصولی ثبت نشده است.")
        return
    msg = "📋 لیست محصولات:\n"
    for p in products:
        msg += f"{p['id']}. {p['name']} - {p['price']} تومان\n"
    await update.message.reply_text(msg)

# Flask route for webhook
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok"

@app.route("/")
def index():
    return "Bot is running!"

# Application
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("addproduct", add_product))
application.add_handler(CommandHandler("products", list_products))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
