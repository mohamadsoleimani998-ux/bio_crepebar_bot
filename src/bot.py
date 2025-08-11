# src/handlers.py
from __future__ import annotations

import os
from typing import Dict, Any, List, Tuple, Optional

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
)

# ایمپورت ماژول دیتابیس از داخل پکیج src
from . import db

# -------------------------------
# پیکربندی و ثابت‌ها
# -------------------------------
ADMIN_IDS: List[int] = []
admins_env = os.getenv("ADMIN_IDS", "")
if admins_env.strip():
    for p in admins_env.replace(" ", "").split(","):
        if p.isdigit():
            ADMIN_IDS.append(int(p))

PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

# استیت‌های گفتگوها
(
    ORDER_CHOOSE_PRODUCT,
    ORDER_SET_QTY,
    ORDER_GET_NAME,
    ORDER_GET_PHONE,
    ORDER_GET_ADDRESS,
    ORDER_CONFIRM,
) = range(100, 106)

(
    CONTACT_WAIT_MSG,
) = range(200, 201)

(
    ADMIN_ADD_NAME,
    ADMIN_ADD_PRICE,
    ADMIN_ADD_PHOTO,
    ADMIN_EDIT_WAIT_ID,
    ADMIN_EDIT_FIELD,
    ADMIN_EDIT_VALUE,
) = range(300, 306)

(
    WALLET_TOPUP_METHOD,
    WALLET_TOPUP_AMOUNT,
    WALLET_TOPUP_CONFIRM,
) = range(400, 403)

# برچسب‌های فارسی دکمه‌های منو (نمایشی)
BTN_PRODUCTS = "🛒 منوی محصولات"
BTN_ORDER = "🧾 ثبت سفارش"
BTN_WALLET = "👛 کیف پول"
BTN_GAME = "🎮 بازی"
BTN_CONTACT = "☎️ ارتباط با ما"
BTN_ADMIN = "🛠 مدیریت (ادمین)"

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [BTN_PRODUCTS, BTN_ORDER],
        [BTN_WALLET, BTN_GAME],
        [BTN_CONTACT],
    ]
    + ([[BTN_ADMIN]] if ADMIN_IDS else []),
    resize_keyboard=True,
)

# -------------------------------
# ابزارها
# -------------------------------

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def price_fmt(amount: int) -> str:
    return f"{amount:,} تومان".replace(",", "٬")

async def send_main_menu(update: Update, text: str) -> None:
    if update.message:
        await update.message.reply_text(text, reply_markup=MAIN_MENU)

# -------------------------------
# استارت و کمک
# -------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_main_menu(
        update,
        "سلام! به ربات خوش آمدید.\n"
        "از منوی زیر استفاده کنید. اگر ادمین هستید، گزینه مدیریت برایتان نمایش داده می‌شود.",
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_main_menu(
        update,
        "راهنما:\n"
        f"{BTN_PRODUCTS} — نمایش منو\n"
        f"{BTN_ORDER} — ثبت سفارش\n"
        f"{BTN_WALLET} — موجودی و شارژ کیف پول\n"
        f"{BTN_CONTACT} — ارتباط با ما\n"
        f"{BTN_GAME} — بازی ساده",
    )

# -------------------------------
# محصولات
# -------------------------------

async def products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = db.list_products()
    if not items:
        await send_main_menu(update, "هنوز محصولی ثبت نشده است.")
        return

    if update.message:
        for p in items:
            # p = {id, name, price, photo_url}
            caption = f"#{p['id']} — {p['name']}\nقیمت: {price_fmt(p['price'])}"
            if p.get("photo_url"):
                await update.message.reply_photo(p["photo_url"], caption=caption)
            else:
                await update.message.reply_text(caption)
        await update.message.reply_text("پایان لیست ✅", reply_markup=MAIN_MENU)

# -------------------------------
# سفارش
# -------------------------------

