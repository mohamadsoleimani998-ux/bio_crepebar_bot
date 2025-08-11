import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler
import db

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

def is_admin(user_id):
    return user_id in ADMIN_IDS

def start(update: Update, context: CallbackContext):
    user = db.get_or_create_user(
        tg_id=update.effective_user.id,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
        username=update.effective_user.username
    )
    reply_text = "سلام! به ربات خوش آمدید.\n" \
                 "دستورات:\n" \
                 "/products - نمایش منو\n" \
                 "/wallet - موجودی کیف پول\n" \
                 "/order - ثبت سفارش\n" \
                 "/help - راهنما"

    keyboard = [
        ["/products", "/wallet"],
        ["/order", "/help"]
    ]
    update.message.reply_text(reply_text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "راهنما:\n"
        "/products - نمایش منو\n"
        "/wallet - کیف پول\n"
        "/order - ثبت سفارش ساده"
    )

def wallet(update: Update, context: CallbackContext):
    user = db.get_or_create_user(update.effective_user.id)
    cents = db.get_wallet(user["id"])
    update.message.reply_text(f"موجودی کیف پول شما: {cents // 100} تومان")

def products(update: Update, context: CallbackContext):
    items = db.list_products()
    if not items:
        update.message.reply_text("هیچ محصولی ثبت نشده است.")
        return
    text = "منو:\n"
    for p in items:
        text += f"{p['id']}. {p['name']} - {p['price_cents'] // 100} تومان\n"
    update.message.reply_text(text)

def order(update: Update, context: CallbackContext):
    args = context.args
    if len(args) < 2:
        update.message.reply_text("برای سفارش: /order <شناسه_محصول> <تعداد>")
        return
    try:
        product_id = int(args[0])
        qty = int(args[1])
    except ValueError:
        update.message.reply_text("شناسه یا تعداد نامعتبر است.")
        return

    user = db.get_or_create_user(update.effective_user.id)
    try:
        res = db.create_order_with_cashback(user["id"], product_id, qty)
    except ValueError as e:
        update.message.reply_text(str(e))
        return

    update.message.reply_text(
        f"سفارش ثبت شد!\n"
        f"محصول: {res['product']['name']}\n"
        f"تعداد: {res['qty']}\n"
        f"مبلغ: {res['total_cents'] // 100} تومان\n"
        f"کش‌بک: {res['cashback_cents'] // 100} تومان"
    )

def add_product(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("دسترسی ندارید.")
        return
    args = context.args
    if len(args) < 2:
        update.message.reply_text("برای افزودن: /addproduct <نام> <قیمت_تومان>")
        return
    try:
        name = args[0]
        price_t = int(args[1])
        pid = db.add_product(name, price_t * 100)
        update.message.reply_text(f"محصول با شناسه {pid} اضافه شد.")
    except ValueError:
        update.message.reply_text("قیمت باید عدد باشد.")

def set_cashback(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        update.message.reply_text("دسترسی ندارید.")
        return
    if not context.args or not context.args[0].isdigit():
        update.message.reply_text("درصد کش‌بک معتبر نیست.")
        return
    db.set_cashback_percent(int(context.args[0]))
    update.message.reply_text("درصد کش‌بک تنظیم شد.")

def register_handlers(dp):
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("wallet", wallet))
    dp.add_handler(CommandHandler("products", products))
    dp.add_handler(CommandHandler("order", order))
    dp.add_handler(CommandHandler("addproduct", add_product))
    dp.add_handler(CommandHandler("setcashback", set_cashback))
