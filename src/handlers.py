from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, ConversationHandler, CallbackQueryHandler, filters
)
from .base import *
from . import db

# ====== کمک‌متن‌ها ======
WELCOME = (
    "سلام! 👋 به ربات بایو کرپ‌بار خوش‌اومدی.\n"
    "از دکمه‌های زیر استفاده کن:\n"
    f"• {BTN_MENU}: نمایش محصولات با نام/قیمت/عکس\n"
    f"• {BTN_ORDER}: ثبت سفارش ساده\n"
    f"• {BTN_WALLET}: مشاهده/شارژ، کش‌بک {DEFAULT_CASHBACK_PERCENT}% بعد هر خرید\n"
    f"• {BTN_GAME}: سرگرمی\n"
    f"• {BTN_CONTACT}: پیام به ادمین\n"
    f"• {BTN_HELP}: دستورها\n"
)

MAIN_KB = ReplyKeyboardMarkup(
    [[BTN_MENU, BTN_ORDER],[BTN_WALLET, BTN_GAME],[BTN_CONTACT, BTN_HELP]],
    resize_keyboard=True
)

# ===== ثبت‌نام سریع در /start =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, (u.full_name or u.username or ""))
    await update.message.reply_text(WELCOME, reply_markup=MAIN_KB)

# ===== منو =====
async def show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products()
    if not prods:
        await update.effective_message.reply_text("هنوز محصولی ثبت نشده.")
        return
    # عکس‌دار جداگانه، بقیه با متن
    medias = []
    for p in prods[:10]:
        cap = f"🍰 <b>{p['name']}</b>\n💵 {int(p['price'])} تومان\n" + (p["description"] or "")
        if p["photo_file_id"]:
            medias.append(("photo", p["photo_file_id"], cap))
    if medias:
        # ارسال اولین به صورت عکس، بقیه آلبوم
        first = medias[0]
        await update.effective_message.reply_photo(first[1], caption=first[2], reply_markup=MAIN_KB)
        for kind, fid, cap in medias[1:]:
            await update.effective_chat.send_photo(fid, caption=cap)
    # لیست متنی هم بده
    lines = [f"{i+1}. {p['name']} — {int(p['price'])} تومان" for i,p in enumerate(prods)]
    await update.effective_message.reply_text("📋 منو:\n" + "\n".join(lines))

# ===== کیف پول =====
async def wallet_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bal = db.wallet(update.effective_user.id)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(BTN_WALLET_TOPUP, callback_data="topup")]])
    await update.effective_message.reply_text(
        f"💳 موجودی شما: <b>{int(bal)}</b> تومان\nکش‌بک فعال: {DEFAULT_CASHBACK_PERCENT}%",
        reply_markup=kb
    )

async def wallet_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "topup":
        card = CARD_NUMBER
        await q.edit_message_text(
            f"برای شارژ کارت‌به‌کارت 👇\n"
            f"شماره کارت: <code>{card}</code>\n"
            "مبلغ دلخواه رو واریز کن و رسید را به صورت «متن» به شکل زیر ارسال کن:\n"
            "مثال: <code>شارژ 150000 با کدپیگیری 123456</code>"
        )

async def wallet_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text or ""
    if txt.startswith("شارژ"):
        # الگوی ساده
        import re
        m = re.search(r"شارژ\s+(\d+).*?(\d+)", txt)
        if not m:
            await update.message.reply_text("فرمت نامعتبر. نمونه: «شارژ 150000 با کدپیگیری 123456»")
            return
        amount = int(m.group(1)); ref = m.group(2)
        db.topup_wallet(update.effective_user.id, amount, ref)
        await update.message.reply_text(f"✅ شارژ شد: {amount} تومان (رسید: {ref})")

# ===== سفارش ساده (نام محصول × تعداد) =====
async def order_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("نام محصول و تعداد را بنویس (مثال: «اسپرسو ×2»).")

async def order_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").replace("x","×").replace("X","×")
    if "×" not in txt:
        await update.message.reply_text("الگو نامعتبر. مثال: «لاته ×1».")
        return
    name, qty = [x.strip() for x in txt.split("×",1)]
    qty = int(qty or "1")
    # پیدا کردن محصول
    prods = db.list_products()
    prod = next((p for p in prods if p["name"].strip()==name), None)
    if not prod:
        await update.message.reply_text("محصول پیدا نشد.")
        return
    u = db.get_user(update.effective_user.id)
    order_id = db.open_draft_order(u["id"])
    db.add_item(order_id, prod["id"], qty, float(prod["price"]))
    db.submit_order(order_id)
    await update.message.reply_text(f"✅ سفارش ثبت شد: {name} ×{qty}")

