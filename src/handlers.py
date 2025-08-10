import os
import logging
import requests
from typing import Any, Dict, Optional

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ارسال پیام
def send_message(chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None):
    try:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logging.exception("send_message error: %s", e)

# چک کردن ادمین بودن
def is_admin(user_id: int) -> bool:
    raw = os.getenv("ADMIN_IDS", "")
    if not raw:
        return False
    try:
        return str(user_id) in [s.strip() for s in raw.split(",") if s.strip()]
    except Exception:
        return False

# ایمپورت امن دیتابیس
def _db():
    try:
        from src import db  # type: ignore
        return db
    except Exception as e:
        logging.warning("db module not ready: %s", e)
        return None

# هندل آپدیت
async def handle_update(update: Dict[str, Any]):
    try:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = message["chat"]["id"]
        text = (message.get("text") or "").strip()
        user_id = message.get("from", {}).get("id")

        # /start
        if text.startswith("/start"):
            send_message(
                chat_id,
                "سلام! به ربات خوش آمدید.\n"
                "دستورات: /products ، /wallet\n"
                "اگر ادمین هستید، برای افزودن محصول یک عکس با کپشن بفرستید."
            )
            return

        # /products
        if text.startswith("/products"):
            db = _db()
            if db and hasattr(db, "list_products"):
                try:
                    items = db.list_products()
                    if not items:
                        send_message(chat_id, "هنوز محصولی ثبت نشده است.")
                        return

                    lines = []
                    for p in items:
                        pid, title, price_cents, desc, _photo = p
                        price = (price_cents or 0) / 100
                        lines.append(f"#{pid} — {title} — {price:.0f} تومان\n{desc or ''}")
                    send_message(chat_id, "\n\n".join(lines))
                except Exception as e:
                    logging.exception("list_products error: %s", e)
                    send_message(chat_id, "خطا در دریافت لیست محصولات.")
            else:
                send_message(chat_id, "ماژول دیتابیس یا تابع محصولات آماده نیست.")
            return

        # /wallet
        if text.startswith("/wallet"):
            db = _db()
            try:
                if db and hasattr(db, "get_wallet"):
                    cents = db.get_wallet(user_id)
                    tomans = (cents or 0) / 100
                    send_message(chat_id, f"موجودی کیف پول شما: {tomans:.0f} تومان")
                elif db and hasattr(db, "get_or_create_user"):
                    u = db.get_or_create_user(user_id)
                    wallet_cents = None
                    if isinstance(u, dict):
                        wallet_cents = u.get("wallet_cents")
                    elif isinstance(u, (list, tuple)) and len(u) >= 2:
                        wallet_cents = u[1]
                    tomans = (wallet_cents or 0) / 100
                    send_message(chat_id, f"موجودی کیف پول شما: {tomans:.0f} تومان")
                else:
                    send_message(chat_id, "کیف پول هنوز فعال نشده است.")
            except Exception as e:
                logging.exception("wallet error: %s", e)
                send_message(chat_id, "خطا در دریافت کیف پول.")
            return

        # افزودن محصول با عکس
        if "photo" in message and is_admin(user_id):
            caption = (message.get("caption") or "").strip()
            photos = message.get("photo") or []
            if not photos:
                return
            file_id = photos[-1]["file_id"]

            try:
                title, price_toman, *rest = [s.strip() for s in caption.split("|")]
                description = rest[0] if rest else ""
                price_cents = int(float(price_toman)) * 100
            except Exception:
                send_message(chat_id, "فرمت کپشن صحیح نیست. مثال:\nعنوان | قیمت_به_تومان | توضیح")
                return

            db = _db()
            if db and hasattr(db, "add_product"):
                try:
                    db.add_product(title, price_cents, description, file_id)
                    send_message(chat_id, "محصول با موفقیت اضافه شد ✅")
                except Exception as e:
                    logging.exception("add_product error: %s", e)
                    send_message(chat_id, "خطا در افزودن محصول.")
            else:
                send_message(chat_id, "تابع افزودن محصول آماده نیست.")
            return

        send_message(chat_id, "دستور ناشناخته. از /start استفاده کنید.")

    except Exception as e:
        logging.exception("handle_update error: %s", e)
