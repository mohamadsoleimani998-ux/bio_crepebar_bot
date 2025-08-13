import logging
import os

from dotenv import load_dotenv

load_dotenv()

# -------- Logging --------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")

# -------- Envs (required) --------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("DB_URL")

# وبهوک
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "hook-secret")  # فقط حروف ساده
PORT = int(os.environ.get("PORT", "10000"))
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("BASE_URL")

# -------- UI texts --------
WELCOME = (
    "سلام! 👋 به ربات بایو کِرپ‌بار خوش اومدی.\n"
    "از دکمه‌های زیر استفاده کن:\n"
    "• منو 🍭: نمایش محصولات با نام و قیمت\n"
    "• سفارش 🧾: ثبت سفارش و مشاهده فاکتور\n"
    "• کیف پول 👛: مشاهده/شارژ، کش‌بک ۳٪ بعد هر خرید\n"
    "• بازی 🎮: سرگرمی\n"
    "• ارتباط با ما ☎️: پیام به ادمین\n"
    "• راهنما ℹ️: دستورات"
)

MAIN_MENU = [
    ["🍭 منو", "🧾 سفارش"],
    ["👛 کیف پول", "🎮 بازی"],
    ["☎️ ارتباط با ما", "ℹ️ راهنما"],
]

# صفحه‌بندی منو
PAGE_SIZE = 6

# علامت پول
CURRENCY = "تومان"

def fmt_money(v):
    try:
        v = int(v)
    except Exception:
        v = float(v or 0)
    return f"{v:,} {CURRENCY}"
