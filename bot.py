import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# گرفتن توکن از Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")

ADMIN_ID = int(os.getenv("ADMIN_ID", "1606170079"))

# ایجاد دیتابیس
conn = sqlite3.connect("cafe.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    price TEXT,
    photo_id TEXT
)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    product_id INTEGER,
    name TEXT,
    phone TEXT,
    address TEXT
)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS music (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    file_id TEXT
)""")
conn.commit()

# شروع
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("☕ منوی محصولات", callback_data="menu")],
        [InlineKeyboardButton("💰 کیف پول", callback_data="wallet")],
        [InlineKeyboardButton("🎵 موزیک‌های کافه", callback_data="music")],
    ]
    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("➕ افزودن محصول", callback_data="add_product")])
        keyboard.append([InlineKeyboardButton("🎵 افزودن موزیک", callback_data="add_music")])
    await update.message.reply_text("به کافه خوش آمدید ☕", reply_markup=InlineKeyboardMarkup(keyboard))

# دکمه‌ها
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "menu":
        cursor.execute("SELECT id, name, price FROM products")
        products = cursor.fetchall()
        if not products:
            await query.message.reply_text("هنوز محصولی ثبت نشده است.")
            return
        for pid, name, price in products:
            cursor.execute("SELECT photo_id FROM products WHERE id=?", (pid,))
            photo_id = cursor.fetchone()[0]
            caption = f"{name}\n💵 قیمت: {price}"
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("سفارش", callback_data=f"order_{pid}")]])
            await query.message.reply_photo(photo=photo_id, caption=caption, reply_markup=btn)

    elif query.data == "wallet":
        await query.message.reply_text("💳 برای شارژ کیف پول فعلاً کارت به کارت انجام دهید.")

    elif query.data.startswith("order_"):
        pid = int(query.data.split("_")[1])
        context.user_data["product_id"] = pid
        await query.message.reply_text("لطفاً نام خود را وارد کنید:")
        context.user_data["step"] = "name"

    elif query.data == "music":
        cursor.execute("SELECT title, file_id FROM music")
        musics = cursor.fetchall()
        if not musics:
            await query.message.reply_text("هنوز موزیکی ثبت نشده است.")
            return
        for title, file_id in musics:
            await query.message.reply_audio(audio=file_id, title=title)

    elif query.data == "add_product" and query.from_user.id == ADMIN_ID:
        await query.message.reply_text("نام محصول را وارد کنید:")
        context.user_data["step"] = "add_name"

    elif query.data == "add_music" and query.from_user.id == ADMIN_ID:
        await query.message.reply_text("عنوان موزیک را وارد کنید:")
        context.user_data["step"] = "music_title"

# پیام‌های متنی
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "name":
        context.user_data["name"] = update.message.text
        await update.message.reply_text("شماره تماس خود را وارد کنید:")
        context.user_data["step"] = "phone"

    elif step == "phone":
        context.user_data["phone"] = update.message.text
        await update.message.reply_text("آدرس خود را وارد کنید:")
        context.user_data["step"] = "address"

    elif step == "address":
        context.user_data["address"] = update.message.text
        pid = context.user_data["product_id"]
        cursor.execute("INSERT INTO orders (user_id, product_id, name, phone, address) VALUES (?, ?, ?, ?, ?)",
                       (update.effective_user.id, pid, context.user_data["name"], context.user_data["phone"], context.user_data["address"]))
        conn.commit()
        await update.message.reply_text("✅ سفارش شما ثبت شد. برای پرداخت، کارت به کارت انجام دهید.")

    elif step == "add_name" and update.effective_user.id == ADMIN_ID:
        context.user_data["new_product_name"] = update.message.text
        await update.message.reply_text("قیمت محصول را وارد کنید:")
        context.user_data["step"] = "add_price"

    elif step == "add_price" and update.effective_user.id == ADMIN_ID:
        context.user_data["new_product_price"] = update.message.text
        await update.message.reply_text("لطفاً عکس محصول را ارسال کنید:")
        context.user_data["step"] = "add_photo"

    elif step == "music_title" and update.effective_user.id == ADMIN_ID:
        context.user_data["new_music_title"] = update.message.text
        await update.message.reply_text("فایل موزیک را ارسال کنید:")
        context.user_data["step"] = "music_file"

# عکس‌ها
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "add_photo" and update.effective_user.id == ADMIN_ID:
        photo_id = update.message.photo[-1].file_id
        name = context.user_data["new_product_name"]
        price = context.user_data["new_product_price"]
        cursor.execute("INSERT INTO products (name, price, photo_id) VALUES (?, ?, ?)", (name, price, photo_id))
        conn.commit()
        await update.message.reply_text("✅ محصول با موفقیت اضافه شد.")
        context.user_data.clear()

# موزیک
async def music_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "music_file" and update.effective_user.id == ADMIN_ID:
        file_id = update.message.audio.file_id
        title = context.user_data["new_music_title"]
        cursor.execute("INSERT INTO music (title, file_id) VALUES (?, ?)", (title, file_id))
        conn.commit()
        await update.message.reply_text("✅ موزیک با موفقیت اضافه شد.")
        context.user_data.clear()

# اجرای ربات
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
app.add_handler(MessageHandler(filters.AUDIO, music_handler))

if __name__ == "__main__":
    app.run_polling()