async def order_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    items = db.list_products()
    if not items:
        await send_main_menu(update, "فعلاً محصولی نداریم.")
        return ConversationHandler.END

    keyboard = [[f"{i['id']} — {i['name']} ({price_fmt(i['price'])})"] for i in items]
    keyboard.append(["لغو"])
    await update.message.reply_text(
        "یک محصول انتخاب کنید (با لمس روی خط):", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return ORDER_CHOOSE_PRODUCT

async def order_choose_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if text == "لغو":
        await send_main_menu(update, "سفارش لغو شد.")
        return ConversationHandler.END

    try:
        prod_id = int(text.split("—")[0].strip())
    except Exception:
        await update.message.reply_text("فرمت انتخاب صحیح نیست. دوباره از لیست انتخاب کنید.")
        return ORDER_CHOOSE_PRODUCT

    product = db.get_product(prod_id)
    if not product:
        await update.message.reply_text("محصول یافت نشد. مجدداً انتخاب کنید.")
        return ORDER_CHOOSE_PRODUCT

    context.user_data["order_product"] = product
    await update.message.reply_text(
        f"تعداد {product['name']} را وارد کنید:", reply_markup=ReplyKeyboardMarkup([["1"], ["2"], ["3"], ["لغو"]], resize_keyboard=True)
    )
    return ORDER_SET_QTY

async def order_set_qty(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = (update.message.text or "").strip()
    if txt == "لغو":
        await send_main_menu(update, "سفارش لغو شد.")
        return ConversationHandler.END

    if not txt.isdigit() or int(txt) <= 0:
        await update.message.reply_text("تعداد باید عدد مثبت باشد.")
        return ORDER_SET_QTY

    context.user_data["order_qty"] = int(txt)
    await update.message.reply_text("نام و نام‌خانوادگی را وارد کنید:", reply_markup=ReplyKeyboardRemove())
    return ORDER_GET_NAME

async def order_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["cust_name"] = (update.message.text or "").strip()
    await update.message.reply_text("شماره تماس را وارد کنید (مثلاً 09xxxxxxxxx):")
    return ORDER_GET_PHONE

async def order_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = (update.message.text or "").strip()
    if not (phone.startswith("09") and len(phone) == 11 and phone.isdigit()):
        await update.message.reply_text("شماره تماس معتبر نیست. دوباره وارد کنید:")
        return ORDER_GET_PHONE
    context.user_data["cust_phone"] = phone
    await update.message.reply_text("آدرس کامل را وارد کنید:")
    return ORDER_GET_ADDRESS

async def order_get_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["cust_addr"] = (update.message.text or "").strip()

    product = context.user_data["order_product"]
    qty = context.user_data["order_qty"]
    total = product["price"] * qty

    await update.message.reply_text(
        f"خلاصه سفارش:\n"
        f"محصول: {product['name']} × {qty}\n"
        f"مبلغ: {price_fmt(total)}\n\n"
        "تایید می‌کنید؟ (بله/خیر)",
        reply_markup=ReplyKeyboardMarkup([["بله"], ["خیر"]], resize_keyboard=True),
    )
    return ORDER_CONFIRM

async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    yes = (update.message.text or "").strip() == "بله"
    if not yes:
        await send_main_menu(update, "سفارش لغو شد.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    name = context.user_data["cust_name"]
    phone = context.user_data["cust_phone"]
    addr = context.user_data["cust_addr"]
    product = context.user_data["order_product"]
    qty = context.user_data["order_qty"]
    total = product["price"] * qty

    # ذخیره مشتری و سفارش
    cust_id = db.upsert_customer(user_id=user_id, name=name, phone=phone, address=addr)
    order_id = db.create_order(customer_id=cust_id, product_id=product["id"], qty=qty, total_amount=total)

    # کیف پول و کش‌بک
    cashback_percent = db.get_cashback_percent()  # بر اساس env در db
    cashback_amount = (total * cashback_percent) // 100 if cashback_percent > 0 else 0
    if cashback_amount:
        db.change_wallet_balance(user_id=user_id, delta=cashback_amount, reason=f"Cashback for order {order_id}")

    # اطلاع به کاربر
    msg = (
        f"سفارش #{order_id} با موفقیت ثبت شد ✅\n"
        f"مبلغ: {price_fmt(total)}\n"
        + (f"کش‌بک: {price_fmt(cashback_amount)} به کیف پول شما اضافه شد.\n" if cashback_amount else "")
        + "سپاس از خرید شما 🌟"
    )
    await update.message.reply_text(msg, reply_markup=MAIN_MENU)

    # ارسال به ادمین
    if ADMIN_IDS:
        admin_text = (
            f"🆕 سفارش جدید #{order_id}\n"
            f"کاربر: {name} ({phone})\n"
            f"آدرس: {addr}\n"
            f"محصول: {product['name']} × {qty}\n"
            f"مبلغ: {price_fmt(total)}"
        )
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=aid, text=admin_text)
            except Exception:
                pass

    return ConversationHandler.END

# -------------------------------
# کیف پول
# -------------------------------

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    info = db.get_wallet(user_id)
    balance = info.get("balance", 0)
    keyboard = ReplyKeyboardMarkup(
        [["💳 شارژ کارت به کارت", "💰 شارژ درگاه (به‌زودی)"], ["منو"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        f"موجودی کیف پول شما: {price_fmt(balance)}", reply_markup=keyboard
    )
    return WALLET_TOPUP_METHOD

async def wallet_topup_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = (update.message.text or "").strip()
    if txt == "منو":
        await send_main_menu(update, "برگشت به منو.")
        return ConversationHandler.END

    if txt.startswith("💳"):
        context.user_data["topup_method"] = "card2card"
        await update.message.reply_text("مبلغ شارژ (تومان) را وارد کنید:")
        return WALLET_TOPUP_AMOUNT

    await update.message.reply_text("فعلاً فقط کارت به کارت فعال است. یکی را انتخاب کنید یا «منو».")
    return WALLET_TOPUP_METHOD

async def wallet_topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = (update.message.text or "").replace("٬", "").replace(",", "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await update.message.reply_text("لطفاً مبلغ معتبر وارد کنید:")
        return WALLET_TOPUP_AMOUNT

    context.user_data["topup_amount"] = int(txt)
    await update.message.reply_text(
        f"تایید شارژ {price_fmt(int(txt))} ؟ (بله/خیر)",
        reply_markup=ReplyKeyboardMarkup([["بله"], ["خیر"]], resize_keyboard=True),
    )
    return WALLET_TOPUP_CONFIRM

async def wallet_topup_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if (update.message.text or "").strip() != "بله":
        await send_main_menu(update, "عملیات لغو شد.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    amt = context.user_data.get("topup_amount", 0)
    db.change_wallet_balance(user_id=user_id, delta=amt, reason="manual card2card topup")
    db.record_topup(user_id=user_id, amount=amt, method="card2card", reference="MANUAL")

    await send_main_menu(update, f"✅ کیف پول شما {price_fmt(amt)} شارژ شد.")
    return ConversationHandler.END

# -------------------------------
# ارتباط با ما
# -------------------------------

async def contact_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("پیام خود را بفرستید تا برای ادمین ارسال شود. (برای لغو: منو)")
    return CONTACT_WAIT_MSG

async def contact_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if text == "منو":
        await send_main_menu(update, "لغو شد.")
        return ConversationHandler.END

    u = update.effective_user
    content = f"📩 پیام تماس از {u.full_name} (id={u.id}):\n\n{text}"
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=content)
        except Exception:
            pass

    await send_main_menu(update, "پیام شما برای ادمین ارسال شد. ✅")
    return ConversationHandler.END

# -------------------------------
# بازی ساده
# -------------------------------

async def game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # یک بازی خیلی ساده: تاس
    await update.message.reply_dice()
    await update.message.reply_text("برای امتحان دوباره از /game یا دکمه «🎮 بازی» استفاده کن.", reply_markup=MAIN_MENU)

# -------------------------------
# مدیریت (ادمین) — افزودن/ویرایش محصول
# -------------------------------

def admin_only(update: Update) -> bool:
    return update.effective_user and is_admin(update.effective_user.id)

async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not admin_only(update):
        await update.message.reply_text("دسترسی ندارید.")
        return ConversationHandler.END

    kb = ReplyKeyboardMarkup([["➕ افزودن محصول", "✏️ ویرایش محصول"], ["منو"]], resize_keyboard=True)
    await update.message.reply_text("بخش مدیریت:", reply_markup=kb)
    return ADMIN_EDIT_WAIT_ID

async def admin_route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not admin_only(update):
        await update.message.reply_text("دسترسی ندارید.")
        return ConversationHandler.END

    txt = (update.message.text or "").strip()
    if txt == "➕ افزودن محصول":
        await update.message.reply_text("نام محصول را وارد کنید:", reply_markup=ReplyKeyboardRemove())
        return ADMIN_ADD_NAME
    elif txt == "✏️ ویرایش محصول":
        items = db.list_products()
        if not items:
            await send_main_menu(update, "فعلاً محصولی نداریم.")
            return ConversationHandler.END
        lines = [f"{i['id']} — {i['name']}" for i in items]
        await update.message.reply_text("ID محصول را از لیست زیر انتخاب/ارسال کنید:\n" + "\n".join(lines))
        return ADMIN_EDIT_WAIT_ID
    else:
        await send_main_menu(update, "بازگشت به منو.")
        return ConversationHandler.END

# افزودن
async def admin_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["p_name"] = (update.message.text or "").strip()
    await update.message.reply_text("قیمت را به تومان وارد کنید:")
    return ADMIN_ADD_PRICE

async def admin_add_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = (update.message.text or "").replace("٬", "").replace(",", "").strip()
    if not txt.isdigit():
        await update.message.reply_text("قیمت نامعتبر است. عدد وارد کنید:")
        return ADMIN_ADD_PRICE
    context.user_data["p_price"] = int(txt)
    await update.message.reply_text("لینک عکس محصول (اختیاری) را ارسال کنید یا بنویسید «ندارد».")
    return ADMIN_ADD_PHOTO

async def admin_add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo_url = (update.message.text or "").strip()
    if photo_url == "ندارد":
        photo_url = ""

    db.add_product(
        name=context.user_data["p_name"],
        price=context.user_data["p_price"],
        photo_url=photo_url,
    )
    await send_main_menu(update, "✅ محصول اضافه شد.")
    return ConversationHandler.END

# ویرایش
async def admin_edit_wait_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = (update.message.text or "").strip()
    if not txt or not any(ch.isdigit() for ch in txt):
        await update.message.reply_text("ID معتبر ارسال کنید:")
        return ADMIN_EDIT_WAIT_ID

    prod_id = int("".join(ch for ch in txt if ch.isdigit()))
    prod = db.get_product(prod_id)
    if not prod:
        await update.message.reply_text("محصول یافت نشد. ID دیگری وارد کنید:")
        return ADMIN_EDIT_WAIT_ID

    context.user_data["edit_id"] = prod_id
    kb = ReplyKeyboardMarkup([["name", "price", "photo_url"], ["منو"]], resize_keyboard=True)
    await update.message.reply_text("کدام فیلد را می‌خواهید تغییر دهید؟ (name/price/photo_url)", reply_markup=kb)
    return ADMIN_EDIT_FIELD

async def admin_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    f = (update.message.text or "").strip()
    if f == "منو":
        await send_main_menu(update, "لغو شد.")
        return ConversationHandler.END

    if f not in {"name", "price", "photo_url"}:
        await update.message.reply_text("فقط name یا price یا photo_url.")
        return ADMIN_EDIT_FIELD

    context.user_data["edit_field"] = f
    await update.message.reply_text("مقدار جدید را ارسال کنید:", reply_markup=ReplyKeyboardRemove())
    return ADMIN_EDIT_VALUE

async def admin_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.message.text or "").strip()
    field = context.user_data["edit_field"]
    prod_id = context.user_data["edit_id"]

    if field == "price":
        v = value.replace("٬", "").replace(",", "")
        if not v.isdigit():
            await update.message.reply_text("قیمت باید عدد باشد. دوباره ارسال کنید:")
            return ADMIN_EDIT_VALUE
        value = int(v)

    db.update_product(prod_id, field, value)
    await send_main_menu(update, "✅ تغییرات ذخیره شد.")
    return ConversationHandler.END

# -------------------------------
# رجیستر همه هندلرها
# -------------------------------

def register(application: Application) -> None:
    # دستورات متنی فارسی روی کیبورد — همه از طریق MessageHandler مدیریت می‌شوند
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("products", products))
    application.add_handler(CommandHandler("order", order_entry))
    application.add_handler(CommandHandler("wallet", wallet))
    application.add_handler(CommandHandler("game", game))
    application.add_handler(CommandHandler("contact", contact_entry))
    if ADMIN_IDS:
        application.add_handler(CommandHandler("admin", admin_entry))

    # منوی فارسی (MessageHandler)
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_PRODUCTS}$"), products))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_ORDER}$"), order_entry))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_WALLET}$"), wallet))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_GAME}$"), game))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_CONTACT}$"), contact_entry))
    if ADMIN_IDS:
        application.add_handler(MessageHandler(filters.Regex(f"^{BTN_ADMIN}$"), admin_entry))

    # گفتگو: سفارش
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("order", order_entry), MessageHandler(filters.Regex(f"^{BTN_ORDER}$"), order_entry)],
            states={
                ORDER_CHOOSE_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_choose_product)],
                ORDER_SET_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_set_qty)],
                ORDER_GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_get_name)],
                ORDER_GET_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_get_phone)],
                ORDER_GET_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_get_address)],
                ORDER_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_confirm)],
            },
            fallbacks=[CommandHandler("start", start)],
            allow_reentry=True,
        )
    )

    # گفتگو: کیف پول/شارژ
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("wallet", wallet), MessageHandler(filters.Regex(f"^{BTN_WALLET}$"), wallet)],
            states={
                WALLET_TOPUP_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_topup_method)],
                WALLET_TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_topup_amount)],
                WALLET_TOPUP_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_topup_confirm)],
            },
            fallbacks=[CommandHandler("start", start)],
            allow_reentry=True,
        )
    )

    # گفتگو: ارتباط با ما
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("contact", contact_entry), MessageHandler(filters.Regex(f"^{BTN_CONTACT}$"), contact_entry)],
            states={CONTACT_WAIT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_forward)]},
            fallbacks=[CommandHandler("start", start)],
            allow_reentry=True,
        )
    )

    # مدیریت (ادمین)
    if ADMIN_IDS:
        application.add_handler(
            ConversationHandler(
                entry_points=[CommandHandler("admin", admin_entry), MessageHandler(filters.Regex(f"^{BTN_ADMIN}$"), admin_entry)],
                states={
                    ADMIN_EDIT_WAIT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_route),
                                         MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_wait_id)],
                    ADMIN_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_name)],
                    ADMIN_ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_price)],
                    ADMIN_ADD_PHOTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_photo)],
                    ADMIN_EDIT_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_field)],
                    ADMIN_EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_value)],
                },
                fallbacks=[CommandHandler("start", start)],
                allow_reentry=True,
            )
        )

# -------------------------------
# راه‌اندازی اولیه پس از استارت اپ
# -------------------------------

async def startup_warmup(application: Application) -> None:
    """
    این تابع توسط ApplicationBuilder.post_init(...) صدا می‌شود
    (در فایل bot.py تنظیمش کن) و کارهای اولیه را انجام می‌دهد.
    """
    # 1) اطمینان از ساخت جداول
    try:
        db.ensure_schema()
    except Exception as e:
        print("DB ensure_schema error:", e)

    # 2) پیام خوش‌آمد به ادمین‌ها
    for aid in ADMIN_IDS:
        try:
            await application.bot.send_message(
                chat_id=aid,
                text="✅ سرویس بوت تلگرام بالا آمد و آماده دریافت دستورات است.",
            )
        except Exception:
            pass
