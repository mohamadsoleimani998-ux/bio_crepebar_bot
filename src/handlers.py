# src/handlers.py
from typing import Any, Dict
from .base import tg_send_message, tg_send_photo, ADMIN_IDS, ensure_schema, add_product, list_products, wallet_get, wallet_add

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "منو 🍽"}, {"text": "ساعات کاری"}],
        [{"text": "موقعیت 📍"}, {"text": "کیف پول 💳"}],
    ],
    "resize_keyboard": True,
}

SHOP_HOURS = "هر روز ۱۲ تا ۲۳"
SHOP_LOCATION = {"latitude": 35.7000, "longitude": 51.4000}  # اگر خواستی از env بگذاریم، می‌تونیم بعداً

async def handle_update(update: Dict[str, Any]):
    # اطمینان از ساخت جداول (فقط اولین بار هزینه داره)
    await ensure_schema()

    if "message" not in update:
        return
    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "") or ""

    # ----- دستورات ادمین -----
    from_user_id = msg["from"]["id"]

    # افزودن محصول: عکس + کپشن با /addproduct
    if "photo" in msg and isinstance(msg.get("caption", ""), str) and msg["caption"].startswith("/addproduct"):
        if from_user_id not in ADMIN_IDS:
            await tg_send_message(chat_id, "شما دسترسی ادمین ندارید.")
            return
        caption = msg["caption"][len("/addproduct"):].strip()
        parts = [p.strip() for p in caption.split("|")]
        if len(parts) < 2:
            await tg_send_message(chat_id, "فرمت نادرست. نمونه:\n/sendphoto با کپشن:\n/addproduct نام | قیمت | توضیح")
            return
        name = parts[0]
        try:
            price = int(parts[1])
        except ValueError:
            await tg_send_message(chat_id, "قیمت باید عددی باشد. نمونه: 120000")
            return
        desc = parts[2] if len(parts) >= 3 else ""

        # بزرگ‌ترین سایز عکس را بگیر
        photo_sizes = msg["photo"]
        best = max(photo_sizes, key=lambda p: p.get("file_size", 0))
        file_id = best["file_id"]

        await add_product(name=name, price=price, description=desc, photo_file_id=file_id)
        await tg_send_message(chat_id, f"✅ محصول «{name}» اضافه شد.", reply_markup=MAIN_KEYBOARD)
        return

    # افزایش کیف پول توسط ادمین
    if text.startswith("/cashback"):
        if from_user_id not in ADMIN_IDS:
            await tg_send_message(chat_id, "شما دسترسی ادمین ندارید.")
            return
        parts = text.split(maxsplit=3)
        if len(parts) < 3:
            await tg_send_message(chat_id, "فرمت: /cashback <user_id> <amount> [note]")
            return
        try:
            target = int(parts[1]); amount = int(parts[2])
        except ValueError:
            await tg_send_message(chat_id, "user_id و amount باید عددی باشند.")
            return
        note = parts[3] if len(parts) >= 4 else "cashback"
        await wallet_add(target, amount, note)
        await tg_send_message(chat_id, f"✅ {amount} به کیف پول {target} اضافه شد.")
        return

    # ----- دستورات عمومی -----
    if text == "/start":
        await tg_send_message(
            chat_id,
            "سلام! به ربات خوش آمدید.",
            reply_markup=MAIN_KEYBOARD
        )
        return

    if text == "ساعات کاری":
        await tg_send_message(chat_id, f"⏰ ساعات کاری: {SHOP_HOURS}", reply_markup=MAIN_KEYBOARD)
        return

    if text == "موقعیت 📍":
        # چون raw API داریم، sendLocation مستقیم صدا می‌زنیم
        from httpx import AsyncClient
        async with AsyncClient(timeout=30) as client:
            await client.post(
                f"https://api.telegram.org/bot{__import__('os').getenv('BOT_TOKEN')}/sendLocation",
                data={"chat_id": chat_id, "latitude": SHOP_LOCATION["latitude"], "longitude": SHOP_LOCATION["longitude"]}
            )
        return

    if text == "منو 🍽":
        products = await list_products(limit=6)
        if not products:
            await tg_send_message(chat_id, "منوی فعلاً خالی است.", reply_markup=MAIN_KEYBOARD)
            return
        # اگر عکس داشت، با عکس بفرست؛ وگرنه متن
        for p in products:
            caption = f"{p['name']} — {p['price']:,} تومان\n{p.get('description','') or ''}"
            if p.get("photo_file_id"):
                await tg_send_photo(chat_id, p["photo_file_id"], caption=caption)
            else:
                await tg_send_message(chat_id, caption)
        return

    if text == "کیف پول 💳" or text == "/wallet":
        bal = await wallet_get(from_user_id)
        await tg_send_message(chat_id, f"💳 موجودی کیف پول شما: {bal:,} تومان", reply_markup=MAIN_KEYBOARD)
        return

    # پیش‌فرض: eco
    await tg_send_message(chat_id, "دستور نامعتبر بود. از منوی پایین استفاده کنید.", reply_markup=MAIN_KEYBOARD)
