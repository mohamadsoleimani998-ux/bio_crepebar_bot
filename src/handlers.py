import os
from typing import Optional, Dict, Any, List

import httpx

# ایمپورت نسبی از لایه دیتابیس (همان امضای قبلی نگه داشته شده)
from .db import (
    get_or_create_user,
    list_products,
    get_wallet,
    add_product,         # اگر کپشنِ عکس دادیم
    set_admins,          # اختیاری: از ENV ادمین‌ها را ست می‌کند
)

# توکن از ENV (هر کدام بود)
BOT_TOKEN = (
    os.getenv("BOT_TOKEN")
    or os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
)
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# === ابزارک‌های ارسال پیام به تلگرام (Async) ===
async def tg_send_message(chat_id: int, text: str, parse_mode: Optional[str] = None):
    if not BOT_TOKEN:
        print("WARN: BOT_TOKEN not set; skip sendMessage")
        return
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{API_BASE}/sendMessage", json=payload)
        if r.status_code >= 400:
            print("sendMessage error:", r.text)


# === استارتاپ وارم‌آپ (اینجا کار سبک انجام می‌دهیم) ===
async def startup_warmup():
    # ادمین‌ها را از ENV تنظیم می‌کنیم (اختیاری)
    # مثال: ADMIN_TG_IDS="12345,67890"
    admins = (os.getenv("ADMIN_TG_IDS") or "").strip()
    if admins:
        ids = [x.strip() for x in admins.split(",") if x.strip()]
        try:
            set_admins(ids)
        except Exception as e:
            print("set_admins error:", e)


# === هندل اصلی وبهوک ===
async def handle_update(update: Dict[str, Any]):
    """
    بدون کتابخانه‌های بات، مستقیم JSON تلگرام را هندل می‌کنیم
    تا وابستگی و خطاهای ماژول از بین برود.
    """
    try:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            # فعلا فقط message را هندل می‌کنیم
            return

        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        from_user = msg.get("from") or {}

        # کاربر را (ایمن) بساز/بگیر
        tg_id = str(from_user.get("id")) if from_user.get("id") is not None else None
        first_name = from_user.get("first_name")
        last_name = from_user.get("last_name")
        username = from_user.get("username")

        # اگر به هر دلیل id نبود، ادامه نده (برای ایمن بودن)
        if not tg_id or not chat_id:
            return

        user = get_or_create_user(
            tg_id=tg_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )

        text = (msg.get("text") or "").strip()

        # ——— فرمان‌ها ———
        if text == "/start":
            await tg_send_message(
                chat_id,
                "سلام! به ربات خوش آمدید.\n"
                "دستورات:\n"
                " /products  — لیست محصولات\n"
                " /wallet    — موجودی کیف پول",
            )
            return

        if text == "/products":
            items: List[Dict[str, Any]] = list_products()
            if not items:
                await tg_send_message(chat_id, "هنوز محصولی ثبت نشده است.")
                return

            lines = []
            for p in items:
                name = p.get("name") or "-"
                price = int(p.get("price_cents") or 0) // 10  # نمایش به تومان
                lines.append(f"• {name} — {price:,} تومان")
            await tg_send_message(chat_id, "\n".join(lines))
            return

        if text == "/wallet":
            cents = int(get_wallet(user_id=user["id"]) or 0)
            toman = cents // 10
            await tg_send_message(chat_id, f"موجودی کیف پول شما: {toman:,} تومان")
            return

        # ——— افزودن محصول توسط ادمین (ارسال عکس با کپشن) ———
        # اگر عکس دارد و کپشن دارد و ادمین است:
        if msg.get("photo") and msg.get("caption") and user.get("is_admin"):
            # کپشن ساده: نام | قیمت_تومان
            # مثال:  "کراپ شکلاتی | 120000"
            cap = msg["caption"]
            try:
                name, toman_str = [x.strip() for x in cap.split("|", 1)]
                price_cents = int(toman_str.replace(",", "")) * 10
                add_product(name=name, price_cents=price_cents)
                await tg_send_message(chat_id, "محصول با موفقیت ثبت شد.")
            except Exception as e:
                print("add_product error:", e)
                await tg_send_message(chat_id, "فرمت کپشن صحیح نیست. مثال: نام | 120000")
            return

        # پیش‌فرض: پاسخی نمی‌دهیم
        # (می‌توان پیام راهنما داد)
        # await tg_send_message(chat_id, "دستور ناشناخته.")
    except Exception as e:
        # هیچ اروری ربات را داون نکند
        print("handle_update error:", e)
