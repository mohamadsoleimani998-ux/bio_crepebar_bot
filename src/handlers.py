# src/handlers.py
import logging
from typing import List

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
)

# ایمپورت دیتابیس از پکیج src
try:
    from src import db
except Exception as e:
    # اگر ساختار قبلی متفاوت بود، حداقل لاگ بدهیم
    logging.getLogger(__name__).warning("DB import warning: %s", e)

log = logging.getLogger(__name__)

# ------------- /start -------------
START_MENU_BUTTONS: List[List[KeyboardButton]] = [
    [KeyboardButton("🍽️ منو"), KeyboardButton("🧾 سفارش")],
    [KeyboardButton("👛 کیف پول"), KeyboardButton("🎮 بازی")],
    [KeyboardButton("📞 ارتباط با ما"), KeyboardButton("ℹ️ راهنما")],
]

START_TEXT = (
    "سلام! 👋 به ربات بایو کرپ بار خوش اومدی.\n"
    "از دکمه‌های زیر استفاده کن:\n"
    "• 🍽️ منو: نمایش محصولات با اسم، قیمت و عکس\n"
    "• 🧾 سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
    "• 👛 کیف پول: مشاهده و شارژ (کارت‌به‌کارت / درگاه در آینده)\n"
    "• 🎯 کش‌بک: بعد از هر خرید به کیف پول اضافه می‌شود\n"
    "• 🎮 بازی: تب سرگرمی\n"
    "• 📞 ارتباط با ما: پیام به ادمین\n"
)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پاسخ مطمئن به /start + تلاش برای ثبت/بروزرسانی کاربر و ایجاد جداول در صورت نیاز."""
    # سعی در اطمینان از وجود جداول (اگر db.init_db داشته باشیم)
    try:
        if hasattr(db, "init_db"):
            db.init_db()
    except Exception as e:
        log.warning("init_db() failed (will continue): %s", e)

    # ثبت یا بروزرسانی کاربر
    try:
        if update.effective_user and hasattr(db, "upsert_user"):
            db.upsert_user(update.effective_user.id, update.effective_user.full_name)
    except Exception as e:
        log.warning("upsert_user failed: %s", e)

    kb = ReplyKeyboardMarkup(START_MENU_BUTTONS, resize_keyboard=True)
    await update.message.reply_text(START_TEXT, reply_markup=kb)

# ------------- راهنما (/help) -------------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "راهنما:\n"
        "• /start — شروع و نمایش منو\n"
        "• /products — نمایش منو محصولات\n"
        "• /order — ثبت سفارش\n"
        "• /wallet — مشاهده کیف پول و شارژ\n"
        "• /contact — ارسال پیام به ادمین\n"
    )
    await update.message.reply_text(text)

# ------------- رجیستر هندلرها در اپ -------------
def register(application: Application) -> None:
    """
    این تابع فقط هندلرهای سراسری را اضافه می‌کند.
    بقیه‌ی هندلرهایی که از قبل در همین فایل تعریف کرده بودی می‌توانند همین‌جا به app اضافه شوند.
    """

    # اطمینان از لاگ
    log.setLevel(logging.INFO)

    # حتماً /start و /help رجیستر شوند
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))

    # ⚠️ اگر پایین‌تر در همین فایل هندلرهای دیگری دارید (products/order/wallet/...)
    # همان‌ها را هم اینجا application.add_handler(...) کنید تا فعال بمانند.
    #
    # مثال‌ها (اگر از قبل داری، دوباره نساز—فقط مطمئن شو add_handler شده‌اند):
    # application.add_handler(CommandHandler("products", products_cmd))
    # application.add_handler(CommandHandler("order", order_cmd))
    # application.add_handler(CommandHandler("wallet", wallet_cmd))
    # application.add_handler(CommandHandler("contact", contact_cmd))
    # application.add_handler(CommandHandler("game", game_cmd))

    log.info("Handlers registered: /start, /help (+ your custom handlers)")
