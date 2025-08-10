# src/handlers.py
import os
import requests
from db import init_db, set_admins, get_or_create_user, get_wallet, list_products, add_product

BOT_TOKEN = os.getenv("BOT_TOKEN")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(",", " ").split() if x.strip().isdigit()]

# در استارتاپ از bot.py صدا زده می‌شود
def startup_warmup():
    try:
        init_db()
        set_admins(ADMIN_IDS)
        print("DB ready; admins set.")
    except Exception as e:
        print("startup_warmup error:", e)

def _send(chat_id, text, parse_mode=None):
    try:
        requests.post(f"{API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode or "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
    except Exception as e:
        print("sendMessage error:", e)

def _extract_user(update: dict):
    """
    برمی‌گرداند: (chat_id, user_id, username, full_name, text, photo, caption)
    در تمام انواع آپدیت‌های رایج.
    """
    chat_id = user_id = None
    username = full_name = text = caption = None
    photo = None

    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        if "from" in msg:
            f = msg["from"]
            user_id = f.get("id")
            username = f.get("username")
            full_name = " ".join([f.get("first_name", "") or "", f.get("last_name", "") or ""]).strip() or None
        text = msg.get("text")
        caption = msg.get("caption")
        # اگر عکس دارد
        if "photo" in msg and msg["photo"]:
            # بزرگترین سایز آخر آرایه است
            photo = msg["photo"][-1].get("file_id")

    elif "callback_query" in update:
        cq = update["callback_query"]
        msg = cq.get("message", {})
        chat_id = (msg.get("chat") or {}).get("id")
        f = cq.get("from", {})
        user_id = f.get("id")
        username = f.get("username")
        full_name = " ".join([f.get("first_name", "") or "", f.get("last_name", "") or ""]).strip() or None
        text = cq.get("data")

    return chat_id, user_id, username, full_name, text, photo, caption

def handle_update(update: dict):
    """
    ورودی خام وبهوک (JSON) را می‌گیرد.
    هیچ خطایی به بیرون پروپاگیت نمی‌شود تا سرویس لایو بماند.
    """
    try:
        chat_id, user_id, username, full_name, text, photo, caption = _extract_user(update)

        if not chat_id:
            return  # چیزی برای جواب‌دادن نداریم

        # *** فیکس اصلی: قبل از هر کاری کاربر را بساز/به‌روز کن — و اگر user_id نداشتیم، کاری نکن ***
        if user_id is not None:
            try:
                get_or_create_user(user_id, username=username, full_name=full_name)
            except Exception as e:
                print("get_or_create_user error:", e)
        else:
            print("No user_id in update; skip user upsert.")

        # دستورات
        if text == "/start":
            _send(chat_id,
                  "سلام! به ربات خوش آمدید.\n"
                  "دستورات:\n"
                  "<code>/products</code> ، <code>/wallet</code>\n"
                  "اگر ادمین هستید، برای افزودن محصول یک عکس با کپشن بفرستید: <code>نام|قیمت_تومان|توضیح_اختیاری</code>")
            return

        if text == "/wallet":
            bal_cents = get_wallet(user_id) if user_id is not None else 0
            toman = bal_cents // 100
            _send(chat_id, f"موجودی کیف پول شما: {toman} تومان")
            return

        if text == "/products":
            prods = list_products()
            if not prods:
                _send(chat_id, "هنوز محصولی ثبت نشده است.")
            else:
                lines = []
                for p in prods:
                    toman = int(p["price_cents"]) // 100
                    lines.append(f"• {p['name']} — {toman} تومان")
                _send(chat_id, "\n".join(lines))
            return

        # افزودن محصول توسط ادمین: ارسال Photo + Caption
        if photo and caption and (str(user_id) in {str(a) for a in ADMIN_IDS}):
            try:
                parts = [x.strip() for x in caption.split("|")]
                if len(parts) >= 2:
                    name = parts[0]
                    price_toman = int(parts[1].replace(",", ""))
                    desc = parts[2] if len(parts) >= 3 else None
                    add_product(name=name,
                                price_cents=price_toman * 100,
                                description=desc,
                                photo_file_id=photo)
                    _send(chat_id, "✅ محصول ثبت شد.")
                else:
                    _send(chat_id, "فرمت کپشن درست نیست. نمونه: <code>نام|قیمت_تومان|توضیح</code>")
            except Exception as e:
                print("add_product error:", e)
                _send(chat_id, "❌ ثبت محصول ناموفق بود.")
            return

    except Exception as e:
        # لاگ بدون ازکارانداختن وب‌سرور
        print("handle_update error:", e)
