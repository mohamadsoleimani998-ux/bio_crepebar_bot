from . import db
from .base import send_message, send_menu
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext

async def handle_update(update: Update, context: CallbackContext):
    """مدیریت همه پیام‌ها"""
    text = update.message.text if update.message else ""

    if text == "/start":
        await send_message(update, context, "به ربات کافی‌شاپ خوش آمدید ☕️")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="لطفاً از منوی زیر انتخاب کنید:",
            reply_markup=send_menu()
        )
    elif text == "/products":
        await send_message(update, context, "📋 لیست محصولات در حال حاضر آماده نیست.")
    elif text == "/wallet":
        await send_message(update, context, "💰 موجودی کیف پول شما: 0 تومان")
    else:
        await send_message(update, context, "دستور نامعتبر است. از منوی زیر استفاده کنید.")

async def startup_warmup(app):
    print("ربات با موفقیت راه‌اندازی شد ✅")
