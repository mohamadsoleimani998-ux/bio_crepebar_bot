import os
from typing import List, Dict

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, filters,
    ConversationHandler, CallbackQueryHandler
)

from . import db

# ---------- ENV ----------
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
PUBLIC_URL = os.getenv("PUBLIC_URL", "")
CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "3"))

# ---------- STATES ----------
(
    ST_ORDER_ADDRESS,
    ST_ORDER_PHONE,
    ST_ADMIN_ADD_TITLE,
    ST_ADMIN_ADD_PRICE,
    ST_ADMIN_ADD_PHOTO,
    ST_SET_NAME,
    ST_SET_ADDRESS,
    ST_SET_PHONE,
    ST_WALLET_CARD2CARD_AMOUNT,
) = range(9)

# ---------- UTIL ----------
MAIN_KB = ReplyKeyboardMarkup(
    [
        ["منو 🍬", "سفارش 🧾"],
        ["کیف پول 👛", "بازی 🎮"],
        ["ارتباط با ما 📞", "راهنما ℹ️"]
    ], resize_keyboard=True
)

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ---------- HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    # ثبت/به‌روزرسانی کاربر
    db.upsert_user(u.id, u.full_name or u.username or str(u.id))
    text = (
        "سلام! 👋 به ربات بایو کِرِپ بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات با اسم، قیمت و عکس\n"
        "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
        f"• کیف پول: مشاهده/شارژ، کش‌بک {CASHBACK_PERCENT}% بعد هر خرید\n"
        "• بازی: سرگرمی 🎮\n"
        "• ارتباط با ما: پیام به ادمین\n"
        "• راهنما: دستورها"
    )
    await update.effective_chat.send_message(text, reply_markup=MAIN_KB)

# --- Menu (products) ---
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products()
    if not prods:
        await update.effective_chat.send_message("فعلاً محصولی ثبت نشده.")
        if is_admin(update.effective_user.id):
            await update.effective_chat.send_message("ادمین: با /addproduct محصول اضافه کن.")
        return
    for p in prods:
        cap = f"#{p['id']} — {p['title']}\nقیمت: {p['price']:,} تومان"
        if p.get("photo"):
            await update.effective_chat.send_photo(p["photo"], cap)
        else:
            await update.effective_chat.send_message(cap)

# --- Order flow ---
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products()
    if not prods:
        await update.effective_chat.send_message("فعلاً محصولی نداریم.")
        return ConversationHandler.END

    lines = ["لطفاً شناسه و تعداد هر محصول را به فرم زیر بفرست:",
             "مثال: 1x2, 3x1  (یعنی: محصول 1 تعداد 2 تا، محصول 3 تعداد 1)"]
    await update.effective_chat.send_message("\n".join(lines))
    context.user_data["cart"] = None
    # از کاربر در همین پیام بعدی، آدرس و شماره را به تفکیک می‌گیریم
    await update.effective_chat.send_message("آدرس ارسال را بفرست:")
    return ST_ORDER_ADDRESS

async def order_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text.strip()
    await update.effective_chat.send_message("شماره تماس را بفرست:")
    return ST_ORDER_PHONE

async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data["phone"] = phone
    # برای سادگی، سبد خرید را از آخرین لیست محصولات می‌گیریم
    await update.effective_chat.send_message(
        "عالی! حالا شناسه و تعداد محصول‌ها را به شکل «1x2, 3x1» ارسال کن."
    )
    context.user_data["expect_cart"] = True
    return ConversationHandler.END  # پیام بعدی را MessageHandler عمومی می‌گیرد

