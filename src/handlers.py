from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, ConversationHandler, CallbackQueryHandler, filters
)
from .base import *
from . import db

# ===== کمک‌متن‌ها و کیبورد اصلی =====
WELCOME = (
    "سلام! 👋 به ربات بایو کرپ‌بار خوش‌اومدی.\n"
    "از دکمه‌های زیر استفاده کن:\n"
    f"• {BTN_MENU}: نمایش محصولات با دکمه‌های انتخاب\n"
    f"• {BTN_ORDER}: ثبت سفارش/فاکتور/پرداخت\n"
    f"• {BTN_WALLET}: مشاهده/شارژ، کش‌بک {DEFAULT_CASHBACK_PERCENT}%\n"
    f"• {BTN_GAME}: سرگرمی\n"
    f"• {BTN_CONTACT}: پیام به ادمین\n"
    f"• {BTN_HELP}: دستورها\n"
)
MAIN_KB = ReplyKeyboardMarkup(
    [[BTN_MENU, BTN_ORDER],[BTN_WALLET, BTN_GAME],[BTN_CONTACT, BTN_HELP]],
    resize_keyboard=True
)

# ===== شروع و ثبت کاربر =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, (u.full_name or u.username or ""))
    await update.message.reply_text(WELCOME, reply_markup=MAIN_KB)

# ====== 1) نمایش محصولات به صورت دکمه (صفحه‌بندی) ======
def _products_keyboard(page: int = 1, per_page: int = 8):
    total = db.count_products()
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    offset = (page - 1) * per_page
    prods = db.list_products(limit=per_page, offset=offset)

    rows = []
    for p in prods:
        title = f"{p['name']} — {int(p['price'])}₮"
        rows.append([InlineKeyboardButton(title, callback_data=f"prod:{p['id']}")])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("« قبلی", callback_data=f"pg:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("بعدی »", callback_data=f"pg:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("مشاهده فاکتور 🧾", callback_data="cart")])
    return InlineKeyboardMarkup(rows)

async def show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("🍬 منو:", reply_markup=_products_keyboard(1))

async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith("pg:"):
        page = int(data.split(":")[1])
        await q.edit_message_reply_markup(reply_markup=_products_keyboard(page))
    elif data.startswith("prod:"):
        pid = int(data.split(":")[1])
        p = db.get_product(pid)
        if not p:
            await q.answer("ناموجود", show_alert=True); return
        u = db.get_user(update.effective_user.id)
        oid = db.open_draft_order(u["id"])
        db.add_or_increment_item(oid, p["id"], float(p["price"]), inc=1)
        await q.answer(f"به سبد اضافه شد: {p['name']}", show_alert=False)
    elif data == "cart":
        await show_cart(update, ctx)
    else:
        pass

# ====== 2) سفارش: دیدن فاکتور + پرداخت ======
async def order_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "از منو محصول اضافه کن یا فاکتور را ببین/پرداخت کن.",
        reply_markup=_order_menu_kb()
    )

def _order_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن از منو", callback_data="go_menu")],
        [InlineKeyboardButton("🧾 مشاهده فاکتور", callback_data="cart")],
        [InlineKeyboardButton("💳 پرداخت با کیف پول", callback_data="pay_wallet")],
        [InlineKeyboardButton("🏧 پرداخت مستقیم (کارت‌به‌کارت)", callback_data="pay_direct")],
    ])

async def order_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "go_menu":
        await q.edit_message_text("🍬 منو:", reply_markup=_products_keyboard(1))
    elif q.data == "cart":
        await show_cart(update, ctx, edit=True)
    elif q.data == "pay_wallet":
        await pay_wallet(update, ctx)
    elif q.data == "pay_direct":
        await ask_direct_payment(update, ctx)

async def show_cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit=False):
    u = db.get_user(update.effective_user.id)
    oid = db.open_draft_order(u["id"])
    txt, total = db.summarize_order(oid)
    extra = "\n\nبرای پرداخت گزینه‌ای را از دکمه‌های زیر انتخاب کن."
    kb = _order_menu_kb()
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(txt+extra, reply_markup=kb)
    else:
        await update.effective_message.reply_text(txt+extra, reply_markup=kb, disable_web_page_preview=True)

