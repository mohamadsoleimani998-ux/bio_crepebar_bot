import os
import json
import hmac
import hashlib
import logging
from typing import Any, Dict

from flask import Flask, request, Response
import requests

# ------------------ تنظیمات پایه ------------------
BOT_TOKEN = os.environ["BOT_TOKEN"].strip()

# اگر WEBHOOK_URL هست از همون استفاده کن؛ وگرنه از WEBHOOK_BASE بساز
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
if not WEBHOOK_URL:
    base = os.environ.get("WEBHOOK_BASE", "").rstrip("/")
    if not base:
        raise RuntimeError("WEBHOOK_BASE or WEBHOOK_URL must be set in Environment.")
    WEBHOOK_URL = f"{base}/webhook"

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip() or None

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TIMEOUT = 15  # ثانیه

# ------------------ لاگینگ ------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("crepebar-bot")

# ------------------ اپ Flask ------------------
app = Flask(__name__)

# صفحه سلامت برای Render
@app.get("/")
def health() -> str:
    return "OK", 200

# ثبت وبهوک (idempotent)
def ensure_webhook() -> None:
    try:
        # چک کن وبهوک فعلی چیه
        info = requests.get(f"{TG_API}/getWebhookInfo", timeout=TIMEOUT).json()
        current = info.get("result", {}).get("url") if info.get("ok") else ""
        if current != WEBHOOK_URL:
            payload = {"url": WEBHOOK_URL}
            if WEBHOOK_SECRET:
                payload["secret_token"] = WEBHOOK_SECRET
            r = requests.post(f"{TG_API}/setWebhook", json=payload, timeout=TIMEOUT)
            r.raise_for_status()
            log.info("Webhook set to %s", WEBHOOK_URL)
        else:
            log.info("Webhook already set.")
    except Exception as e:
        log.exception("Failed to set webhook: %s", e)

# هنگام استارت اپ یک بار تلاش کن وبهوک ست شود
with app.app_context():
    ensure_webhook()

# ------------------ کمک‌تابع‌های Bot API ------------------
def tg_send(chat_id: int, text: str, reply_markup: Dict[str, Any] | None = None) -> None:
    data: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(f"{TG_API}/sendMessage", data=data, timeout=TIMEOUT)
    except Exception as e:
        log.exception("sendMessage failed: %s", e)

def main_menu_kb() -> Dict[str, Any]:
    # کیبورد ساده؛ می‌تونی عناوین را بعداً عوض کنی
    return {
        "keyboard": [
            [{"text": "منو و سفارش"}, {"text": "تخفیف من"}],
            [{"text": "آدرس و تماس"}, {"text": "راهنما"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }

# تأیید صحت هدر secret (اختیاری)
def verify_secret(req: request) -> bool:
    if not WEBHOOK_SECRET:
        return True
    sig = req.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    return hmac.compare_digest(sig, WEBHOOK_SECRET)

# ------------------ وبهوک ------------------
@app.post("/webhook")
def webhook() -> Response:
    if not verify_secret(request):
        return Response("forbidden", status=403)

    try:
        update = request.get_json(force=True, silent=False)
    except Exception:
        return Response("bad request", status=400)

    # فقط پیام‌های متنی را پوشش بدهیم
    message = (update or {}).get("message") or (update or {}).get("edited_message")
    if not message:
        return Response("no message", status=200)

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id:
        return Response("no chat", status=200)

    # دستورات اصلی
    if text.startswith("/start"):
        tg_send(
            chat_id,
            "سلام! 👋\nبه <b>کِرپ بار</b> خوش اومدی.\nاز کیبورد پایین یکی رو انتخاب کن.",
            reply_markup=main_menu_kb(),
        )
    elif text == "منو و سفارش":
        tg_send(
            chat_id,
            "منو فعلاً ساده است:\n• کرپ نوتلا — ۱۹۰\n• کرپ موز-نوتلا — ۲۲۰\nبرای سفارش، همینجا پیام بده. (نسخه ساده)",
        )
    elif text == "تخفیف من":
        tg_send(chat_id, "کش‌بک پیش‌فرض شما ۳٪ است. 👌")
    elif text == "آدرس و تماس":
        tg_send(chat_id, "تهران، ...\n☎️ 09xx xxx xxxx\nساعت کاری: ۱۰ تا ۲۳")
    elif text == "راهنما":
        tg_send(chat_id, "دستورات: /start\nیا از دکمه‌ها استفاده کن.")
    else:
        # پاسخ پیش‌فرض
        tg_send(chat_id, "دستور نامعتبر بود. از دکمه‌های پایین استفاده کن 🙂", reply_markup=main_menu_kb())

    return Response("ok", status=200)

# ------------------ ورودی Gunicorn ------------------
# در Procfile از `gunicorn bot:app` استفاده می‌کنی، پس این «app» باید اکسپورت شود.
# هیچ حلقهٔ رویدادی اجرا نمی‌کنیم تا خطاهای event loop اتفاق نیفتد.