async def collect_cart_and_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هر وقت expect_cart=True بود، این پیام را سبد خرید فرض می‌کنیم و سفارش می‌سازیم."""
    if not context.user_data.get("expect_cart"):
        return

    txt = update.message.text.replace(" ", "")
    items: List[Dict] = []
    ok = True
    for chunk in txt.split(","):
        if "x" not in chunk:
            ok = False; break
        pid_s, qty_s = chunk.split("x", 1)
        if not (pid_s.isdigit() and qty_s.isdigit()):
            ok = False; break
        items.append({"product_id": int(pid_s), "qty": int(qty_s)})
    if not ok or not items:
        await update.effective_chat.send_message("فرمت درست نیست. مثل «1x2, 3x1» بفرست.")
        return

    context.user_data["expect_cart"] = False
    # ذخیره اطلاعات تماس در پروفایل
    db.set_user_contact(update.effective_user.id,
                        phone=context.user_data.get("phone"),
                        address=context.user_data.get("address"))
    # ساخت سفارش
    order = db.create_order(update.effective_user.id, items,
                            context.user_data.get("address", ""),
                            context.user_data.get("phone", ""))

    # اطلاع به کاربر
    await update.effective_chat.send_message(
        f"سفارش ثبت شد ✅\n"
        f"کد سفارش: {order['id']}\n"
        f"مبلغ: {order['total']:,} تومان\n"
        f"کش‌بک: {order['cashback']:,} تومان به کیف پول اضافه شد."
    )
    # پیام برای ادمین
    admin_text = (
        f"🆕 سفارش جدید #{order['id']}\n"
        f"کاربر: {update.effective_user.full_name} ({update.effective_user.id})\n"
        f"مبلغ: {order['total']:,}\n"
        f"آدرس: {order['address']}\n"
        f"شماره: {order['phone']}\n"
        f"آیتم‌ها: {items}"
    )
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=admin_text)
        except Exception:
            pass

# --- Wallet ---
async def wallet_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = db.get_wallet(update.effective_user.id)
    kb = ReplyKeyboardMarkup(
        [["شارژ کارت‌به‌کارت 💳", "بازگشت ⬅️"]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await update.effective_chat.send_message(
        f"موجودی کیف پول: {w:,} تومان", reply_markup=kb
    )

async def wallet_c2c_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("مبلغ شارژ (تومان) را بفرست:")
    return ST_WALLET_CARD2CARD_AMOUNT

async def wallet_c2c_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amt_txt = update.message.text.replace(",", "").strip()
    if not amt_txt.isdigit():
        await update.effective_chat.send_message("فقط عدد بفرست.")
        return ST_WALLET_CARD2CARD_AMOUNT
    amt = int(amt_txt)
    db.adjust_wallet(update.effective_user.id, amt)
    await update.effective_chat.send_message(f"شارژ شد ✅ موجودی جدید: {db.get_wallet(update.effective_user.id):,} تومان",
                                             reply_markup=MAIN_KB)
    # اطلاع به ادمین
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, f"شارژ کارت‌به‌کارت کاربر {update.effective_user.id}: +{amt:,}")
        except Exception:
            pass
    return ConversationHandler.END

# --- Admin: add product ---
async def addproduct_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.effective_chat.send_message("نام محصول را بفرست:")
    return ST_ADMIN_ADD_TITLE

async def addproduct_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_title"] = update.message.text.strip()
    await update.effective_chat.send_message("قیمت (تومان) را بفرست:")
    return ST_ADMIN_ADD_PRICE

async def addproduct_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.replace(",", "").strip()
    if not txt.isdigit():
        await update.effective_chat.send_message("قیمت باید عدد باشد. دوباره بفرست:")
        return ST_ADMIN_ADD_PRICE
    context.user_data["p_price"] = int(txt)
    await update.effective_chat.send_message("اگر عکس داری بفرست؛ اگر نه «رد» بنویس.")
    return ST_ADMIN_ADD_PHOTO

async def addproduct_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_url = None
    if update.message.photo:
        # فایل‌ آیدی تلگرام را ذخیره می‌کنیم تا نمایش سریع باشد
        photo_url = update.message.photo[-1].file_id
    elif update.message.text and update.message.text.strip() != "رد":
        photo_url = update.message.text.strip()

    p = db.add_product(context.user_data["p_title"], context.user_data["p_price"], photo_url)
    await update.effective_chat.send_message(f"محصول ذخیره شد ✅\n#{p['id']} — {p['title']} ({p['price']:,} تومان)",
                                             reply_markup=MAIN_KB)
    return ConversationHandler.END

# --- Play tab ---
async def play_tab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # یک بازی ساده دایس
    await update.effective_chat.send_dice()
    await update.effective_chat.send_message("برای منوی اصلی /start رو بزن یا از دکمه‌ها استفاده کن.")

# --- Contact us ---
async def contact_tab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("پیامت رو بفرست تا برای ادمین ارسال بشه.")
    context.user_data["expect_contact_msg"] = True

async def catch_contact_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("expect_contact_msg"):
        return
    context.user_data["expect_contact_msg"] = False
    txt = f"📩 پیام از {update.effective_user.full_name} ({update.effective_user.id}):\n{update.message.text}"
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, txt)
        except Exception:
            pass
    await update.effective_chat.send_message("پیامت به ادمین ارسال شد ✅", reply_markup=MAIN_KB)

# --- Help ---
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "دستورها:\n"
        "/start — منوی اصلی\n"
        "/addproduct — افزودن محصول (ادمین)\n"
        "/menu — نمایش منو\n"
        "/wallet — کیف پول\n"
        "/order — ثبت سفارش\n"
    )

# ---------- REGISTER ----------
def register(application):
    # اطمینان از آماده بودن دیتابیس
    db.init_db()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("order", order_start))
    application.add_handler(CommandHandler("wallet", wallet_panel))
    application.add_handler(CommandHandler("addproduct", addproduct_cmd, filters.User(user_id=list(ADMIN_IDS))))

    # دکمه‌های فارسی
    application.add_handler(MessageHandler(filters.Regex("^منو"), show_menu))
    application.add_handler(MessageHandler(filters.Regex("^سفارش"), order_start))
    application.add_handler(MessageHandler(filters.Regex("^کیف پول"), wallet_panel))
    application.add_handler(MessageHandler(filters.Regex("^بازی"), play_tab))
    application.add_handler(MessageHandler(filters.Regex("^ارتباط با ما"), contact_tab))
    application.add_handler(MessageHandler(filters.Regex("^راهنما"), help_cmd))
    application.add_handler(MessageHandler(filters.Regex("^بازگشت"), start))

    # جریان افزودن محصول (ادمین)
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addproduct", addproduct_cmd, filters.User(user_id=list(ADMIN_IDS)))],
        states={
            ST_ADMIN_ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_title)],
            ST_ADMIN_ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_price)],
            ST_ADMIN_ADD_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, addproduct_photo)],
        },
        fallbacks=[CommandHandler("start", start)],
        name="addproduct_flow",
        persistent=False
    ))

    # جریان سفارش: گرفتن آدرس و شماره
    application.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^سفارش"), order_start), CommandHandler("order", order_start)],
        states={
            ST_ORDER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            ST_ORDER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
        },
        fallbacks=[CommandHandler("start", start)],
        name="order_flow",
        persistent=False
    ))

    # شارژ کارت‌به‌کارت
    application.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^شارژ کارت‌به‌کارت"), wallet_c2c_start)],
        states={
            ST_WALLET_CARD2CARD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_c2c_amount)],
        },
        fallbacks=[CommandHandler("start", start)],
        name="wallet_c2c",
        persistent=False
    ))

    # پیام آزاد: اگر انتظار سبد خرید یا پیامِ ارتباط با ما داریم
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_cart_and_finish))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, catch_contact_msg))
