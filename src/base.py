import logging
import os
from telegram.constants import ParseMode
from telegram.ext import Defaults

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.environ.get("LOG_LEVEL", "INFO"),
)
log = logging.getLogger("crepebar")

# ---------- ENV ----------
BOT_TOKEN       = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
PUBLIC_URL      = os.environ.get("PUBLIC_URL") or os.environ.get("WEBHOOK_URL")
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "telegram-secret")
ADMIN_IDS       = {int(x) for x in (os.environ.get("ADMIN_IDS") or "").replace(",", " ").split() if x.isdigit()}
CASHBACK_PERCENT = int(os.environ.get("CASHBACK_PERCENT", "3"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env is missing")
if not PUBLIC_URL:
    raise RuntimeError("PUBLIC_URL env (your Render URL) is missing")

# Defaults: همه پیام‌ها HTML
tg_defaults = Defaults(parse_mode=ParseMode.HTML)
