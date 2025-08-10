import os
from typing import Dict, Any

# اگر base توابع ارسال پیام/منو رو داره، همون‌ها رو استفاده می‌کنیم
from src.base import send_message, send_menu

# توابع دیتابیس—فقط ایمپورت مطلق
from src.db import (
    init_db,          # اگر جایی لازم شد
    set_admins,       # اگر جایی لازم شد
    get_or_create_user,
    get_wallet,
    list_products,
    add_product,      # برای بعداً (افزودن محصول)
)

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")

async def handle_update(update: Dict[str, Any]) -> None:
    """
    منطق همون قبلیه: /start ، /wallet ، /products
    فقط ایمپورت‌ها اصلاح شده‌اند. send_message/send_menu فرضاً سینک هستند
    و در تابع async بدون await صدا می‌زنیم (مثل قبل که برات کار می‌کرد).
    """
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

        # ثبت/بروزرسانی کاربر بر اساس tg_id (همان چیزی که در DB ساختیم)
        user = get_or_create_user(
            tg_id=from_user.get("id"),
            first_name=from_user.get("first_name"),
            last_name=from_user.get("last_name"),
            username=from_user.get("username"),
        )

        # دستورات
        if text == "/start":
            # پیام خوش‌آمد + منو
            send_menu(chat_id)
            return

        if text == "/wallet":
            wallet_cents, is_admin = get_wallet(user["tg_id"])
            # نمایش به تومان مثل قبل
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

        # سایر دستورات (در صورت نیاز بعداً اضافه می‌کنیم)
        # ...

    except Exception as e:
        # فقط لاگ؛ تا سرویس لایو بماند
        print("handle_update error:", e)

def startup_warmup() -> None:
    # برای گرم نگه‌داشتن/لود اولیه اگر لازم شد
    pass
