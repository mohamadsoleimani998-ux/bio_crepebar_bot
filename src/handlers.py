from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, ConversationHandler, filters
)
from .base import ADMIN_IDS, CARD_NUMBER, CASHBACK_PERCENT, log
from . import db

# ── کیبوردها ─────────────────────────────────────────────────────────────────
MAIN_KB = ReplyKeyboardMarkup(
    [
        ["🍬 منو", "🧾 سفارش"],
        ["👜 کیف پول", "🎮 بازی"],
        ["☎️ ارتباط با ما", "ℹ️ راهنما"],
    ], resize_keyboard=True
)

def admin_only(update: Update) -> bool:
    return update.effective_user and (update.effective_user.id in ADMIN_IDS)

# ────────────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    is_admin = admin_only(update)
    db.upsert_user(u.id, u.full_name or u.username or str(u.id), is_admin=is_admin)

    await update.message.reply_text(
        "سلام! 👋 به ربات بایو کرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات با نام، قیمت و عکس\n"
        "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
        "• کیف پول: مشاهده/شارژ/کش‌بک %{} بعد هر خرید\n"
        "• بازی: سرگرمی\n"
        "• ارتباط با ما: پیام به ادمین\n"
        "• راهنما: دستورها".format(CASHBACK_PERCENT),
        reply_markup=MAIN_KB
    )

# ── راهنما/ارتباط ───────────────────────────────────────────────────────────
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "دستورها:\n"
        "/start شروع\n"
        "/register ثبت‌نام\n"
        "/addproduct افزودن محصول (ادمین)\n"
        "/menu منو\n"
        "/wallet کیف پول\n"
    )

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پیام خود را بنویسید؛ برای پاسخ، ادمین با شما تماس می‌گیرد.")

# ── ثبت‌نام کاربر ───────────────────────────────────────────────────────────
REG_NAME, REG_PHONE, REG_ADDR = range(3)

async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("نام و نام‌خانوادگی را بفرست:")
    return REG_NAME

async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("شماره موبایل را بفرست (مثل 09xxxxxxxxx):")
    return REG_PHONE

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("آدرس کامل را بفرست:")
    return REG_ADDR

async def register_addr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text.strip()
    u = update.effective_user
    db.update_profile(u.id, context.user_data["name"], context.user_data["phone"], context.user_data["address"])
    await update.message.reply_text("ثبت‌نام با موفقیت انجام شد ✅", reply_markup=MAIN_KB)
    return ConversationHandler.END

async def register_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ثبت‌نام لغو شد.", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ── منو / محصولات ──────────────────────────────────────────────────────────
async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products()
    if not prods:
        msg = "فعلاً محصولی ثبت نشده."
        if admin_only(update):
            msg += "\nادمین: با /addproduct محصول اضافه کن."
        await update.message.reply_text(msg)
        return
    for p in prods:
        cap = f"• {p['name']}\nقیمت: {p['price']} تومان"
        if p.get("description"):
            cap += f"\nتوضیح: {p['description']}"
        if p.get("photo_file_id"):
            await update.message.reply_photo(p["photo_file_id"], caption=cap)
        else:
            await update.message.reply_text(cap)

# ── افزودن محصول (ادمین) ───────────────────────────────────────────────────
ADD_NAME, ADD_PRICE, ADD_PHOTO, ADD_DESC = range(4)

async def addproduct_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        await update.message.reply_text("این بخش مخصوص ادمین است.")
        return ConversationHandler.END
    await update.message.reply_text("نام محصول را بفرست:")
    return ADD_NAME

async def addproduct_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = (update.message.text or "").strip()
    await update.message.reply_text("قیمت (تومان) را بفرست:")
    return ADD_PRICE

async def addproduct_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").replace(",", "").strip()
    if not t.isdigit():
        await update.message.reply_text("قیمت صحیح نیست. یک عدد بفرست.")
        return ADD_PRICE
    context.user_data["p_price"] = int(t)
    await update.message.reply_text("عکس محصول را بفرست (یا بنویس «بدون عکس»):")
    return ADD_PHOTO

async def addproduct_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        fid = update.message.photo[-1].file_id
        context.user_data["p_photo"] = fid
    else:
        if (update.message.text or "").strip() != "بدون عکس":
            await update.message.reply_text("لطفاً عکس بفرست یا بنویس «بدون عکس».")
            return ADD_PHOTO
        context.user_data["p_photo"] = None
    await update.message.reply_text("توضیح کوتاه محصول (اختیاری) را بفرست؛ یا بنویس «بدون توضیح».")
    return ADD_DESC

async def addproduct_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = (update.message.text or "").strip()
    if desc == "بدون توضیح":
        desc = ""
    p = db.add_product(context.user_data["p_name"], context.user_data["p_price"],
                       context.user_data.get("p_photo"), desc)
    await update.message.reply_text(f"ثبت شد ✅\n#{p['id']} - {p['name']} ({p['price']} تومان)")
    return ConversationHandler.END

