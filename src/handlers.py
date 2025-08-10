import os
from typing import Dict, Any

# --- تلاش برای استفاده از توابع آماده در base.py (اگر باشند)
_HAS_BASE_SEND = False
try:
    from src.base import send_message as _base_send_message  # ممکن است وجود نداشته باشد
    from src.base import send_menu as _base_send_menu        # ممکن است وجود نداشته باشد
    _HAS_BASE_SEND = True
except Exception:
    _HAS_BASE_SEND = False

# --- وابستگی‌ها
import requests

from src.db import (
    init_db,          # فقط اگر جای دیگری لازم شد
    set_admins,       # فقط اگر جای دیگری لازم شد
    get_or_create_user,
    get_wallet,
    list_products,
    add_product,
)

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None


# ====== Fallback ها در صورت نبودن توابع در base.py ======
def _fallback_send_message(chat_id: int, text: str) -> None:
    """ارسال متن ساده با Telegram API (اگر base.send_message نبود)."""
    if not (API_URL and chat_id and text is not None):
        return
    try:
        requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text})
    except Exception as _e:
        print("fallback send_message error:", _e)


def _fallback_send_menu(chat_id: int) -> None:
    """پیام خوش‌آمد و منو (اگر base.send_menu نبود)."""
    welcome = (
        "سلام! به ربات خوش آمدید.\n"
        "دستورات:\n"
        "/products  \n"
        "/wallet  \n"
        "اگر ادمین هستید، برای افزودن محصول بعداً گزینه ادمین اضافه می‌کنیم."
    )
    _fallback_send_message(chat_id, welcome)


# رَپرهای نهایی که اولویت را به base.py می‌دهند
def send_message(chat_id: int, text: str) -> None:
    if _HAS_BASE_SEND and callable(globals().get("_base_send_message", None)):
        try:
            _base_send_message(chat_id, text)
            return
        except Exception as _e:
            print("base.send_message error, using fallback:", _e)
    _fallback_send_message(chat_id, text)


def send_menu(chat_id: int) -> None:
    if _HAS_BASE_SEND and callable(globals().get("_base_send_menu", None)):
        try:
            _base_send_menu(chat_id)
            return
        except Exception as _e:
            print("base.send_menu error, using fallback:", _e)
    _fallback_send_menu(chat_id)


# ====== منطق اصلی هندلرها (بدون تغییر رفتاری) ======
async def handle_update(update: Dict[str, Any]) -> None:
    try:
        msg = update.get("message") or update.get("edited_message") or {}
        if not msg:
            return

        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        text = (msg.get("text") or "").strip()
        from_user = msg.get("from") or {}

        if not (chat_id and text):
            return

        # ثبت/بروزرسانی کاربر
        user = get_or_create_user(
            tg_id=from_user.get("id"),
            first_name=from_user.get("first_name"),
            last_name=from_user.get("last_name"),
            username=from_user.get("username"),
        )

        if text == "/start":
            send_menu(chat_id)
            return

        if text == "/wallet":
            wallet_cents, is_admin = get_wallet(user["tg_id"])
            send_message(chat_id, f"موجودی کیف پول شما: {wallet_cents // 100} تومان")
            return

        if text == "/products":
            products = list_products()
            if not products:
                send_message(chat_id, "هنوز محصولی ثبت نشده است.")
            else:
                lines = []
                for i, p in enumerate(products, start=1):
                    name = p.get("name") or p.get("title") or f"محصول {i}"
                    price = p.get("price") or 0
                    lines.append(f"{i}. {name} — {price} تومان")
                send_message(chat_id, "\n".join(lines))
            return

        # جا برای دستورات بعدی…

    except Exception as e:
        print("handle_update error:", e)


def startup_warmup() -> None:
    # هر کاری برای گرم‌کردن در استارتاپ—فعلاً چیزی لازم نیست
    pass
