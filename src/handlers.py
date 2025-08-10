import os
from .base import send_message
from . import base
from .db import (
    init_db, get_or_create_user, add_product, list_products,
    add_order, get_wallet, get_product
)

# تنظیمات از env
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "5") or "5")

# در اولین استفاده، جداول را می‌سازد (اینجا صدا زده می‌شود تا اپ لایو بماند)
try:
    init_db()
except Exception as e:
    # اگر هم نئون موقتا در دسترس نباشد، ربات از کار نمی‌افتد؛ فقط بخش DB کار نمی‌کند.
    print("DB init error:", e)

def cents_to_irr(cents: int) -> str:
    # فعلا واحد رو تومن در نظر نمی‌گیریم؛ فقط عدد خام (می‌تونی بعدا تبدیل دلخواه بذاری)
    return f"{cents/100:.2f}"

async def handle_update(update: dict):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id = msg["chat"]["id"]
    from_id = msg["from"]["id"]
    user = None
    try:
        user = get_or_create_user(from_id, ADMIN_IDS)
    except Exception as e:
        print("get_or_create_user error:", e)

    text = msg.get("text", "") or ""

    # --- /start
    if text.strip() == "/start":
        await send_message(chat_id, "سلام! به ربات خوش آمدید.\nدستورات: /products , /wallet")
        return

    # --- لیست محصولات
    if text.strip() == "/products":
        try:
            items = list_products()
            if not items:
                await send_message(chat_id, "فعلاً محصولی ثبت نشده.")
                return
            lines = [f"#{p['id']} - {p['title']} - قیمت: {cents_to_irr(p['price_cents'])}"
                     for p in items]
            lines.append("\nبرای خرید: /buy <id> <qty>")
            await send_message(chat_id, "\n".join(lines))
        except Exception as e:
            print("list_products error:", e)
            await send_message(chat_id, "خطا در دریافت لیست محصولات.")
        return

    # --- کیف پول
    if text.strip() == "/wallet":
        if not user:
            await send_message(chat_id, "کاربر یافت نشد.")
            return
        try:
            bal = get_wallet(user["id"])
            await send_message(chat_id, f"موجودی کیف پول: {cents_to_irr(bal)}")
        except Exception as e:
            print("wallet error:", e)
            await send_message(chat_id, "خطا در دریافت کیف پول.")
        return

    # --- خرید
    if text.startswith("/buy"):
        if not user:
            await send_message(chat_id, "کاربر یافت نشد.")
            return
        parts = text.split()
        if len(parts) < 2:
            await send_message(chat_id, "فرمت: /buy <product_id> <qty(optional)>")
            return
        try:
            pid = int(parts[1])
            qty = int(parts[2]) if len(parts) > 2 else 1
        except ValueError:
            await send_message(chat_id, "شناسه یا تعداد نامعتبر است.")
            return
        try:
            pr = get_product(pid)
            if not pr:
                await send_message(chat_id, "محصول یافت نشد.")
                return
            order = add_order(user["id"], pid, max(qty, 1), CASHBACK_PERCENT)
            if not order:
                await send_message(chat_id, "ثبت سفارش ناموفق بود.")
                return
            await send_message(
                chat_id,
                f"سفارش ثبت شد ✅\nجمع: {cents_to_irr(order['total_cents'])}\n"
                f"کش‌بک شما: {cents_to_irr(order['cashback_cents'])}"
            )
        except Exception as e:
            print("buy error:", e)
            await send_message(chat_id, "خطا در ثبت سفارش.")
        return

    # --- افزودن محصول با عکس (فقط ادمین)
    # روش استفاده:
    #   عکس بفرست + کپشن:
    #   /addproduct عنوان | قیمت_به_تومان
    # قیمت مثلا 120000 (تومان). ما به سنت ذخیره می‌کنیم: تومان*100
    if user and user.get("is_admin"):
        # حالت عکس + کپشن
        if "photo" in msg and isinstance(msg["photo"], list) and msg.get("caption", "").startswith("/addproduct"):
            caption = msg.get("caption", "")
            parts = caption.replace("/addproduct", "", 1).strip().split("|", 1)
            if len(parts) != 2:
                await send_message(chat_id, "فرمت نادرست. نمونه: /addproduct عنوان | 120000")
                return
            title = parts[0].strip()
            try:
                price_toman = int(parts[1].strip())
            except ValueError:
                await send_message(chat_id, "قیمت نامعتبر است.")
                return
            # بزرگ‌ترین سایز عکس را می‌گیریم
            photo_sizes = msg["photo"]
            best = max(photo_sizes, key=lambda p: p.get("file_size", 0))
            file_id = best.get("file_id")
            try:
                pid = add_product(title, price_toman * 100, file_id)
                await send_message(chat_id, f"✅ محصول #{pid} اضافه شد.")
            except Exception as e:
                print("add_product(photo) error:", e)
                await send_message(chat_id, "خطا در افزودن محصول.")
            return

        # حالت بدون عکس (متنی)
        if text.startswith("/addproduct"):
            parts = text.replace("/addproduct", "", 1).strip().split("|", 1)
            if len(parts) != 2:
                await send_message(chat_id, "فرمت: /addproduct عنوان | 120000")
                return
            title = parts[0].strip()
            try:
                price_toman = int(parts[1].strip())
            except ValueError:
                await send_message(chat_id, "قیمت نامعتبر است.")
                return
            try:
                pid = add_product(title, price_toman * 100, None)
                await send_message(chat_id, f"✅ محصول #{pid} اضافه شد.")
            except Exception as e:
                print("add_product(text) error:", e)
                await send_message(chat_id, "خطا در افزودن محصول.")
            return

    # بقیه پیام‌ها
    if text:
        await send_message(chat_id, f"دریافت شد: {text}")
