from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, ConversationHandler,
    CallbackQueryHandler, filters
)
from .base import ADMIN_IDS, CASHBACK_PERCENT, log
from . import db

# -------- Helpers ----------
MAIN_KB = InlineKeyboardMarkup.from_row([
    InlineKeyboardButton("🍬 منو", callback_data="menu"),
    InlineKeyboardButton("🧾 سفارش", callback_data="order"),
    InlineKeyboardButton("👛 کیف پول", callback_data="wallet"),
    InlineKeyboardButton("🎮 بازی", callback_data="game"),
    InlineKeyboardButton("☎️ ارتباط با ما", url="https://t.me/"),
    InlineKeyboardButton("ℹ️ راهنما", callback_data="help"),
])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or str(u.id))
    txt = (
        "سلام! 👋 به ربات بایو کِرِپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات با نام، قیمت و عکس\n"
        "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
        f"• کیف پول: مشاهده/شارژ، کش‌بک {CASHBACK_PERCENT}% بعد هر خرید\n"
        "• بازی: سرگرمی\n"
        "• ارتباط با ما: پیام به ادمین\n"
        "• راهنما: دستورها"
    )
    await (update.message or update.callback_query.message).reply_text(txt, reply_markup=MAIN_KB)

async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q: await q.answer()
    prods = db.list_products()
    if not prods:
        await (q.message if q else update.message).reply_text("فعلاً محصولی ثبت نشده.")
        if update.effective_user.id in ADMIN_IDS:
            await (q.message if q else update.message).reply_text("ادمین: با /addproduct محصول اضافه کن.")
        return
    for p in prods[:10]:
        caption = f"#{p['product_id']} — {p['name']}\nقیمت: {p['price']:,} تومان"
        kb = InlineKeyboardMarkup.from_row([
            InlineKeyboardButton("افزودن به سفارش 🧺", callback_data=f"order:{p['product_id']}"),
        ])
        if p["photo_file_id"]:
            await (q.message if q else update.message).reply_photo(photo=p["photo_file_id"], caption=caption, reply_markup=kb)
        else:
            await (q.message if q else update.message).reply_text(caption, reply_markup=kb)

async def on_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await (update.message or update.callback_query.message).reply_text(
        "/start شروع\n/menu منو\n/addproduct فقط ادمین\n"
        "/order سفارش با شناسه محصول\nمثال: /order 12 2  (دو عدد از محصول ۱۲)"
    )

# -------- سفارش سریع با دستور ----------
async def cmd_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("فرمت: /order <product_id> [quantity]")
        return
    try:
        pid = int(context.args[0]); qty = int(context.args[1]) if len(context.args) > 1 else 1
    except ValueError:
        await update.message.reply_text("شناسه/تعداد نامعتبر است.")
        return
    total = db.place_order(update.effective_user.id, pid, qty)
    if not total:
        await update.message.reply_text("محصول یافت نشد یا غیرفعال است.")
        return
    await update.message.reply_text(f"سفارش ثبت شد ✅\nمبلغ قابل پرداخت: {total:,} تومان")

# ================== جریان افزودن محصول (ادمین) ==================
AP_NAME, AP_PRICE, AP_PHOTO, AP_DESC = range(4)

def _admin_only(update: Update) -> bool:
    return (update.effective_user and update.effective_user.id in ADMIN_IDS)

async def addproduct_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _admin_only(update):
        await update.message.reply_text("فقط ادمین می‌تواند محصول اضافه کند.")
        return ConversationHandler.END
    await update.message.reply_text("نام محصول را بفرست:")
    return AP_NAME

async def addproduct_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (به تومان) را بفرست:")
    return AP_PRICE

async def addproduct_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.replace(",", "").strip())
    except ValueError:
        await update.message.reply_text("قیمت عددی نیست! دوباره بفرست:")
        return AP_PRICE
    context.user_data["p_price"] = price
    await update.message.reply_text("درصورت داشتن عکس، همین‌جا آپلود کن؛ یا /skip بزن:")
    return AP_PHOTO

async def addproduct_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = update.message.photo[-1].file_id if update.message.photo else None
    context.user_data["p_photo"] = file_id
    await update.message.reply_text("توضیح کوتاه محصول را بفرست (یا /skip):")
    return AP_DESC

async def addproduct_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text if update.message and update.message.text else None
    pid = db.add_product(
        context.user_data["p_name"],
        context.user_data["p_price"],
        context.user_data.get("p_photo"),
        desc,
    )
    await update.message.reply_text(f"محصول ذخیره شد ✅ (ID={pid})")
    context.user_data.clear()
    return ConversationHandler.END

async def addproduct_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # مسیر مشترک برای /skip در مراحل عکس/توضیح
    return await addproduct_desc(update, context)

async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q: return
    data = q.data
    if data == "menu":
        return await on_menu(update, context)
    if data == "help":
        return await on_help(update, context)
    if data.startswith("order:"):
        pid = int(data.split(":")[1])
        total = db.place_order(update.effective_user.id, pid, 1)
        await q.answer("افزوده شد!", show_alert=False)
        if total:
            await q.message.reply_text(f"سفارش ۱ عدد ثبت شد ✅ مبلغ: {total:,} تومان")
        return

def build_handlers():
    return [
        CommandHandler("start", start),
        CommandHandler("menu", on_menu),
        CommandHandler("help", on_help),
        CommandHandler("order", cmd_order),

        # Conversation: /addproduct
        ConversationHandler(
            entry_points=[CommandHandler("addproduct", addproduct_entry)],
            states={
                AP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_name)],
                AP_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_price)],
                AP_PHOTO:[MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, addproduct_photo),
                          CommandHandler("skip", addproduct_skip)],
                AP_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_desc),
                          CommandHandler("skip", addproduct_skip)],
            },
            fallbacks=[CommandHandler("cancel", lambda u,c: (u.message.reply_text("لغو شد."), ConversationHandler.END)[1])],
            name="addproduct_flow",
            persistent=False,
        ),

        CallbackQueryHandler(cb_router),
        # هر متنی → راهنما
        MessageHandler(filters.TEXT & ~filters.COMMAND, start),
    ]
