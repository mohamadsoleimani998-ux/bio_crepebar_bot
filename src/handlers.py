from __future__ import annotations
from typing import List, Tuple
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
from telegram.ext import (
    CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)
from .base import log, ADMIN_IDS, CASHBACK_PERCENT, CARD_NUMBER
from . import db

# ===== Keyboards (FA) =====
MAIN_KB = ReplyKeyboardMarkup(
    [
        ["🍬 منو", "🧾 سفارش"],
        ["👛 کیف پول", "🎮 بازی"],
        ["☎️ ارتباط با ما", "ℹ️ راهنما"],
    ],
    resize_keyboard=True
)

WALLET_KB = ReplyKeyboardMarkup(
    [
        ["📥 شارژ کیف پول", "💳 موجودی"],
        ["↩️ بازگشت"]
    ],
    resize_keyboard=True
)

# ===== Helpers =====
def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or str(u.id))
    text = (
        "سلام! 👋 به ربات بایو کرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات با نام، قیمت و عکس\n"
        "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
        f"• کیف پول: مشاهده/شارژ، کش‌بک {CASHBACK_PERCENT}% بعد هر خرید\n"
        "• بازی: سرگرمی\n"
        "• ارتباط با ما: پیام به ادمین\n"
        "• راهنما: دستورات"
    )
    await update.message.reply_text(text, reply_markup=MAIN_KB)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start – شروع ربات\n"
        "/addproduct – افزودن محصول (ادمین)\n"
        "/register – ثبت نام/ویرایش مشخصات\n"
        "/balance – موجودی کیف پول\n", reply_markup=MAIN_KB
    )

# ===== Register =====
REG_NAME, REG_PHONE, REG_ADDR = range(3)

async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("نام کامل خود را بفرست:", reply_markup=ReplyKeyboardMarkup([["↩️ انصراف"]], resize_keyboard=True))
    return REG_NAME

async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("📱 شماره تماس را بفرست (مثلاً 09xxxxxxxxx):")
    return REG_PHONE

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("📍 آدرس را بفرست:")
    return REG_ADDR

async def register_addr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("name")
    phone = context.user_data.get("phone")
    address = update.message.text.strip()
    db.update_user_profile(update.effective_user.id, name, phone, address)
    await update.message.reply_text("✅ ثبت نام/ویرایش انجام شد.", reply_markup=MAIN_KB)
    return ConversationHandler.END

async def register_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ===== Menu / Products =====
async def menu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products()
    if not prods:
        await update.message.reply_text("فعلاً محصولی ثبت نشده.\nادمین: با /addproduct محصول اضافه کن.", reply_markup=MAIN_KB)
        return
    for p in prods[:30]:
        caption = f"#{p['product_id']} • {p['name']}\n💰 {p['price']:,} تومان"
        if p.get("description"):
            caption += f"\n📝 {p['description']}"
        if p.get("photo_file_id"):
            await update.message.reply_photo(p["photo_file_id"], caption=caption)
        else:
            await update.message.reply_text(caption)

# ===== Wallet =====
async def wallet_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("گزینهٔ کیف پول:", reply_markup=WALLET_KB)

async def wallet_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = db.wallet_balance(update.effective_user.id)
    await update.message.reply_text(f"💳 موجودی شما: {bal:,} تومان", reply_markup=WALLET_KB)

async def wallet_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        f"برای شارژ کیف پول، مبلغ را کارت‌به‌کارت کنید:\n"
        f"💳 شماره کارت: <code>{CARD_NUMBER}</code>\n"
        "سپس رسید یا 4 رقم آخر کارت و مبلغ را برای ادمین ارسال کنید.\n"
        "ادمین با دستور زیر شارژ می‌کند:\n"
        "<code>/confirm USER_ID AMOUNT</code>\n"
        "مثال: <code>/confirm 1606170079 500000</code>"
    )
    await update.message.reply_text(msg, reply_markup=WALLET_KB)

# ادمین: تایید شارژ
async def admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _is_admin(uid):
        return
    try:
        _, user_id_str, amount_str = update.message.text.strip().split(maxsplit=2)
        user_id = int(user_id_str)
        amount = int(amount_str)
    except Exception:
        await update.message.reply_text("فرمت صحیح: /confirm <USER_ID> <AMOUNT>")
        return
    db.wallet_add(user_id, amount, kind="topup", meta={"by": uid})
    await update.message.reply_text(f"✅ برای {user_id} مبلغ {amount:,} تومان شارژ شد.")

