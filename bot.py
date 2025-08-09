# bot.py
import os
import time
import logging
from typing import Any, Dict

from flask import Flask, request, jsonify
import requests

# =========================
# تنظیمات و لاگ‌برداری
# =========================
SERVICE_TAG = "crepebar-bot"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | INFO | " + SERVICE_TAG + " | %(message)s",
)
log = logging.getLogger(SERVICE_TAG)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_BASE = (os.getenv("WEBHOOK_BASE") or "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
# در صورت تعریف بودن وبهوک کامل، از همان استفاده می‌کنیم
ENV_WEBHOOK_URL = (os.getenv("WEBHOOK_URL") or "").strip()

if not BOT_TOKEN:
    log.warning("BOT_TOKEN is empty! The app will run, but Telegram handlers won't work.")

# URL نهایی وبهوک
if ENV_WEBHOOK_URL:
    TARGET_WEBHOOK_URL = ENV_WEBHOOK_URL.rstrip("/")
elif WEBHOOK_BASE and WEBHOOK_SECRET:
    TARGET_WEBHOOK_URL = f"{WEBHOOK_BASE}/webhook/{WEBHOOK_SECRET}"
else:
    TARGET_WEBHOOK_URL = ""

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)


# =========================
# Health & Root
# =========================
@app.get("/health")
def health() -> Any:
    return jsonify({"status": "ok"}), 200


@app.get("/")
def root() -> Any:
    # فقط برای اینکه Render/Load Balancer پاسخ 200 بگیرد
    return "OK", 200


# =========================
# Webhook Handler
# =========================
@app.post("/webhook/<secret>")
def telegram_webhook(secret: str):
    # اگر سکرت نادرست بود، 404 بده تا لو نرود
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        return "Not Found", 404

    if not BOT_TOKEN:
        log.error("Incoming update but BOT_TOKEN is empty.")
        return "BOT_TOKEN missing", 500

    update: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    message = (update.get("message") or update.get("edited_message") or {})
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id:
        return "No chat", 200  # پاسخ 200 تا تلگرام دوباره نفرستد

    # منطق ساده‌ی فعلی: /start و Echo
    if text.startswith("/start"):
        reply = "👋 سلام Mes\nربات فعاله. برای تست، هر متنی بفرست تا برگردونم."
    else:
        reply = text or "..."

    try:
        r = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": reply},
            timeout=10,
        )
        if r.status_code != 200:
            log.error("sendMessage failed: %s - %s", r.status_code, r.text)
    except requests.RequestException as e:
        log.exception("sendMessage exception: %s", e)

    return "OK", 200


# =========================
# Webhook Idempotent Setup
# =========================
def _ensure_webhook():
    """ست‌کردن وبهوک فقط در صورت نیاز + هندل Flood/RetryAfter."""
    if not BOT_TOKEN or not TARGET_WEBHOOK_URL:
        if not TARGET_WEBHOOK_URL:
            log.warning("WEBHOOK URL is empty. Skipping setWebhook.")
        return

    info_url = f"{TELEGRAM_API}/getWebhookInfo"
    set_url = f"{TELEGRAM_API}/setWebhook"

    try:
        gi = requests.get(info_url, timeout=10)
        current_url = ""
        if gi.ok:
            current_url = (gi.json().get("result") or {}).get("url", "")
        else:
            log.warning("getWebhookInfo failed: %s - %s", gi.status_code, gi.text)

        if current_url == TARGET_WEBHOOK_URL:
            log.info("Webhook already set to target. (idempotent)")
            return

        payload = {
            "url": TARGET_WEBHOOK_URL,
            # اگر بخواهی می‌تونی certificate/allowed_updates و ... هم اضافه کنی
        }

        # چند تلاش با Backoff کوتاه برای خطای Flood control
        for attempt in range(4):
            resp = requests.post(set_url, json=payload, timeout=15)
            if resp.ok and (resp.json().get("ok") is True):
                log.info("Webhook set to: %s", TARGET_WEBHOOK_URL)
                return

            data = {}
            try:
                data = resp.json()
            except Exception:
                pass

            # RetryAfter
            params = (data.get("parameters") or {})
            retry_after = params.get("retry_after")
            if retry_after:
                wait_s = int(retry_after)
                wait_s = min(max(wait_s, 1), 10)  # بین 1 تا 10 ثانیه
                log.warning("Flood control: retry in %s sec...", wait_s)
                time.sleep(wait_s)
                continue

            log.error("setWebhook failed (attempt %s): %s - %s", attempt + 1, resp.status_code, resp.text)
            time.sleep(1)

    except requests.RequestException as e:
        log.exception("ensure_webhook exception: %s", e)


# =========================
# Error handler (Flask level)
# =========================
@app.errorhandler(Exception)
def on_flask_error(e):
    log.exception("Flask error: %s", e)
    # پاسخ 200 ندهیم که باعث تکرار بی‌پایان نشود؛ 500 کافی است
    return "Internal Server Error", 500


# =========================
# Startup hook
# =========================
with app.app_context():
    _ensure_webhook()


# برای اجرای لوکال (اختیاری)
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
