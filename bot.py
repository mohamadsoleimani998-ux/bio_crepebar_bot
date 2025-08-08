import logging
import sqlite3
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler
)

import os

# --- تنظیمات ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = 1606170079  # chat_id شما

DB_FILE = "database.db"

# --- لاگ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --- پایگاه داده ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    price INTEGER,
                    photo_id TEXT
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    name TEXT,
                    phone TEXT,
                    address TEXT,
                    wallet INTEGER DEFAULT 0
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    product_id INTEGER,
                    status TEXT,
                    receipt_photo TEXT
                )""")
    conn.commit()
    conn.close()

init_db()

# --- دکمه‌های اصلی ---
def main_menu():
    keyboard = [
        [InlineKeyboardButton("☕ منوی محصولات", callback_data="menu")],
        [InlineKeyboardButton("💸 کیف پول", callback_data="wallet")],
        [InlineKeyboardButton("📱 اینستاگرام", url="https://www.instagram.com/bio.crepebar")],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- استارت ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("به بایو کرپ بار خوش آمدید ☕", reply_markup=main_menu())

# --- نمایش محصولات ---
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, name, price, photo_id FROM products")
    products = c.fetchall()
    conn.close()

    if not products:
        await query.message.reply_text("هنوز محصولی ثبت نشده است.")
        return

    for pid, name, price, photo_id in products:
        if photo_id:
            await query.message.reply_photo(photo=photo_id, caption=f"{name}\n💵 قیمت: {price} تومان",
                                            reply_markup=InlineKeyboardMarkup(
                                                [[InlineKeyboardButton("سفارش", callback_data=f"order:{pid}")]]))
        else:
            await query.message.reply_text(f"{name}\n💵 قیمت: {price} تومان",
                                           reply_markup=InlineKeyboardMarkup(
                                               [[InlineKeyboardButton("سفارش", callback_data=f"order:{pid}")]]))

# --- سفارش ---
USER_NAME, USER_PHONE, USER_ADDRESS, WAIT_RECEIPT = range(4)
user_order = {}

async def order_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.split(":")[1])
    user_order[query.from_user.id] = pid
    await query.message.reply_text("نام خود را وارد کنید:")
    return USER_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    context.user_data["name"] = name
    await update.message.reply_text("شماره تماس خود را وارد کنید:")
    return USER_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    context.user_data["phone"] = phone
    await update.message.reply_text("آدرس خود را وارد کنید:")
    return USER_ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text
    context.user_data["address"] = address

    # ذخیره در DB
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, name, phone, address) VALUES (?, ?, ?, ?)",
              (update.message.from_user.id, context.user_data["name"], context.user_data["phone"], context.user_data["address"]))
    conn.commit()
    conn.close()

    await update.message.reply_text("لطفاً مبلغ را کارت‌به‌کارت کنید و عکس رسید را ارسال کنید:")
    return WAIT_RECEIPT

async def get_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = update.message.photo[-1].file_id
    pid = user_order.get(update.message.from_user.id)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO orders (user_id, product_id, status, receipt_photo) VALUES (?, ?, ?, ?)",
              (update.message.from_user.id, pid, "در انتظار تایید", photo_id))
    conn.commit()
    conn.close()
    await update.message.reply_text("سفارش شما ثبت شد و در انتظار تایید است ✅")
    return ConversationHandler.END

# --- مدیریت محصولات (ادمین) ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    keyboard = [
        [KeyboardButton("➕ افزودن محصول"), KeyboardButton("🗑 حذف محصول")],
        [KeyboardButton("📋 لیست محصولات")]
    ]
    await update.message.reply_text("پنل ادمین:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

ADD_NAME, ADD_PRICE, ADD_PHOTO = range(10, 13)
new_product = {}

async def add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_product["name"] = update.message.text
    await update.message.reply_text("قیمت محصول را وارد کنید:")
    return ADD_PRICE

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_product["price"] = int(update.message.text)
    await update.message.reply_text("عکس محصول را ارسال کنید:")
    return ADD_PHOTO

async def add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_product["photo_id"] = update.message.photo[-1].file_id
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO products (name, price, photo_id) VALUES (?, ?, ?)",
              (new_product["name"], new_product["price"], new_product["photo_id"]))
    conn.commit()
    conn.close()
    await update.message.reply_text("محصول اضافه شد ✅")
    return ConversationHandler.END

# --- ران ---
def main():
    app = Application.builder().token(TOKEN).build()

    # دستورات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_menu, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(order_product, pattern="^order:"))

    app.add_handler(CommandHandler("admin", admin_panel))

    # سفارش
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(order_product, pattern="^order:")],
        states={
            USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            USER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            USER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
            WAIT_RECEIPT: [MessageHandler(filters.PHOTO, get_receipt)],
        },
        fallbacks=[]
    ))

    # افزودن محصول
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ افزودن محصول$"), add_product_name)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            ADD_PHOTO: [MessageHandler(filters.PHOTO, add_product_photo)],
        },
        fallbacks=[]
    ))

    app.run_polling()

if __name__ == "__main__":
    main()
