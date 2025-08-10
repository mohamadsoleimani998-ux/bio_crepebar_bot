# src/handlers.py
import os
import asyncio
import httpx

from db import (
    get_or_create_user,
    get_wallet,
    list_products,
    add_product,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- helpers --------------------------------------------------------------

async def _post(method: str, payload: dict):
    """Send request to Telegram safely; never raise to break the app."""
    if not BOT_TOKEN:
        print("BOT_TOKEN is empty!")
        return None
    url = f"{BASE_URL}/{method}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=payload)
            if r.is_success:
                return r.json()
            else:
                print("Telegram API error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram send error:", e)
    return None

async def send_message(chat_id: int, text: str, reply_to: int | None = None):
    await _post(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_to_message_id": reply_to,
        },
    )

def _format_toman(cents: int | None) -> str:
    """wallet_cents -> تومان (رند ساده)"""
    if cents is None:
        return "0"
    # اگر واحد ذخیره‌سازی «سِنت/ریال» باشد، این تقسیم جلوی اعداد خیلی بزرگ را می‌گیرد.
    # لازم شد بعدا دقیق‌تر تنظیم می‌کنیم.
    amount = int(cents) // 10
    return f"{amount:,}"

# --- core handler ---------------------------------------------------------

async def handle_update(update: dict):
    """
    مین‌هندلر وبهوک: فقط کارهای امن و ساده که قبلا داشتیم:
      - /start: خوش‌آمد، ایجاد کاربر در DB (اگر نبود)
      - /products: لیست محصولات یا پیام «هنوز محصولی ثبت نشده است.»
      - /wallet: نمایش موجودی کیف پول
      - ادمین: ارسال عکس با کپشن "نام | قیمت" => افزودن محصول
    هر خطایی فقط لاگ می‌شود تا سرویس لایو بماند.
    """
    try:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return

        from_user = message.get("from") or {}
        tg_id = from_user.get("id")

        # کاربر را بساز/بخوان (ایمن)
        try:
            user = get_or_create_user(tg_id)
        except Exception as e:
            print("get_or_create_user error:", e)
            user = {"is_admin": False}

        text = (message.get("text") or "").strip()

        # ---- commands ----
        if text == "/start":
            await send_message(
                chat_id,
                "سلام! به ربات خوش آمدید.\n"
                "دستورات:\n"
                "/products , /wallet/\n"
                "اگر ادمین هستید، برای افزودن یک محصول با عکس، کپشن را به شکل «نام | قیمت» بفرستید."
            )
            return

        if text == "/wallet":
            try:
                cents = get_wallet(tg_id)
                await send_message(chat_id, f"موجودی کیف پول شما: {_format_toman(cents)} تومان")
            except Exception as e:
                print("wallet error:", e)
                await send_message(chat_id, "خطا در دریافت کیف پول.")
            return

        if text == "/products":
            try:
                items = list_products()
                if not items:
                    await send_message(chat_id, "هنوز محصولی ثبت نشده است.")
                else:
                    lines = []
                    for p in items:
                        # انتظار: هر ردیف دیکشنری/تاپل شامل name و price_cents
                        name = p.get("name") if isinstance(p, dict) else p[1]
                        price_cents = p.get("price_cents") if isinstance(p, dict) else p[2]
                        lines.append(f"• {name} — {_format_toman(price_cents)} تومان")
                    await send_message(chat_id, "\n".join(lines))
            except Exception as e:
                print("list_products error:", e)
                await send_message(chat_id, "خطا در دریافت لیست محصولات.")
            return

        # ---- admin: add product via photo + caption "name | price" ----
        if user.get("is_admin") and ("photo" in message) and message.get("caption"):
            caption = message["caption"].strip()
            if "|" in caption:
                try:
                    name, price_str = [part.strip() for part in caption.split("|", 1)]
                    # ساده: قیمت را عددی می‌کنیم و فرض می‌کنیم تومان است -> به سنت/ریال تبدیل
                    price_cents = int("".join(ch for ch in price_str if ch.isdigit())) * 10
                    # از بزرگ‌ترین سایز photo فایل آی‌دی می‌گیریم
                    file_id = message["photo"][-1]["file_id"]
                    add_product(name=name, price_cents=price_cents, photo_file_id=file_id)
                    await send_message(chat_id, "✅ محصول ذخیره شد.")
                except Exception as e:
                    print("add_product error:", e)
                    await send_message(chat_id, "خطا در افزودن محصول. فرمت کپشن: «نام | قیمت»")
            else:
                await send_message(chat_id, "فرمت کپشن: «نام | قیمت»")
            return

        # سایر پیام‌ها را نادیده می‌گیریم تا چیزی خراب نشود
    except Exception as e:
        print("handle_update error:", e)
