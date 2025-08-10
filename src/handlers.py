import os
import re
import requests

from db import init_db, get_or_create_user, get_wallet, update_wallet, list_products, add_product

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x]
CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "5") or "5")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def _send_text(chat_id: int, text: str, parse_mode: str | None = None):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        requests.post(f"{API}/sendMessage", json=payload, timeout=10)
    except Exception:
        pass

def _send_photo(chat_id: int, file_id: str, caption: str | None = None):
    payload = {"chat_id": chat_id, "photo": file_id}
    if caption:
        payload["caption"] = caption
    try:
        requests.post(f"{API}/sendPhoto", json=payload, timeout=10)
    except Exception:
        pass


async def handle_update(update: dict):
    """
    حداقل‌های پایدار:
    - /start : ساخت کاربر + راهنما
    - /wallet : نمایش موجودی (تومان)
    - /products : لیست محصولات (اگر عکس دارد با عکس، وگرنه متن)
    - ادمین: ارسال Photo با کپشن «عنوان | قیمت_تومان» -> ثبت محصول
    """
    try:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = int(chat.get("id"))
        from_user = msg.get("from", {}) or {}
        tg_id = int(from_user.get("id"))

        is_admin = tg_id in ADMIN_IDS
        # ایجاد/خواندن کاربر
        get_or_create_user(tg_id, is_admin=is_admin)

        text = msg.get("text") or ""
        photo = msg.get("photo")

        # --- Commands ---
        if text.startswith("/start"):
            _send_text(
                chat_id,
                "سلام! به ربات خوش آمدید.\n"
                "دستورات: /wallet , /products\n"
                "اگر ادمین هستید، برای افزودن محصول یک عکس با کپشن بفرستید.\n"
                "فرمت کپشن: عنوان | قیمت_تومان",
            )
            return

        if text.startswith("/wallet"):
            cents = get_wallet(tg_id)
            toman = cents // 100
            _send_text(chat_id, f"موجودی کیف پول شما: {toman} تومان")
            return

        if text.startswith("/products"):
            items = list_products()
            if not items:
                _send_text(chat_id, "هنوز محصولی ثبت نشده است.")
                return
            for it in items[:20]:
                cap = f"{it['title']} - قیمت: {it['price_cents']//100} تومان"
                if it.get("image_file_id"):
                    _send_photo(chat_id, it["image_file_id"], cap)
                else:
                    _send_text(chat_id, cap)
            return

        # --- Admin: add product via photo + caption ---
        if is_admin and photo:
            caption = msg.get("caption") or ""
            # الگو: عنوان | قیمت_تومان
            m = re.match(r"(.+?)\s*\|\s*(\d+)", caption)
            if not m:
                _send_text(chat_id, "فرمت کپشن معتبر نیست. مثال: «کراپ نوتلا | 85000»")
                return
            title = m.group(1).strip()
            price_toman = int(m.group(2))
            price_cents = price_toman * 100
            # آخرین سایز بزرگ‌ترین عکس را می‌گیریم
            file_id = photo[-1]["file_id"] if isinstance(photo, list) and photo else None
            add_product(title, price_cents, file_id)
            _send_text(chat_id, f"محصول «{title}» با قیمت {price_toman} تومان ثبت شد.")
            return

    except Exception as e:
        # لاگ مختصر؛ سرویس لایو می‌ماند
        print("handle_update error:", e)
