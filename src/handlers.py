from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, ConversationHandler, filters
)
from .base import log, ADMIN_IDS, CASHBACK_PERCENT
from . import db

# --- کیبورد اصلی ---
MAIN_KBD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("منو 🍬"), KeyboardButton("سفارش 🧾")],
        [KeyboardButton("کیف پول 👛"), KeyboardButton("بازی 🎮")],
        [KeyboardButton("ارتباط با ما ☎️"), KeyboardButton("راهنما ℹ️")],
    ],
    resize_keyboard=True
)

# --- /start ---
async def start(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.id, u.full_name or (u.first_name or ""))
    txt = (
        "سلام! 👋 به ربات بایو کرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات با نام، قیمت و عکس\n"
        "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
        f"• کیف پول: مشاهده/شارژ، کش‌بک {CASHBACK_PERCENT}% بعد هر خرید\n"
        "• بازی: سرگرمی\n"
        "• ارتباط با ما: پیام به ادمین\n"
        "• راهنما: دستورها"
    )
    await update.message.reply_text(txt, reply_markup=MAIN_KBD)

# --- منو ---
async def menu_(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    prods = db.list_products()
    if not prods:
        await update.message.reply_text("فعلاً محصولی ثبت نشده.\nادمین: با /addproduct محصول اضافه کن.")
        return
    # ارسال به صورت فهرست (اگر عکس داشت آلبوم می‌فرستیم)
    media = []
    for p in prods[:10]:
        caption = f"<b>{p['name']}</b>\nقیمت: {p['price']:,} تومان"
        if p.get("description"):
            caption += f"\n{p['description']}"
        if p.get("photo_file_id"):
            media.append(InputMediaPhoto(p["photo_file_id"], caption=caption, parse_mode="HTML"))
    if media:
        await update.message.reply_media_group(media)
    # متن لیست ساده
    lines = [f"• {p['name']} — {p['price']:,} تومان" for p in prods]
    await update.message.reply_text("\n".join(lines))

# --- کیف پول ---
async def wallet(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    bal = db.get_balance(update.effective_user.id)
    btn = ReplyKeyboardMarkup([[KeyboardButton("شارژ کارت‌به‌کارت")]], resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text(
        f"موجودی شما: {bal:,} تومان\nکش‌بک فعال: {CASHBACK_PERCENT}% ", reply_markup=btn
    )

async def wallet_topup(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    text = (
        "👛 شارژ کارت‌به‌کارت\n"
        "مبلغ دلخواه را به کارت زیر واریز کنید و رسید را برای ادمین بفرستید:\n"
        "<code>5029-0810-8098-4145</code>\n\n"
        "پس از تایید، کیف پول شما شارژ می‌شود."
    )
    await update.message.reply_text(text)

# --- بازی ---
async def game(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("...بزودی🎲")

# --- راهنما / ارتباط ---
async def help_(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("برای سفارش «سفارش 🧾» را بزن. برای مشاهده منو «منو 🍬».")

async def contact(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("برای ارتباط: همینجا پیام بده تا ادمین ببیند.")

# ---------------- Admin: افزودن محصول ----------------
AP_NAME, AP_PRICE, AP_PHOTO, AP_DESC = range(4)

async def addproduct_cmd(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text("دسترسی نداری.")
    await update.message.reply_text("نام محصول را بفرست:")
    return AP_NAME

async def ap_name(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ap_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان) را بفرست:")
    return AP_PRICE

async def ap_price(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    try:
        price = int("".join(ch for ch in update.message.text if ch.isdigit()))
    except Exception:
        return await update.message.reply_text("قیمت نامعتبر است. عدد بفرست.")
    ctx.user_data["ap_price"] = price
    await update.message.reply_text("عکس محصول را بفرست (یا بنویس «بدون عکس»):")
    return AP_PHOTO

async def ap_photo(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    if update.message.text and "بدون" in update.message.text:
        ctx.user_data["ap_photo"] = None
    else:
        if not update.message.photo:
            return await update.message.reply_text("عکس نامعتبر. دوباره ارسال کن یا بنویس «بدون عکس».")
        ctx.user_data["ap_photo"] = update.message.photo[-1].file_id
    await update.message.reply_text("توضیحات کوتاه (اختیاری) را بفرست. اگر نمی‌خواهی بنویس «بدون توضیحات».")
    return AP_DESC

async def ap_desc(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    desc = "" if (update.message.text and "بدون" in update.message.text) else (update.message.text or "")
    name = ctx.user_data.get("ap_name")
    price = ctx.user_data.get("ap_price")
    photo = ctx.user_data.get("ap_photo")
    db.add_product(name, price, photo, desc)
    await update.message.reply_text("✅ محصول ذخیره شد.")
    return ConversationHandler.END

async def ap_cancel(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.")
    return ConversationHandler.END

# ---------- ثبت‌نام ساده (نام/تلفن/آدرس) ----------
REG_NAME, REG_PHONE, REG_ADDR = range(10,13)

async def register_cmd(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اسم شما؟")
    return REG_NAME

async def reg_name(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    ctx.user_data["r_name"] = update.message.text.strip()
    await update.message.reply_text("شماره موبایل؟")
    return REG_PHONE

async def reg_phone(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    ctx.user_data["r_phone"] = update.message.text.strip()
    await update.message.reply_text("آدرس کامل؟")
    return REG_ADDR

async def reg_addr(update:Update, ctx:ContextTypes.DEFAULT_TYPE):
    db.set_profile(
        update.effective_user.id,
        name=ctx.user_data.get("r_name"),
        phone=ctx.user_data.get("r_phone"),
        address=update.message.text.strip()
    )
    await update.message.reply_text("✅ ثبت‌نام/ویرایش پروفایل انجام شد.", reply_markup=MAIN_KBD)
    return ConversationHandler.END

# ----------------- ثبت هندلرها -----------------
def build_handlers():
    # Command handlers
    hs = [
        CommandHandler("start", start),
        CommandHandler("help", help_),
        CommandHandler("register", register_cmd),
        CommandHandler("wallet", wallet),
        CommandHandler("menu", menu_),
    ]

    # Admin addproduct conversation
    hs.append(ConversationHandler(
        entry_points=[CommandHandler("addproduct", addproduct_cmd)],
        states={
            AP_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_name)],
            AP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_price)],
            AP_PHOTO: [MessageHandler((filters.PHOTO | filters.Regex("(?i)^بدون")), ap_photo)],
            AP_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_desc)],
        },
        fallbacks=[CommandHandler("cancel", ap_cancel)],
        name="addproduct",
        persistent=False
    ))

    # Register conversation
    hs.append(ConversationHandler(
        entry_points=[CommandHandler("signup", register_cmd)],
        states={
            REG_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            REG_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone)],
            REG_ADDR:  [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_addr)],
        },
        fallbacks=[CommandHandler("cancel", ap_cancel)],
        name="register",
        persistent=False
    ))

    # Persian buttons (order of handlers مهم است تا منو درست کار کند)
    hs += [
        MessageHandler(filters.Regex(r"^منو\b") & ~filters.COMMAND, menu_),
        MessageHandler(filters.Regex(r"^کیف پول") & ~filters.COMMAND, wallet),
        MessageHandler(filters.Regex(r"^شارژ کارت") & ~filters.COMMAND, wallet_topup),
        MessageHandler(filters.Regex(r"^بازی") & ~filters.COMMAND, game),
        MessageHandler(filters.Regex(r"^راهنما") & ~filters.COMMAND, help_),
        MessageHandler(filters.Regex(r"^ارتباط") & ~filters.COMMAND, contact),
    ]
    return hs