# ===== پرداخت با کیف پول =====
async def pay_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    oid = db.open_draft_order(u["id"])
    ok, bal_after, total = db.can_pay_with_wallet(u["id"], oid)
    if not ok:
        bal = db.wallet(update.effective_user.id)
        await update.callback_query.edit_message_text(
            f"❗️ موجودی کافی نیست.\n"
            f"مبلغ فاکتور: {total} تومان\n"
            f"موجودی فعلی: {int(bal)} تومان\n\n"
            f"از «{BTN_WALLET}» برای شارژ استفاده کن یا پرداخت مستقیم را انتخاب کن.",
            reply_markup=_order_menu_kb()
        )
        return
    ok2, bal_after, total = db.pay_with_wallet(u["id"], oid)
    if ok2:
        await update.callback_query.edit_message_text(
            f"✅ پرداخت با کیف پول انجام شد.\nشماره سفارش: {oid}\n"
            f"موجودی جدید: {int(bal_after)} تومان\n"
            f"کش‌بک تا چند لحظه‌ی دیگر شارژ می‌شود.",
            reply_markup=None
        )
    else:
        await update.callback_query.edit_message_text("❌ خطا در پرداخت. دوباره تلاش کن.", reply_markup=_order_menu_kb())

# ===== پرداخت مستقیم (کارت‌به‌کارت) =====
async def ask_direct_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    oid = db.open_draft_order(u["id"])
    txt, total = db.summarize_order(oid)
    ctx.user_data["await_direct_for_order"] = oid
    await update.callback_query.edit_message_text(
        f"{txt}\n\n"
        f"برای پرداخت مستقیم، مبلغ <b>{total}</b> تومان را به کارت زیر واریز کن و "
        "رسید را به صورت «متن» اینجا بفرست:\n"
        f"شماره کارت: <code>{CARD_NUMBER}</code>\n"
        "نمونه متن: <code>پرداخت 230000 با کد 987654</code>",
        reply_markup=None
    )

async def direct_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if "await_direct_for_order" not in ctx.user_data:
        return  # این متن مربوط به شارژ کیف پول یا چیز دیگر است
    import re
    m = re.search(r"پرداخت\s+(\d+).*?(\d+)", update.message.text or "")
    if not m:
        await update.message.reply_text("فرمت رسید درست نیست. نمونه: «پرداخت 230000 با کد 987654»")
        return
    ref = m.group(2)
    u = db.get_user(update.effective_user.id)
    oid = ctx.user_data.pop("await_direct_for_order")
    db.mark_paid_direct(u["id"], oid, ref)
    await update.message.reply_text(
        f"✅ پرداخت ثبت شد. شماره سفارش: {oid}\nکد پیگیری: {ref}\n"
        "پس از ثبت، کش‌بک به کیف پولت افزوده می‌شود. 🙌",
        reply_markup=MAIN_KB
    )

# ===== کیف پول (مثل قبل + شارژ) =====
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
        await q.edit_message_text(
            f"برای شارژ کارت‌به‌کارت 👇\n"
            f"شماره کارت: <code>{CARD_NUMBER}</code>\n"
            "مبلغ دلخواه را واریز و متن زیر را بفرست:\n"
            "مثال: <code>شارژ 150000 با کدپیگیری 123456</code>"
        )

async def wallet_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # هم برای شارژ کیف پول و هم رسید مستقیم اگر state فعال بود
    if "await_direct_for_order" in ctx.user_data:
        await direct_text(update, ctx)
        return
    import re
    m = re.search(r"شارژ\s+(\d+).*?(\d+)", update.message.text or "")
    if not m:
        return
    amount = int(m.group(1)); ref = m.group(2)
    db.topup_wallet(update.effective_user.id, amount, ref)
    await update.message.reply_text(f"✅ شارژ شد: {amount} تومان (رسید: {ref})")

# ===== ثبت‌نام/پروفایل (مثل قبل) =====
PROFILE_NAME, PROFILE_PHONE, PROFILE_ADDRESS = range(3)

async def register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اسم‌ت را بفرست:")
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

# ===== ادمین: افزودن محصول (مثل قبل) =====
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
        await update.message.reply_text(f"❌ خطا در ذخیره: {e}", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ===== راهنما =====
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — شروع\n/register — ثبت نام\n/add — افزودن محصول (ادمین)\n"
        "از دکمه‌های پایین برای منو/سفارش/پرداخت استفاده کن."
    )

def build_handlers():
    return [
        CommandHandler("start", start),
        CommandHandler("help", help_cmd),

        # منو
        CommandHandler("menu", show_menu),
        MessageHandler(filters.Regex(f"^{BTN_MENU}$"), show_menu),
        CallbackQueryHandler(menu_cb, pattern="^(pg:|prod:|cart|noop)$"),

        # سفارش
        MessageHandler(filters.Regex(f"^{BTN_ORDER}$"), order_entry),
        CallbackQueryHandler(order_cb, pattern="^(go_menu|cart|pay_wallet|pay_direct)$"),

        # کیف پول + شارژ
        MessageHandler(filters.Regex(f"^{BTN_WALLET}$"), wallet_entry),
        CallbackQueryHandler(wallet_cb, pattern="^topup$"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_text),

        # ثبت نام
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

        # ادمین: افزودن محصول
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
