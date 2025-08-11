# handlers.py
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext
import db

ADMIN_ID = 1606170079  # آیدی ادمین

menu_keyboard = [
    ["/products", "/wallet"],
    ["/order", "/help"]
]

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "سلام! به ربات خوش آمدید.\n"
        "دستورات: /products , /wallet , /order , /help\n"
        "اگر ادمین هستید، برای افزودن محصول بعدا گزینه ادمین اضافه می‌کنیم.",
        reply_markup=ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
    )

def products(update: Update, context: CallbackContext):
    products = "\n".join(db.get_products())
    update.message.reply_text(f"منوی محصولات:\n{products}")

def wallet(update: Update, context: CallbackContext):
    balance = db.get_wallet(update.effective_user.id)
    update.message.reply_text(f"موجودی کیف پول شما: {balance} تومان")

def order(update: Update, context: CallbackContext):
    update.message.reply_text("سفارش شما ثبت شد (دمو)")

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "راهنما:\n"
        "نمایش منو /products\n"
        "کیف پول /wallet\n"
        "ثبت سفارش ساده /order"
    )