# ===== Add Product (admin) =====
P_NAME, P_PRICE, P_PHOTO, P_DESC = range(4)

async def addp_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("این دستور مخصوص ادمین است.")
        return ConversationHandler.END
    await update.message.reply_text("نام محصول را بفرست:")
    return P_NAME

async def addp_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان) را بفرست:")
    return P_PRICE

async def addp_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.replace(",", "").strip())
    except Exception:
        await update.message.reply_text("قیمت نامعتبر. یک عدد بفرست.")
        return P_PRICE
    context.user_data["p_price"] = price
    await update.message.reply_text("عکس محصول را بفرست (یا بنویس «بدون عکس»):")
    return P_PHOTO

async def addp_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        text = (update.message.text or "").strip()
        file_id = None if "بدون" in text else None
    context.user_data["p_photo"] = file_id
    await update.message.reply_text("توضیحات کوتاه (اختیاری) را بفرست. اگر نمی‌خواهی بنویس «بدون توضیحات».")
    return P_DESC

async def addp_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    desc = None if "بدون" in text else text
    p = db.add_product(
        context.user_data.get("p_name"),
        context.user_data.get("p_price"),
        context.user_data.get("p_photo"),
        desc
    )
    await update.message.reply_text(f"✅ محصول ثبت شد: #{p['product_id']} – {p['name']} ({p['price']:,} تومان)", reply_markup=MAIN_KB)
    return ConversationHandler.END

async def addp_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ===== Fallbacks / small handlers =====
async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("☎️ پیام بده: @your_admin_username", reply_markup=MAIN_KB)

async def game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎮 به‌زودی بازی‌های کوچک اضافه می‌شود.", reply_markup=MAIN_KB)

def build_handlers() -> List:
    reg = ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.Regex("^↩️ انصراف$"), register_name)],
            REG_PHONE:[MessageHandler(filters.TEXT & ~filters.Regex("^↩️ انصراف$"), register_phone)],
            REG_ADDR: [MessageHandler(filters.TEXT & ~filters.Regex("^↩️ انصراف$"), register_addr)],
        },
        fallbacks=[MessageHandler(filters.Regex("^↩️ انصراف$"), register_cancel)],
        name="register",
        persistent=False
    )

    addp = ConversationHandler(
        entry_points=[CommandHandler("addproduct", addp_start), MessageHandler(filters.Regex("^/addproduct$"), addp_start)],
        states={
            P_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, addp_name)],
            P_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addp_price)],
            P_PHOTO: [MessageHandler((filters.PHOTO | filters.Regex("بدون")), addp_photo)],
            P_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, addp_desc)],
        },
        fallbacks=[CommandHandler("cancel", addp_cancel)],
        name="addproduct",
        persistent=False
    )

    return [
        CommandHandler("start", start),
        CommandHandler("help", help_cmd),
        CommandHandler("register", register_start),
        CommandHandler("balance", wallet_balance_cmd),
        CommandHandler("confirm", admin_confirm),  # admin only
        addp, reg,
        # Persian buttons
        MessageHandler(filters.Regex("^🍬 منو$"), menu_show),
        MessageHandler(filters.Regex("^🧾 سفارش$"), help_cmd),  # نمونه ساده
        MessageHandler(filters.Regex("^👛 کیف پول$"), wallet_entry),
        MessageHandler(filters.Regex("^📥 شارژ کیف پول$"), wallet_topup),
        MessageHandler(filters.Regex("^💳 موجودی$"), wallet_balance_cmd),
        MessageHandler(filters.Regex("^↩️ بازگشت$"), start),
        MessageHandler(filters.Regex("^☎️ ارتباط با ما$"), contact),
        MessageHandler(filters.Regex("^🎮 بازی$"), game),
        MessageHandler(filters.Regex("^ℹ️ راهنما$"), help_cmd),
        # آخرین راه‌حل: هر متن ناشناخته -> منو
        MessageHandler(filters.TEXT & ~filters.COMMAND, start),
    ]
