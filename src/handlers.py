import requests
from .base import BOT_TOKEN, RENDER_URL
from .db import init_db, get_or_create_user, get_wallet, list_products

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def _send(chat_id: int, text: str):
    try:
        requests.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": text})
    except Exception as e:
        print("sendMessage error:", e)

def startup_warmup():
    """در استارتاپ: DB را آماده کن و اگر URL رندر موجود بود، وبهوک را ست کن."""
    try:
        init_db()
        print("DB init OK")
    except Exception as e:
        print("init_db error:", e)

    try:
        if RENDER_URL:
            wh = f"{RENDER_URL}/webhook"
            r = requests.post(f"{API}/setWebhook", json={"url": wh})
            print("setWebhook:", r.status_code, r.text)
        else:
            print("RENDER_EXTERNAL_URL not set -> skip setWebhook")
    except Exception as e:
        print("setWebhook error:", e)

async def handle_update(update: dict):
    """هندلر اصلی وبهوک (ساده و مقاوم)."""
    try:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return  # چیز قابل پردازش نیست

        from_user = message.get("from", {}) or {}
        chat_id   = message["chat"]["id"]
        text      = (message.get("text") or "").strip()

        # کاربر را ثبت/واکشی کن
        try:
            get_or_create_user(from_user)
        except Exception as e:
            print("get_or_create_user error:", e)

        if text.startswith("/start"):
            _send(chat_id,
                  "سلام! به ربات خوش آمدید.\n"
                  "دستورات: /products , /wallet/\n"
                  "اگر ادمین هستید، برای افزودن محصول بعدا گزینه ادمین اضافه می‌کنیم.")
            return

        if text.startswith("/wallet"):
            cents = 0
            try:
                cents = get_wallet(from_user.get("id"))
            except Exception as e:
                print("get_wallet error:", e)
            toman = cents // 100
            _send(chat_id, f"موجودی کیف پول شما: {toman} تومان")
            return

        if text.startswith("/products"):
            items = []
            try:
                items = list_products()
            except Exception as e:
                print("list_products error:", e)
            if not items:
                _send(chat_id, "هنوز محصولی ثبت نشده است.")
            else:
                lines = [f"{p['id']}. {p['title']} - {p['price_cents']//100} تومان" for p in items]
                _send(chat_id, "محصولات:\n" + "\n".join(lines))
            return

        # پیش‌فرض
        _send(chat_id, "دستور ناشناخته است. از /start استفاده کنید.")
    except Exception as e:
        print("handle_update error:", e)
