import os
import logging

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")

# ====== ENV ======
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
DATABASE_URL = os.getenv("DATABASE_URL", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "WebhookSecret")
PORT = int(os.getenv("PORT", "10000"))

# ادمین‌ها
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(",", " ").split() if x.isdigit()}

# تنظیمات کیف‌پول
DEFAULT_CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "3"))
CARD_NUMBER = os.getenv("CARD_NUMBER", "5029081080984145")  # کارت به کارت

# کلیدهای کیبورد
BTN_MENU = "منو 🍬"
BTN_ORDER = "سفارش 🧾"
BTN_WALLET = "کیف پول 👛"
BTN_GAME = "بازی 🎮"
BTN_HELP = "راهنما ℹ️"
BTN_CONTACT = "ارتباط با ما ☎️"
BTN_WALLET_TOPUP = "شارژ کارت‌به‌کارت"
