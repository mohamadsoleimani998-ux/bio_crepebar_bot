# src/handlers.py
from __future__ import annotations
import os
from typing import Final

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InputMediaPhoto
)
from telegram.ext import (
    Application, ContextTypes, CommandHandler, MessageHandler, ConversationHandler,
    filters
)

import src.db as db

# -------- پیکربندی
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
CASHBACK = int(os.environ.get("CASHBACK_PERCENT", "3"))  # درصد کش‌بک

# -------- کیبورد اصلی
MAIN_BTNS = [
    [KeyboardButton("منو 🍬"), KeyboardButton("سفارش 🧾")],
    [KeyboardButton("کیف پول 👜"), KeyboardButton("بازی 🎮")],
    [KeyboardButton("ارتباط با ما ☎️"), KeyboardButton("راهنما ℹ️")],
]
MAIN_KB = ReplyKeyboardMarkup(MAIN_BTNS, resize_keyboard=True)

# -------- استارتاپ: ساخت جداول
async def startup_warmup(app: Application):
    db.init_db()

# -------- /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name)
    text = (
        "سلام! 👋 به ربات بایو کرپ بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات با اسم، قیمت و عکس\n"
        "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
        "• کیف پول: مشاهده و شارژ (کارت‌به‌کارت / درگاه در آینده)\n"
        f"• کش‌بک: بعد از هر خرید {CASHBACK}% به کیف پول اضافه می‌شود\n"
        "• بازی: تب سرگرمی\n"
        "• ارتباط با ما: پیام به ادمین\n"
    )
    await update.message.reply_text(text, reply_markup=MAIN_KB)

# -------- تب راهنما
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("برای استفاده از ربات از دکمه‌های زیر استفاده کن.", reply_markup=MAIN_KB)

# -------- تب منو (نمایش محصولات)
async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = db.list_products()
    if not items:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.", reply_markup=MAIN_KB)
        return
    # ارسال هر محصول با عکس اگر بود
    for p in items:
        caption = f"🍬 {p['name']}\n💵 قیمت: {p['price']:,} تومان"
        if p["image_file_id"]:
            await update.message.reply_photo(p["image_file_id"], caption=caption)
        else:
            await update.message.reply_text(caption)

# -------- تب سفارش (ساده: انتخاب نام محصول و تعداد)
ORDER_WAIT_NAME, ORDER_WAIT_QTY, ORDER_CONFIRM = range(200, 203)

async def order_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products()
    if not prods:
        await update.message.reply_text("فعلاً محصولی نداریم.", reply_markup=MAIN_KB)
        return ConversationHandler.END
    names = "، ".join(p["name"] for p in prods)
    await update.message.reply_text(f"نام محصول موردنظر را بفرست.\nمحصولات: {names}")
    return ORDER_WAIT_NAME

async def order_set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    # پیدا کردن محصول
    prod = next((p for p in db.list_products() if p["name"] == name), None)
    if not prod:
        await update.message.reply_text("نام محصول یافت نشد. دوباره نام صحیح را بفرست.")
        return ORDER_WAIT_NAME
    context.user_data["prod"] = prod
    await update.message.reply_text("تعداد را وارد کن (عدد).")
    return ORDER_WAIT_QTY

async def order_set_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("عدد صحیح ارسال کن.")
        return ORDER_WAIT_QTY
    prod = context.user_data["prod"]
    total = prod["price"] * qty
    context.user_data["qty"] = qty
    context.user_data["total"] = total
    await update.message.reply_text(f"تأیید می‌کنی؟\nمحصول: {prod['name']}\nتعداد: {qty}\nمبلغ: {total:,} تومان\n(بفرست: تایید / انصراف)")
    return ORDER_CONFIRM

async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text not in ("تایید", "تاييد", "confirm", "ok"):
        await update.message.reply_text("سفارش لغو شد.", reply_markup=MAIN_KB)
        return ConversationHandler.END
    user = update.effective_user
    prod = context.user_data["prod"]
    qty = context.user_data["qty"]
    total = context.user_data["total"]

    # ثبت سفارش
    order_id = db.create_order(user.id, prod["id"], qty, total)

    # کش‌بک
    cashback_amount = (total * CASHBACK) // 100
    if cashback_amount:
        db.change_wallet(user.id, cashback_amount)

    # اطلاع به کاربر
    await update.message.reply_text(
        f"سفارش شما ثبت شد ✅\nشماره سفارش: {order_id}\nمبلغ: {total:,} تومان\n"
        f"کش‌بک واریز شد: {cashback_amount:,} تومان",
        reply_markup=MAIN_KB
    )
    # پیام به ادمین
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, f"سفارش جدید #{order_id}\nکاربر: {user.full_name} ({user.id})\n{prod['name']} x{qty}\nمبلغ: {total:,}")
        except Exception:
            pass
    return ConversationHandler.END

async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("انصراف دادی.", reply_markup=MAIN_KB)
    return ConversationHandler.END

# -------- تب کیف پول
async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    row = db.get_user(u.id)
    bal = row["wallet"] if row else 0
    await update.message.reply_text(
        f"موجودی کیف پول: {bal:,} تومان\nبرای شارژ کارت‌به‌کارت رسید را همینجا ارسال کن. (درگاه؛ به‌زودی)",
        reply_markup=MAIN_KB
    )

