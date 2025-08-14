# src/bot.py
import os
from typing import Dict, Any, Optional

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup,
    KeyboardButton, ReplyKeyboardRemove, ParseMode
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, CallbackContext,
    ConversationHandler, CallbackQueryHandler
)

# ماژول‌های پروژه
from .base import log, ADMIN_IDS  # ADMIN_IDS را از env می‌خوانَد
from . import db
try:
    # اگر قبلاً هندلرهای عمومی ساخته‌ایم، اضافه‌شان می‌کنیم
    from .handlers import build_handlers
except Exception:
    build_handlers = None

# ---------------------------
# تنظیمات
# ---------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("WEBHOOK_BASE")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or PUBLIC_URL
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")  # اختیاری
PORT = int(os.environ.get("PORT") or 8000)

# واحد پول
CURRENCY = "تومان"

def toman(n: float) -> str:
    try:
        n = float(n)
    except Exception:
        return f"{n} {CURRENCY}"
    s = f"{int(n):,}".replace(",", "،")
    return f"{s} {CURRENCY}"

# ===========================
# پنل ادمین: افزودن محصول
# ===========================
(
    AP_NAME,
    AP_PRICE,
    AP_DESC,
    AP_PHOTO,
    AP_CONFIRM,
) = range(5)

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def admin_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("➕ افزودن محصول", callback_data="adm:add")],
        # جای خالی برای امکانات بعدی
    ]
    return InlineKeyboardMarkup(rows)

async def cmd_admin(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if not _is_admin(uid):
        return
    await update.effective_chat.send_message(
        "پنل مدیریت:", reply_markup=admin_menu
