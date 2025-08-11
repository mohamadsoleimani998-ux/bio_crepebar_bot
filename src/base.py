from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext

async def send_message(update: Update, context: CallbackContext, text: str):
    """ارسال پیام به کاربر"""
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)

def send_menu():
    """ارسال منوی اصلی"""
    return ReplyKeyboardMarkup(
        [["/products", "/wallet"], ["/order", "/help"]],
        resize_keyboard=True
    )