# -------- تب بازی (ساده)
async def game_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎮 بازی به‌زودی! فعلاً هر روز یک کش‌بک شانسی داریم 😉", reply_markup=MAIN_KB)

# -------- تب ارتباط با ما
async def contact_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام خودت را بفرست تا برای ادمین ارسال شود.", reply_markup=MAIN_KB)

# فوروارد پیام کاربر به ادمین‌ها
async def forward_to_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.text in None:
        return
    txt = update.message.text
    if txt in {"منو 🍬", "سفارش 🧾", "کیف پول 👜", "بازی 🎮", "ارتباط با ما ☎️", "راهنما ℹ️"}:
        return  # اینها پیام‌های تب‌هاست
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, f"پیام کاربر {update.effective_user.id}:\n{txt}")
        except Exception:
            pass

# -------- پنل ادمین: افزودن محصول
ADD_NAME, ADD_PRICE, ADD_PHOTO = range(300, 303)

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("➕ افزودن محصول"), KeyboardButton("🗒 لیست محصولات")],
         [KeyboardButton("🗑 حذف محصول"), KeyboardButton("بازگشت")]],
        resize_keyboard=True
    )
    await update.message.reply_text("پنل ادمین:", reply_markup=kb)

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    txt = update.message.text.strip()
    if txt == "➕ افزودن محصول":
        await update.message.reply_text("نام محصول را بفرست:")
        return ADD_NAME
    if txt == "🗒 لیست محصولات":
        items = db.list_products()
        if not items:
            await update.message.reply_text("لیست خالی است.")
        else:
            msg = "\n".join([f"{p['id']}. {p['name']} — {p['price']:,}" for p in items])
            await update.message.reply_text(msg)
        return ConversationHandler.END
    if txt == "🗑 حذف محصول":
        await update.message.reply_text("نام محصولی که باید حذف شود را بفرست:")
        context.user_data["del_mode"] = True
        return ADD_NAME
    if txt == "بازگشت":
        await update.message.reply_text("برگشتی.", reply_markup=MAIN_KB)
        return ConversationHandler.END

async def add_set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("del_mode"):
        name = update.message.text.strip()
        cnt = db.delete_product_by_name(name)
        context.user_data.pop("del_mode", None)
        if cnt:
            await update.message.reply_text("حذف شد ✅", reply_markup=MAIN_KB)
        else:
            await update.message.reply_text("چیزی با این نام پیدا نشد.", reply_markup=MAIN_KB)
        return ConversationHandler.END

    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("قیمت را به تومان بفرست (عدد):")
    return ADD_PRICE

async def add_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("عدد صحیح بفرست.")
        return ADD_PRICE
    context.user_data["price"] = price
    await update.message.reply_text("حالا عکس محصول را ارسال کن. اگر عکس نداری بنویس: «بدون عکس».")
    return ADD_PHOTO

async def add_set_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    image_id = None
    if update.message.photo:
        image_id = update.message.photo[-1].file_id
    # اگر متن «بدون عکس» بود، image_id همون None می‌مونه
    pid = db.add_product(context.user_data["name"], context.user_data["price"], image_id)
    await update.message.reply_text(f"ثبت شد ✅ (ID: {pid})", reply_markup=MAIN_KB)
    context.user_data.clear()
    return ConversationHandler.END

async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("لغو شد.", reply_markup=MAIN_KB)
    return ConversationHandler.END

# -------- ثبت هندلرها
def register(application: Application):
    # استارت
    application.add_handler(CommandHandler(["start", "شروع"], start))
    # تب‌ها با کامند و با متن دکمه
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(MessageHandler(filters.Regex("^راهنما") | filters.Command("راهنما"), help_cmd))

    application.add_handler(MessageHandler(filters.Regex("^منو") | filters.Command("منو"), menu_cmd))
    application.add_handler(MessageHandler(filters.Regex("^کیف پول") | filters.Command("کیف_پول"), wallet_cmd))
    application.add_handler(MessageHandler(filters.Regex("^بازی") | filters.Command("بازی"), game_cmd))
    application.add_handler(MessageHandler(filters.Regex("^ارتباط با ما") | filters.Command("ارتباط"), contact_cmd))

    # سفارش
    application.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^سفارش") | filters.Command("سفارش"), order_entry)],
        states={
            ORDER_WAIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_set_name)],
            ORDER_WAIT_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_set_qty)],
            ORDER_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_confirm)],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
        name="order_flow", persistent=False
    ))

    # پنل ادمین
    application.add_handler(CommandHandler(["admin", "ادمین"], admin_entry))
    application.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(➕ افزودن محصول|🗒 لیست محصولات|🗑 حذف محصول|بازگشت)$"), admin_buttons)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_set_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_set_price)],
            ADD_PHOTO: [
                MessageHandler(filters.PHOTO, add_set_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_set_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        name="admin_add_product", persistent=False
    ))

    # فوروارد پیام‌های آزاد به ادمین (برای «ارتباط با ما»)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_to_admins))
