import os
import logging

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("crepebar")

# ---- Env ----
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PUBLIC_URL = (os.getenv("WEBHOOK_URL") or os.getenv("PUBLIC_URL") or "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
PORT = int(os.getenv("PORT", "10000"))

# ادمین‌ها (با کاما جدا شده)
def _parse_admins(v: str):
    if not v:
        return set()
    return {int(x.strip()) for x in v.split(",") if x.strip().lstrip("-").isdigit()}

ADMIN_IDS = _parse_admins(os.getenv("ADMIN_IDS", ""))

# درصد کش‌بک پیش‌فرض
DEFAULT_CASHBACK = int(os.getenv("CASHBACK_PERCENT", "3"))

# شماره کارت برای شارژ کیف‌پول (کارت به کارت)
CARD_NUMBER = os.getenv("CARD_NUMBER", "5029081080984145")

# متن‌های آماده
WELCOME_TEXT = (
    "سلام! 👋 به ربات بایو کرِپ‌بار خوش اومدی.\n"
    "از دکمه‌های زیر استفاده کن:\n"
    "• منو: نمایش محصولات با نام، قیمت و عکس\n"
    "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
    "• کیف پول: مشاهده/شارژ، کش‌بک {cb}% بعد هر خرید\n"
    "• بازی: سرگرمی\n"
    "• ارتباط با ما: پیام به ادمین\n"
    "• راهنما: دستورها"
).format(cb=DEFAULT_CASHBACK)

MAIN_KEYBOARD = [
    ["🍬 منو", "🧾 سفارش"],
    ["👛 کیف پول", "🎮 بازی"],
    ["📞 ارتباط با ما", "ℹ️ راهنما"],
]