# ===== ثبت‌نام/پروفایل =====
PROFILE_NAME, PROFILE_PHONE, PROFILE_ADDRESS = range(3)

async def register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اسم‌ت رو بفرست:")
    return PROFILE_NAME

async def profile_name(update, ctx):
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("شماره موبایل:")
    return PROFILE_PHONE

async def profile_phone(update, ctx):
    ctx.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("آدرس:")
    return PROFILE_ADDRESS

async def profile_address(update, ctx):
    ctx.user_data["address"] = update.message.text.strip()
    db.set_user_profile(update.effective_user.id, **ctx.user_data)
    await update.message.reply_text("✅ ثبت شد.", reply_markup=MAIN_KB)
    return ConversationHandler.END

async def cancel_conv(update, ctx):
    await update.message.reply_text("لغو شد.", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ===== ادمین: افزودن محصول =====
ADD_NAME, ADD_PRICE, ADD_PHOTO, ADD_DESC = range(10,14)

def _is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in ADMIN_IDS

async def admin_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("اجازه نداری.")
        return ConversationHandler.END
    await update.message.reply_text("نام محصول را بفرست:")
    return ADD_NAME

async def add_name(update, ctx):
    ctx.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان):")
    return ADD_PRICE

async def add_price(update, ctx):
    ctx.user_data["p_price"] = float(update.message.text.strip())
    await update.message.reply_text("عکس محصول را بفرست (یا بنویس «بدون عکس»):")
    return ADD_PHOTO

async def add_photo(update, ctx):
    if update.message.photo:
        fid = update.message.photo[-1].file_id
    else:
        fid = None
    ctx.user_data["p_photo"] = fid
    await update.message.reply_text("توضیحات کوتاه (اختیاری). اگر نمی‌خوای بنویس «بدون توضیحات».")
    return ADD_DESC

async def add_desc(update, ctx):
    desc = update.message.text
    if desc in ("بدون توضیحات","بدون توضیح"):
        desc = None
    try:
        db.add_product(ctx.user_data["p_name"], ctx.user_data["p_price"], ctx.user_data["p_photo"], desc)
        await update.message.reply_text("✅ ذخیره شد.", reply_markup=MAIN_KB)
    except Exception as e:
        log.exception("add_product failed")
        await update.message.reply_text(f"❌ خطا در ذخیره: {e}", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ===== راهنما =====
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — شروع\n/register — ثبت نام\n/add — افزودن محصول (ادمین)\n"
        "دکمه‌های پایین همۀ امکانات را دارند."
    )

def build_handlers():
    return [
        CommandHandler("start", start),
        CommandHandler("help", help_cmd),
        CommandHandler("menu", show_menu),

        MessageHandler(filters.Regex(f"^{BTN_MENU}$"), show_menu),

        MessageHandler(filters.Regex(f"^{BTN_WALLET}$"), wallet_entry),
        CallbackQueryHandler(wallet_cb, pattern="^topup$"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_text),

        MessageHandler(filters.Regex(f"^{BTN_ORDER}$"), order_entry),
        MessageHandler(filters.Regex("×") & ~filters.COMMAND, order_text),

        ConversationHandler(
            entry_points=[CommandHandler("register", register)],
            states={
                PROFILE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_name)],
                PROFILE_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND, profile_phone)],
                PROFILE_ADDRESS:[MessageHandler(filters.TEXT & ~filters.COMMAND, profile_address)],
            },
            fallbacks=[CommandHandler("cancel", cancel_conv)],
            name="register",
            persistent=False
        ),

        ConversationHandler(
            entry_points=[CommandHandler("add", admin_add)],
            states={
                ADD_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
                ADD_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
                ADD_PHOTO:[MessageHandler((filters.PHOTO | filters.Regex("^بدون عکس$")) & ~filters.COMMAND, add_photo)],
                ADD_DESC:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_desc)],
            },
            fallbacks=[CommandHandler("cancel", cancel_conv)],
            name="add_product",
            persistent=False
        ),
    ]
