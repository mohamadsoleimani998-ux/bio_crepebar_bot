import os
from typing import List

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
CASHBACK_PERCENT = int(os.environ.get("CASHBACK_PERCENT", "0") or 0)

_admin_raw = os.environ.get("ADMIN_IDS", "") or os.environ.get("ADMIN_ID", "")
ADMIN_IDS: List[int] = []
for part in _admin_raw.replace(";", ",").split(","):
    part = part.strip()
    if part.isdigit():
        ADMIN_IDS.append(int(part))

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

START_HELP_TEXT = (
    "سلام! به ربات خوش آمدید.\n"
    "دستورات: /help , /order , /wallet , /products , /contact\n"
    "اگر ادمین هستید، برای افزودن محصول بعداً گزینه ادمین اضافه می‌کنیم."
)

HELP_TEXT = (
    "راهنما:\n"
    "/products نمایش منو\n"
    "/wallet کیف پول\n"
    "/order ثبت سفارش ساده\n"
    "/contact ارتباط با ما\n"
)

CONTACT_TEXT = "ارتباط با ما:\nپیام خود را بفرستید تا برای ادمین ارسال شود."

GAME_TEXT = "بازی: به‌زودی! 🎮"
