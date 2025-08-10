import os
from typing import Optional

# ایمپورت نسبی از لایه دیتابیس
from .db import (
    init_db,
    set_admins,
    get_or_create_user,
    get_wallet,
    list_products,
    add_product,
)


def startup_warmup():
    """در شروع برنامه، دیتابیس را آماده و ادمین‌ها را ست می‌کند."""
    init_db()
    set_admins()


def _is_admin(tg_id: int) -> bool:
    admins = os.getenv("ADMIN_IDS", "").strip()
    if not admins:
        return False
    admin_ids = {int(x) for x in admins.replace(" ", "").split(",") if x}
    return tg_id in admin_ids


def _fmt_toman(cents: int) -> str:
    # واحد داخلی ما 'سِنت' است (هر 100 = 1 تومان)
    toman = cents // 100
    return f"{toman:,} تومان".replace(",", "،")


async def handle_update(update: dict):
    """
    فقط پیام‌های متنی ساده و عکس با کپشن را پوشش می‌دهیم.
    /start , /products , /wallet
    ادمین: ارسال عکس با کپشن = افزودن محصول
      قالب کپشن:  عنوان | قیمت‌تومان | توضیحات (اختیاری)
    """
    try:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat_id = msg["chat"]["id"]
        from_user = msg.get("from") or {}
        tg_id = int(from_user.get("id", 0))

        # کاربر را اگر نبود بسازیم/بخوانیم
        user = get_or_create_user(from_user)  # {'tg_id','wallet_cents','is_admin'}

        text: Optional[str] = msg.get("text")

        # عکس با کپشن (فقط برای ادمین‌ها)
        if "photo" in msg and _is_admin(tg_id):
            caption = msg.get("caption") or ""
            if caption:
                # قالب: title | price_in_toman | desc(optional)
                parts = [p.strip() for p in caption.split("|")]
                if len(parts) >= 2:
                    title = parts[0]
                    try:
                        price_toman = int(parts[1].replace("،", "").replace(",", ""))
                    except ValueError:
                        await _send_text(chat_id, "❌ قیمت نامعتبر است. مثال: «کِرِپ شکلات | 85000 | توضیح اختیاری»")
                        return
                    desc = parts[2] if len(parts) >= 3 else None

                    # بزرگ‌ترین فایل‌اید عکس را بگیریم
                    photo_sizes = msg["photo"]
                    file_id = photo_sizes[-1]["file_id"]

                    add_product(title=title, price_cents=price_toman * 100, caption=desc, photo_file_id=file_id)
                    await _send_text(chat_id, f"✅ محصول «{title}» ذخیره شد.")
                    return
                else:
                    await _send_text(chat_id, "❌ قالب کپشن: «عنوان | قیمت‌ تومانی | توضیح(اختیاری)»")
                    return

        # دستورات متنی
        if text:
            cmd = text.strip().lower()
            if cmd == "/start":
                await _send_text(
                    chat_id,
                    "سلام! به ربات خوش آمدید.\n"
                    "دستورات: /products , /wallet\n"
                    "اگر ادمین هستید، برای افزودن محصول یک عکس با کپشن بفرستید.",
                )
                return

            if cmd == "/wallet":
                balance = get_wallet(tg_id)
                await _send_text(chat_id, f"موجودی کیف پول شما: {_fmt_toman(balance)}")
                return

            if cmd == "/products":
                prods = list_products()
                if not prods:
                    await _send_text(chat_id, "هنوز محصولی ثبت نشده است.")
                    return

                # ارسال فهرست ساده (برای سادگی فعلاً فقط متن)
                lines = []
                for p in prods:
                    lines.append(f"• {p['title']} — {_fmt_toman(p['price_cents'])}")
                    if p.get("caption"):
                        lines.append(f"  {p['caption']}")
                await _send_text(chat_id, "\n".join(lines))
                return

    except Exception as e:
        # لاگ خطا در رندر دیده می‌شود
        print("handle_update error:", e)


# --- کمک‌متد ارسال پیام تلگرام (ساده و بدون کتابخانه) ---
import http.client
import json
from urllib.parse import urlencode


def _bot_token() -> str:
    return os.environ["BOT_TOKEN"].strip()


async def _send_text(chat_id: int, text: str):
    try:
        payload = {"chat_id": chat_id, "text": text}
        body = urlencode(payload)
        conn = http.client.HTTPSConnection("api.telegram.org", timeout=10)
        conn.request("POST", f"/bot{_bot_token()}/sendMessage", body,
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        conn.getresponse().read()  # پاسخی لازم نداریم
        conn.close()
    except Exception as e:
        print("send_message error:", e)
