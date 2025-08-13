# src/base.py
import os
import logging
from typing import List

try:
    # اگر python-dotenv نصب باشد، متغیرهای .env را نیز لود می‌کنیم
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---------------------------
# تنظیمات محیط (ENV)
# ---------------------------
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN env is missing (TELEGRAM_TOKEN / BOT_TOKEN).")

# آدرس پابلیک برای وبهوک (Render یا هر میزبان دیگر)
PUBLIC_URL = (
    os.getenv("PUBLIC_URL")
    or os.getenv("WEBHOOK_URL")
    or os.getenv("WEBHOOK_BASE")
    or ""
).strip()

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "T3legramWebhookSecret_2025")
PORT = int(os.getenv("PORT", "10000"))

# دیتابیس در db.py استفاده می‌شود (اینجا فقط برای اطلاع)
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DB_URL")

# ادمین‌ها (با کاما/فاصله جدا)
def _parse_admins(raw: str | None) -> List[int]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace(",", " ").split()]
    out: List[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except Exception:
            pass
    return out

ADMIN_IDS: List[int] = _parse_admins(os.getenv("ADMIN_IDS"))

# شماره کارت برای شارژ کارت‌به‌کارت
CARD_NUMBER = os.getenv("CARD_NUMBER", "5029081080984145")

# تعداد نمایش آیتم منو در هر صفحه
PAGE_SIZE_PRODUCTS = int(os.getenv("PAGE_SIZE_PRODUCTS", "6"))

# درصد کش‌بک برای نمایش داخل پیام‌ها (تریگر واقعی از جدول settings می‌خوانَد)
CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "3"))

# واحد پول
CURRENCY = os.getenv("CURRENCY_FA", "تومان")

# ---------------------------
# تنظیم لاگ
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")

# ---------------------------
# کمک‌تابع‌های کاربردی
# ---------------------------
def fmt_amount(n: float | int) -> str:
    """فرمت اعداد پولی به صورت 12,345"""
    try:
        return f"{int(round(float(n))):,}"
    except Exception:
        return str(n)

def toman(n: float | int) -> str:
    return f"{fmt_amount(n)} {CURRENCY}"

# متن/برچسب‌های فارسی
LBL_MENU     = "منو 🍭"
LBL_ORDER    = "سفارش 🧾"
LBL_WALLET   = "کیف پول 👛"
LBL_GAME     = "بازی 🎮"
LBL_CONTACT  = "ارتباط با ما ☎️"
LBL_HELP     = "راهنما ℹ️"
LBL_INVOICE  = "مشاهده فاکتور 🧾"
LBL_BACK     = "بازگشت ⬅️"
LBL_NEXT     = "بعدی ➡️"
LBL_PREV     = "قبلی ⬅️"

# برای کیبوردهای Reply
def main_reply_keyboard() -> list[list[str]]:
    """آرایش دکمه‌های اصلی (برای ReplyKeyboardMarkup در handlers.py استفاده کن)"""
    return [
        [LBL_MENU, LBL_ORDER],
        [LBL_WALLET, LBL_GAME],
        [LBL_CONTACT, LBL_HELP],
    ]
