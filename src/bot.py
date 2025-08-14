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
        "پنل مدیریت:", reply_markup=admin_menu_kb()
    )

async def admin_cb(update: Update, context: CallbackContext):
    """هندل کلیک‌های پنل ادمین"""
    q = update.callback_query
    await q.answer()
    if not _is_admin(q.from_user.id):
        return

    data = q.data or ""
    if data == "adm:add":
        context.user_data["ap"] = {}
        await q.message.reply_text(
            "افزودن محصول جدید\n\nنام محصول را بفرست:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return AP_NAME

# ---- مراحل افزودن محصول ----
async def ap_name(update: Update, context: CallbackContext):
    name = (update.effective_message.text or "").strip()
    if not name:
        return AP_NAME
    context.user_data["ap"]["name"] = name
    await update.effective_chat.send_message("قیمت را بفرست (عدد):")
    return AP_PRICE

async def ap_price(update: Update, context: CallbackContext):
    txt = (update.effective_message.text or "").strip().replace(",", "")
    try:
        price = float(txt)
    except Exception:
        await update.effective_chat.send_message("قیمت نامعتبر بود. دوباره قیمت را بفرست (فقط عدد).")
        return AP_PRICE
    context.user_data["ap"]["price"] = price
    await update.effective_chat.send_message("توضیح کوتاه (اختیاری). اگر نمی‌خواهی «-» بفرست:")
    return AP_DESC

async def ap_desc(update: Update, context: CallbackContext):
    desc = (update.effective_message.text or "").strip()
    if desc == "-":
        desc = ""
    context.user_data["ap"]["description"] = desc
    await update.effective_chat.send_message("عکس محصول را بفرست (اختیاری). اگر نمی‌خواهی «-» بفرست:")
    return AP_PHOTO

async def ap_photo(update: Update, context: CallbackContext):
    photo_id: Optional[str] = None
    if update.message and update.message.photo:
        # بزرگ‌ترین سایز
        photo_id = update.message.photo[-1].file_id
    elif (update.message and (update.message.text or "").strip() == "-"):
        photo_id = None
    else:
        await update.effective_chat.send_message("لطفاً یک عکس بفرست یا «-» برای صرف‌نظر.")
        return AP_PHOTO

    context.user_data["ap"]["photo_file_id"] = photo_id
    ap = context.user_data["ap"]

    preview = (
        f"نام: {ap['name']}\n"
        f"قیمت: {toman(ap['price'])}\n"
        f"توضیح: {ap.get('description','') or '—'}\n\n"
        "تأیید می‌کنی؟"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید و ثبت", callback_data="ap:ok"),
         InlineKeyboardButton("❌ انصراف", callback_data="ap:cancel")]
    ])

    if photo_id:
        await update.effective_chat.send_photo(photo=photo_id, caption=preview, reply_markup=kb)
    else:
        await update.effective_chat.send_message(preview, reply_markup=kb)
    return AP_CONFIRM

async def ap_confirm_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()
    if q.data == "ap:cancel":
        await q.message.edit_text("عملیات لغو شد.")
        context.user_data.pop("ap", None)
        return ConversationHandler.END

    ap: Dict[str, Any] = context.user_data.get("ap") or {}
    if not ap:
        await q.message.edit_text("داده‌ای پیدا نشد؛ دوباره تلاش کن.")
        return ConversationHandler.END

    # ثبت در دیتابیس
    try:
        with db._conn() as cn, cn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO products(name, price, description, photo_file_id, is_active)
                VALUES (%s, %s, %s, %s, TRUE)
                """,
                (ap["name"], ap["price"], ap.get("description", ""), ap.get("photo_file_id")),
            )
        await q.message.edit_text("✅ محصول با موفقیت ثبت شد.")
    except Exception as e:
        log.exception("ap_confirm insert failed")
        await q.message.edit_text(f"❌ خطا در ثبت محصول: {e}")
    finally:
        context.user_data.pop("ap", None)
    return ConversationHandler.END

async def ap_fallback(update: Update, context: CallbackContext):
    await update.effective_chat.send_message("لغو شد.")
    context.user_data.pop("ap", None)
    return ConversationHandler.END

# ===========================
# شروع / استارت ساده (fallback اگر handlers.py نبود)
# ===========================
def main_menu_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton("منو 🍭"), KeyboardButton("سفارش 🧾")],
        [KeyboardButton("کیف پول 👛"), KeyboardButton("راهنما ℹ️")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

async def cmd_start(update: Update, context: CallbackContext):
    user = update.effective_user
    try:
        await update.effective_chat.send_message(
            "سلام 😊\nربات فروشگاهی شما آماده است!",
            reply_markup=main_menu_kb(),
        )
        # ثبت/به‌روزرسانی کاربر
        if user:
            await context.application.run_in_threadpool(db.upsert_user, user.id, user.full_name or "")
    except Exception:
        log.exception("start failed")

# ===========================
# ساخت اپلیکیشن و اجرا
# ===========================
def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN/TELEGRAM_TOKEN env is missing.")

    application = Application.builder().token(BOT_TOKEN).build()

    # هندلرهای عمومی پروژه (اگر وجود داشته باشند)
    if build_handlers:
        for h in build_handlers():
            application.add_handler(h)
    else:
        # حداقل /start داشته باشیم
        application.add_handler(CommandHandler("start", cmd_start))

    # پنل ادمین
    application.add_handler(CommandHandler("admin", cmd_admin, filters.User(ADMIN_IDS)))
    application.add_handler(CallbackQueryHandler(admin_cb, pattern=r"^adm:"))

    ap_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_cb, pattern=r"^adm:add$")],
        states={
            AP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_name)],
            AP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_price)],
            AP_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_desc)],
            AP_PHOTO: [
                MessageHandler(filters.PHOTO, ap_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ap_photo),
            ],
            AP_CONFIRM: [CallbackQueryHandler(ap_confirm_cb, pattern=r"^ap:(ok|cancel)$")],
        },
        fallbacks=[MessageHandler(filters.COMMAND, ap_fallback)],
        name="add_product_conv",
        persistent=False,
        allow_reentry=False,
    )
    application.add_handler(ap_conv)

    return application

def main():
    # اطمینان از اجرای مایگریشن/ساخت اسکیمای دیتابیس
    try:
        db.init_db()
    except Exception:
        log.exception("init_db failed (continuing)")

    app = build_app()

    # اگر WEBHOOK_URL تنظیم شده باشد، روی وبهوک اجرا کن؛ وگرنه Polling
    if WEBHOOK_URL:
        log.info("Starting webhook... %s", WEBHOOK_URL)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="",  # از full URL استفاده می‌کنیم
            webhook_url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET,
        )
    else:
        log.info("Starting polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
