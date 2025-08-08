import os
import sqlite3
import telebot
from telebot import types
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading

# دریافت توکن از متغیر محیطی
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 1606170079  # آیدی عددی ادمین

bot = telebot.TeleBot(BOT_TOKEN)

# اتصال به دیتابیس
conn = sqlite3.connect("products.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    photo_id TEXT
)
""")
conn.commit()

# دکمه‌ها
def main_menu(is_admin=False):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("☕ منوی محصولات", "💰 کیف پول", "📱 اینستاگرام")
    if is_admin:
        markup.add("➕ افزودن محصول")
    return markup

# استارت
@bot.message_handler(commands=['start'])
def start(message):
    is_admin = (message.from_user.id == ADMIN_ID)
    bot.send_message(message.chat.id, "به بایو کرپ بار خوش آمدید ☕", reply_markup=main_menu(is_admin))

# منوی محصولات
@bot.message_handler(func=lambda m: m.text == "☕ منوی محصولات")
def show_products(message):
    cursor.execute("SELECT name, photo_id FROM products")
    products = cursor.fetchall()
    if not products:
        bot.send_message(message.chat.id, "هنوز محصولی ثبت نشده است.")
    else:
        for name, photo_id in products:
            if photo_id:
                bot.send_photo(message.chat.id, photo_id, caption=name)
            else:
                bot.send_message(message.chat.id, name)

# افزودن محصول (فقط ادمین)
@bot.message_handler(func=lambda m: m.text == "➕ افزودن محصول" and m.from_user.id == ADMIN_ID)
def add_product_step1(message):
    bot.send_message(message.chat.id, "نام محصول را وارد کنید:")
    bot.register_next_step_handler(message, add_product_step2)

def add_product_step2(message):
    product_name = message.text
    bot.send_message(message.chat.id, "عکس محصول را ارسال کنید:")
    bot.register_next_step_handler(message, add_product_step3, product_name)

def add_product_step3(message, product_name):
    if message.content_type == 'photo':
        photo_id = message.photo[-1].file_id
        cursor.execute("INSERT INTO products (name, photo_id) VALUES (?, ?)", (product_name, photo_id))
        conn.commit()
        bot.send_message(message.chat.id, f"✅ محصول '{product_name}' اضافه شد.")
    else:
        bot.send_message(message.chat.id, "❌ لطفاً عکس ارسال کنید.")

# وب‌سرور ساده برای Render
def run_server():
    port = int(os.environ.get("PORT", 5000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_server).start()
    bot.polling(none_stop=True)
