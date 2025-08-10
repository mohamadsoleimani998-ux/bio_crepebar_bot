import os
import asyncio
from typing import Any, Dict, Optional

import requests

# =========================
# تلاش برای استفاده از ارسال آماده در base.py (اگر موجود باشد)
# =========================
_HAS_BASE_SEND = False
try:
    from src.base import send_message as _base_send_message
    from src.base import send_menu as _base_send_menu
    _HAS_BASE_SEND = True
except Exception:
    _HAS_BASE_SEND = False

# =========================
# ایمپورت‌های دیتابیس (الزامی‌ها)
# =========================
from src.db import get_or_create_user, get_wallet, list_products, add_product

# =========================
# ایمپورت‌های دیتابیس (اختیاری‌ها: اگر نبودند، جایگزین خنثی)
# =========================
try:
    from src.db import set_admins  # ممکن است در db.py تعریف نشده باشد
except Exception:
    def set_admins(*args, **kwargs):
        return None

try:
    from src.db import init_db  # ممکن است وجود نداشته باشد
except Exception:
    def init_db():
        return None

# =========================
# تنظیمات تلگرام
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else ""

def _http_send_message(chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None):
    """ارسال پیام با استفاده از Telegram Bot API (وقتی base.py نداریم)."""
    if not BASE_URL:
        print("WARN: TELEGRAM_BOT_TOKEN تنظیم نشده؛ پیام ارسال نشد.")
        return
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=15)
        if r.status_code >= 300:
            print("sendMessage error:", r.status_code, r.text)
    except Exception as e:
        print("sendMessage exception:", e)

def send_message(chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None):
    """رَپر واحد برای ارسال پیام؛ اولویت با base.py اگر باشد."""
    if _HAS_BASE_SEND:
        try:
            return _base_send_message(chat_id, text, reply_markup=reply_markup)
        except Exception as e:
            print("base.send_message failed, fallback http:", e)
    return _http_send_message(chat_id, text, reply_markup)

def _default_menu_markup() -> Dict[str, Any]:
    """کیبورد ساده با تب/دکمه‌های اصلی."""
    return {
        "keyboard": [
            [{"text": "/products"}, {"text": "/wallet"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }

def send_menu(chat_id: int):
    """ارسال منوی اصلی؛ اگر base موجود بود همان را صدا می‌زنیم."""
    if _HAS_BASE_SEND:
        try:
            return _base_send_menu(chat_id)
        except Exception as e:
            print("base.send_menu failed, fallback http:", e)
    return send_message(chat_id, "گزینه‌ها:", reply_markup=_default_menu_markup())

# =========================
# هَندل اصلی آپدیت‌ها
# =========================
async def handle_update(update: Dict[str, Any]):
    """
    هندل ساده برای پیام‌های متنی:
    - /start
    - /products
    - /wallet
    سایر پیام‌ها نادیده گرفته می‌شوند.
    """
    try:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if not chat_id:
            return

        text = (msg.get("text") or "").strip()

        # ساخت/خواندن کاربر
        from_user = msg.get("from") or {}
        tg_id = from_user.get("id")
        first_name = from_user.get("first_name")
        last_name = from_user.get("last_name")
        username = from_user.get("username")

        # توجه: امضای get_or_create_user باید با db.py خودت سازگار باشد
        try:
            get_or_create_user(
                tg_id=tg_id,
                first_name=first_name,
                last_name=last_name,
                username=username,
            )
        except TypeError:
            # اگر امضای تابع شما متفاوت است، تلاش ساده‌تر:
            try:
                get_or_create_user(tg_id)
            except Exception:
                pass

        if text == "/start":
            welcome = (
                "سلام! به ربات خوش آمدید.\n"
                "دستورات: /products , /wallet\n"
                "اگر ادمین هستید، برای افزودن محصول یک عکس با کپشن بفرستید."
            )
            await asyncio.to_thread(send_message, chat_id, welcome, _default_menu_markup())
            await asyncio.to_thread(send_menu, chat_id)
            return

        if text == "/products":
            try:
                products = list_products()
            except Exception as e:
                print("list_products error:", e)
                products = []

            if not products:
                await asyncio.to_thread(send_message, chat_id, "هنوز محصولی ثبت نشده است.", _default_menu_markup())
            else:
                lines = []
                for p in products:
                    # انعطاف: p می‌تواند dict یا tuple باشد
                    if isinstance(p, dict):
                        name = p.get("name") or p.get("title") or "محصول"
                        price = p.get("price") or p.get("amount") or 0
                    else:
                        # tuple: (id,name,price,...) یا مشابه
                        name = str(p[1]) if len(p) > 1 else "محصول"
                        price = p[2] if len(p) > 2 else 0
                    lines.append(f"• {name} — {price} تومان")
                await asyncio.to_thread(send_message, chat_id, "\n".join(lines), _default_menu_markup())
            return

        if text == "/wallet":
            try:
                balance = get_wallet(tg_id)
            except TypeError:
                balance = get_wallet()
            except Exception as e:
                print("get_wallet error:", e)
                balance = 0
            await asyncio.to_thread(send_message, chat_id, f"موجودی کیف پول شما: {balance} تومان", _default_menu_markup())
            return

        # افزودن محصول برای ادمین‌ها (الگوی ساده: عکس با کپشن)
        if "photo" in msg and msg.get("caption"):
            caption = (msg.get("caption") or "").strip()
            # انتظار نام و قیمت در کپشن (به دلخواه خودت؛ فعلاً فقط نام)
            try:
                add_product(caption)
                await asyncio.to_thread(send_message, chat_id, "محصول اضافه شد ✅", _default_menu_markup())
            except Exception as e:
                print("add_product error:", e)
                await asyncio.to_thread(send_message, chat_id, "افزودن محصول ناموفق بود.", _default_menu_markup())
            return

        # سایر پیام‌ها
        await asyncio.to_thread(send_message, chat_id, "دستور نامعتبر است.", _default_menu_markup())

    except Exception as e:
        # لاگ خطای کلی اما اجازه می‌دهیم سرویس لایو بماند
        print("handle_update error:", e)

# =========================
# استارتاپ وارم‌آپ (فراخوانی از bot.py)
# =========================
def startup_warmup():
    """برای آماده‌سازی اولیه: ساخت جداول/ستون‌ها اگر لازم است."""
    try:
        init_db()
        # اگر set_admins تعریف شده بود، می‌توانی اینجا لیست اولیه بدهی:
        set_admins()  # نسخه‌ی خنثی چیزی انجام نمی‌دهد
        print("startup_warmup OK")
    except Exception as e:
        print("startup_warmup error:", e)