async def addproduct_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("افزودن محصول لغو شد.")
    return ConversationHandler.END

# ── کیف پول ─────────────────────────────────────────────────────────────────
WALLET_MENU, WALLET_CHARGE = range(2)

async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = db.wallet_balance(update.effective_user.id)
    kb = ReplyKeyboardMarkup(
        [["➕ شارژ کیف پول", "📜 گردش‌ها"], ["بازگشت ⬅️"]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        f"موجودی کیف پول: {bal} تومان\n"
        f"کش‌بک فعال: {CASHBACK_PERCENT}%",
        reply_markup=kb
    )
    return WALLET_MENU

async def wallet_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt == "➕ شارژ کیف پول":
        await update.message.reply_text(
            "مبلغ شارژ (تومان) را بفرست.\n"
            f"پرداخت کارت‌به‌کارت به کارت: {CARD_NUMBER}\n"
            "سپس «پرداخت شد» را ارسال کن."
        )
        return WALLET_CHARGE
    elif txt == "📜 گردش‌ها":
        await update.message.reply_text("جهت سادگی نسخه فعلی، گزارش‌گیری خلاصه است. (به‌زودی کامل‌تر)")
        return WALLET_MENU
    else:
        await update.message.reply_text("بازگشت به منو.", reply_markup=MAIN_KB)
        return ConversationHandler.END

async def wallet_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = (update.message.text or "").replace(",", "").strip()
    if t == "پرداخت شد":
        amt = context.user_data.get("charge_amount")
        if not amt:
            await update.message.reply_text("ابتدا مبلغ را وارد کن.")
            return WALLET_CHARGE
        # در نسخه فعلی، تأیید خودکار (نسخه بعدی: تأیید ادمین)
        db.wallet_change(update.effective_user.id, amt, "charge", "manual card to card")
        await update.message.reply_text(f"شارژ شد ✅ (+{amt})", reply_markup=MAIN_KB)
        return ConversationHandler.END
    if not t.isdigit():
        await update.message.reply_text("لطفاً یک عدد بفرست یا پیام «پرداخت شد».")
        return WALLET_CHARGE
    context.user_data["charge_amount"] = int(t)
    await update.message.reply_text(
        f"عدد {t} ثبت شد.\n"
        f"حالا کارت‌به‌کارت به {CARD_NUMBER} انجام بده و «پرداخت شد» رو بفرست.")
    return WALLET_CHARGE

# ── روتر متن‌های عمومی ─────────────────────────────────────────────────────
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt in ("منو", "🍬 منو"):
        return await menu_cmd(update, context)
    if txt in ("کیف پول", "👜 کیف پول"):
        return await wallet_cmd(update, context)
    if txt in ("ارتباط با ما", "☎️ ارتباط با ما"):
        return await contact(update, context)
    if txt in ("راهنما", "ℹ️ راهنما"):
        return await help_cmd(update, context)
    if txt in ("سفارش", "🧾 سفارش"):
        return await update.message.reply_text("ماژول سفارش در نسخه بعدی تکمیل می‌شود. فعلاً از منو خرید کنید 😊")
    # fallback
    await update.message.reply_text("از دکمه‌ها استفاده کن.", reply_markup=MAIN_KB)

# ── رجیستر همه هندلرها ─────────────────────────────────────────────────────
def build_handlers():
    hs = []

    hs.append(CommandHandler("start", start))
    hs.append(CommandHandler("help", help_cmd))
    hs.append(CommandHandler("menu", menu_cmd))
    hs.append(CommandHandler("wallet", wallet_cmd))
    hs.append(CommandHandler("register", register_start))
    hs.append(CommandHandler("addproduct", addproduct_start))

    # ثبت‌نام
    hs.append(ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            REG_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
            REG_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)],
            REG_ADDR:  [MessageHandler(filters.TEXT & ~filters.COMMAND, register_addr)],
        },
        fallbacks=[MessageHandler(filters.Regex("^لغو$"), register_cancel)],
        allow_reentry=True,
    ))

    # افزودن محصول
    hs.append(ConversationHandler(
        entry_points=[CommandHandler("addproduct", addproduct_start)],
        states={
            ADD_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_price)],
            ADD_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, addproduct_photo)],
            ADD_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_desc)],
        },
        fallbacks=[MessageHandler(filters.Regex("^لغو$"), addproduct_cancel)],
        allow_reentry=True,
    ))

    # کیف پول
    hs.append(ConversationHandler(
        entry_points=[CommandHandler("wallet", wallet_cmd)],
        states={
            WALLET_MENU:  [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_menu_router)],
            WALLET_CHARGE:[MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_charge)],
        },
        fallbacks=[MessageHandler(filters.Regex("^لغو$"), text_router)],
        allow_reentry=True,
    ))

    # روتر عمومی متن‌ها
    hs.append(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    return hs
