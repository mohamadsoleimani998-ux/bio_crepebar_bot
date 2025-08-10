import os
import re
import requests
from typing import Any, Dict, Optional

from db import init_db, get_or_create_user, get_wallet, list_products, add_product

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# لیست ادمین‌ها از env مثل: 123,456
_admin_env = os.getenv("ADMIN_IDS", "") or ""
ADMIN_IDS = [int(x) for x in re.findall(r"\d+", _admin_env)]

def _fmt_toman_from_cents(cents: int) -> str:
    toman = cents // 100  # ذخیره را «سِنت» در نظر گرفتیم
    s = f"{toman:,}".replace(",", "٬")
    return f"{s} تومان"

def _send_message(chat_id: int, text: str, reply_to: Optional[int] = None):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        requests.post(f"{API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        print("send_message error:", e)

def _send_photo(chat_id: int, file_id: str, caption: Optional[str] = None):
    try:
        payload = {"chat_id": chat_id, "photo": file_id}
        if caption:
            payload["caption"] = caption
            payload["parse_mode"] = "HTML"
        requests.post(f"{API}/sendPhoto", json=payload, timeout=10)
    except Exception as e:
        print("send_photo error:", e)

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def _greet_text() -> str:
    return ("سلام! به ربات خوش آمدید.\n"
            "دستورات: <b>/products</b> , <b>/wallet</b>\n"
            "اگر ادمین هستید، برای افزودن محصول یک <b>عکس با کپشن</b> بفرستید.\n"
            "فرمت کپشن: <i>نام محصول | قیمت به تومان</i>")

def _parse_caption(caption: str):
    """
    ورودی مثل:  'کوکاکولا | 58000'
    خروجی: name, price_cents
    """
    if not caption:
        return None, None
    parts = [p.strip() for p in caption.split("|")]
    if len(parts) < 2:
        return None, None
    name = parts[0]
    # فقط عدد قیمت
    digits = re.sub(r"[^\d]", "", parts[1])
    if not digits:
        return None, None
    price_toman = int(digits)
    price_cents = price_toman * 100
    return name, price_cents

async def handle_update(update: Dict[str, Any]):
    """
    هندلر اصلی وبهوک. هر خطا لاگ می‌شود ولی کرش نمی‌کنیم تا سرویس لایو بماند.
    """
    try:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = message["chat"]["id"]
        from_user = message.get("from", {})
        user_id = int(from_user.get("id", 0))
        full_name = " ".join([from_user.get("first_name","") or "", from_user.get("last_name","") or ""]).strip()
        username = from_user.get("username")

        # کاربر را بساز/آپدیت کن (ایمن)
        try:
            get_or_create_user(user_id, full_name, username)
        except Exception as e:
            print("get_or_create_user error:", e)

        # --- متن‌ها ---
        if "text" in message:
            text = (message.get("text") or "").strip()

            if text == "/start":
                _send_message(chat_id, _greet_text())
                return

            if text == "/wallet":
                try:
                    cents = get_wallet(user_id)
                    _send_message(chat_id, f"موجودی کیف پول شما: {_fmt_toman_from_cents(cents)}")
                except Exception as e:
                    print("get_wallet error:", e)
                    _send_message(chat_id, "خطا در دریافت موجودی کیف پول.")
                return

            if text == "/products":
                try:
                    items = list_products()
                    if not items:
                        _send_message(chat_id, "هنوز محصولی ثبت نشده است.")
                        return
                    for p in items:
                        cap = f"<b>{p['name']}</b>\nقیمت: {_fmt_toman_from_cents(int(p['price_cents']))}"
                        if p.get("photo_file_id"):
                            _send_photo(chat_id, p["photo_file_id"], cap)
                        else:
                            _send_message(chat_id, cap)
                except Exception as e:
                    print("list_products error:", e)
                    _send_message(chat_id, "خطا در دریافت لیست محصولات.")
                return

            # سایر متن‌ها
            _send_message(chat_id, "دستور نامعتبر. /products یا /wallet را بفرستید.")
            return

        # --- افزودن محصول توسط ادمین (عکس با کپشن) ---
        if "photo" in message and _is_admin(user_id):
            try:
                photos = message.get("photo") or []
                if not photos:
                    return
                largest = photos[-1]
                file_id = largest["file_id"]
                name, price_cents = _parse_caption(message.get("caption") or "")
                if not name or price_cents is None:
                    _send_message(chat_id, "کپشن نامعتبر است. فرمت: <i>نام | قیمت</i>")
                    return
                pid = add_product(name, price_cents, file_id)
                _send_message(chat_id, f"✅ محصول «{name}» با قیمت {_fmt_toman_from_cents(price_cents)} ثبت شد. (id={pid})")
            except Exception as e:
                print("add_product error:", e)
                _send_message(chat_id, "خطا در ثبت محصول.")
            return

        # اگر عکس آمد ولی ادمین نبود
        if "photo" in message and not _is_admin(user_id):
            _send_message(chat_id, "ارسال عکس فقط برای ادمین جهت افزودن محصول است.")
            return

    except Exception as e:
        # هیچ‌وقت کرش نکن
        print("handle_update top-level error:", e)
