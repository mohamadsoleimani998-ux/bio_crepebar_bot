import os
import requests

from db import init_db, get_or_create_user, get_wallet, list_products, add_product

BOT_TOKEN = os.getenv("BOT_TOKEN")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

ADMIN_IDS = set()
_raw_admins = os.getenv("ADMIN_IDS", "")
if _raw_admins:
    for x in _raw_admins.replace(",", " ").split():
        try:
            ADMIN_IDS.add(int(x))
        except Exception:
            pass

def _send_text(chat_id: int, text: str, reply_to: int | None = None):
    try:
        requests.post(f"{API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "reply_to_message_id": reply_to
        }, timeout=8)
    except Exception as e:
        print("sendMessage err:", e)

def _send_photo(chat_id: int, file_id: str, caption: str = ""):
    try:
        requests.post(f"{API}/sendPhoto", json={
            "chat_id": chat_id,
            "photo": file_id,
            "caption": caption
        }, timeout=10)
    except Exception as e:
        print("sendPhoto err:", e)

async def handle_update(update: dict):
    # ایمن: اگر DB آماده نبود، اینجا هم کرش نمی‌کنیم
    try:
        init_db()
    except Exception as e:
        print("init on update err:", e)

    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id = msg["chat"]["id"]
    from_id = msg["from"]["id"]
    text = (msg.get("text") or "").strip()

    # همیشه کاربر را داشته باشیم
    user = get_or_create_user(from_id)

    if text == "/start":
        _send_text(chat_id, "سلام! به ربات خوش آمدید.\nدستورات: /wallet , /products")
        return

    if text == "/wallet":
        cents = get_wallet(from_id)
        _send_text(chat_id, f"موجودی کیف پول: {cents/100:.2f} تومان")
        return

    if text == "/products":
        prods = list_products()
        if not prods:
            _send_text(chat_id, "فعلاً محصولی ثبت نشده است.")
            return
        for p in prods[:10]:
            cap = f"{p['name']} - قیمت: {p['price_cents']/100:.2f} تومان"
            if p.get("photo_file_id"):
                _send_photo(chat_id, p["photo_file_id"], cap)
            else:
                _send_text(chat_id, cap)
        return

    # اضافه کردن محصول توسط ادمین (اسم و قیمت در کپشن عکس یا متن)
    if text.startswith("/addproduct"):
        if (from_id not in ADMIN_IDS) and (not user.get("is_admin")):
            _send_text(chat_id, "اجازهٔ این کار را ندارید.")
            return
        # الگو: /addproduct نام محصول | 125000 (تومان)  -> تبدیل به سنت
        try:
            parts = text.split(" ", 1)[1]
            name, price_tmn = [x.strip() for x in parts.split("|", 1)]
            price_cents = int(float(price_tmn.replace(",", "")) * 100)
        except Exception:
            _send_text(chat_id, "فرمت درست: /addproduct نام | قیمت_تومان")
            return

        # اگر پیام عکس دارد، فایل آیدی عکس را بردار
        photo_file_id = None
        photos = msg.get("photo") or []
        if photos:
            # بزرگ‌ترین سایز آخرین ایتم
            photo_file_id = photos[-1].get("file_id")

        new_id = add_product(name, price_cents, photo_file_id)
        if new_id:
            _send_text(chat_id, f"محصول ثبت شد (ID: {new_id}).")
        else:
            _send_text(chat_id, "خطا در ثبت محصول.")
        return

    # سایر متن‌ها
    _send_text(chat_id, "دستور ناشناخته. /wallet یا /products را ارسال کنید.")
