import os
import logging
from typing import List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler
)

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar-bot")

# ---------- Env ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_BASE = os.environ.get("WEBHOOK_URL")  # e.g. https://bio_crepebar_bot.onrender.com/webhook
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS: List[int] = [int(x) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")
if not WEBHOOK_BASE:
    raise RuntimeError("ENV WEBHOOK_URL is missing (e.g. https://<render-app>.onrender.com/webhook)")

# ---------- Handlers ----------
MAIN_BTNS = [
    [InlineKeyboardButton("🍔 منوی محصولات", callback_data="menu")],
    [InlineKeyboardButton("💼 کیف پول", callback_data="wallet")],
    [InlineKeyboardButton("ℹ️ درباره ما", callback_data="about")],
]

ADMIN_BTNS = [
    [InlineKeyboardButton("➕ افزودن محصول", callback_data="admin:add_product")],
    [InlineKeyboardButton("🛠 مدیریت", callback_data="admin:panel")],
]

def main_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [*MAIN_BTNS]
    if is_admin:
        rows += ADMIN_BTNS
    return InlineKeyboardMarkup(rows)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    is_admin = user and user.id in ADMIN_IDS
    name = (user.full_name if user else "دوست خوبمون")
    await update.effective_message.reply_text(
        f"سلام {name}! 👋\n"
        f"به «بیو کرپ بار» خوش اومدی.",
        reply_markup=main_keyboard(is_admin),
    )

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "menu":
        await query.edit_message_text("لیست محصولات فعلاً نمونه است. بعداً وصل می‌کنیم. ✅")
    elif data == "wallet":
        await query.edit_message_text("کیف پول فعلاً نمونه است. ✅")
    elif data == "about":
        await query.edit_message_text("بیو کرپ بار 🍽\nسفارش‌های خوشمزه در راهه! ✅")
    elif data.startswith("admin:"):
        if update.effective_user and update.effective_user.id in ADMIN_IDS:
            await query.edit_message_text("پنل ادمین (نمونه). ✅")
        else:
            await query.edit_message_text("⛔ این بخش فقط برای ادمین‌هاست.")
    else:
        await query.edit_message_text("گزینه نامعتبر.")

# ---------- App bootstrap ----------
def build_application() -> Application:
    return Application.builder().token(BOT_TOKEN).build()

async def run_webhook(app: Application) -> None:
    """
    از وب‌هوک داخلی PTB استفاده می‌کنیم. این خودش وب‌سرور aiohttp را
    روی PORT رندر بالا می‌آورد و پورت را «باز» نگه‌می‌دارد.
    """
    # مسیر وب‌هوک را /webhook/<token> می‌گذاریم
    url_path = f"webhook/{BOT_TOKEN}"
    webhook_url = f"{WEBHOOK_BASE}/{BOT_TOKEN}"

    port = int(os.environ.get("PORT", "10000"))  # Render PORT injects here

    log.info("Setting webhook to %s", webhook_url)
    await app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=url_path,
        webhook_url=webhook_url,
        # برای اطمینان که برنامه زنده می‌ماند و پورت باز است
        drop_pending_updates=True,
    )

def main() -> None:
    application = build_application()

    # ثبت هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(on_button))

    # اجرای وب‌هوک (بلوک‌کننده)
    # نکته: run_webhook خودش loop را مدیریت می‌کند و برنامه را باز نگه می‌دارد.
    import asyncio
    asyncio.run(run_webhook(application))

if __name__ == "__main__":
    main()
