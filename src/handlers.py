from __future__ import annotations
from decimal import Decimal
import re
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, ConversationHandler, filters
)
from .base import ADMIN_IDS, DEFAULT_CASHBACK, log
from . import db

# ---------- Keyboards (FA)
MAIN_KB = ReplyKeyboardMarkup(
    [
        ["منو 🍬", "سفارش 🧾"],
        ["کیف پول 👛", "بازی 🎮"],
        ["ارتباط با ما ☎️", "راهنما ℹ️"],
        ["ثبت نام 📝"],
    ],
    resize_keyboard=True,
)

def money(n) -> str:
    try:
        n = int(Decimal(n))
    except Exception:
        pass
    return f"{n:,} تومان".replace(",", "٬")

# ---------- /start & welcome
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    row = db.upsert_user(u.id, u.full_name)
    text = (
        "سلام! 👋 به ربات بایو کِرِپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات با نام، قیمت و عکس\n"
        "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
        f"• کیف پول: مشاهده/شارژ، کش‌بک {db.get_cashback_percent() or DEFAULT_CASHBACK}% بعد هر خرید\n"
        "• ثبت نام: تکمیل نام، شماره و آدرس\n"
        "• بازی: سرگرمی\n"
        "• ارتباط با ما: پیام به ادمین\n"
        "• راهنما: دستورها"
    )
    await update.effective_message.reply_text(text, reply_markup=MAIN_KB)

# ---------- Menu (list products)
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products(limit=10)
    if not prods:
        await update.effective_message.reply_text("فعلاً محصولی ثبت نشده.\nادمین: با /addproduct محصول اضافه کن.")
        return
    for p in prods:
        caption = f"• {p['name']}\nقیمت: {money(p['price'])}"
        if p.get("description"):
            caption += f"\n{p['description']}"
        if p.get("photo_file_id"):
            await update.effective_message.reply_photo(p["photo_file_id"], caption=caption)
        else:
            await update.effective_message.reply_text(caption)

# ---------- Wallet
async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user_by_tg(update.effective_user.id)
    percent = db.get_cashback_percent() or DEFAULT_CASHBACK
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("شارژ کارت‌به‌کارت")], ["بازگشت ⬅️"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.effective_message.reply_text(
        f"موجودی شما: {money(u['balance'])}\nکش‌بک فعال: {percent}%",
        reply_markup=kb,
    )

async def wallet_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.effective_message.text or "").strip()
    if txt == "شارژ کارت‌به‌کارت":
        await update.effective_message.reply_text(
            "مبلغ شارژ را به کارت زیر واریز کن و رسید را برای ادمین بفرست:\n"
            "شماره کارت: 5029-0810-8098-4145\n\n"
            "پس از تأیید ادمین، موجودی‌ات افزایش می‌یابد."
        )
    elif txt == "بازگشت ⬅️":
        await update.effective_message.reply_text("بازگشت به منو.", reply_markup=MAIN_KB)

# ---------- Simple order (demo): "نام ×تعداد"
async def order_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "نام محصول و تعداد را بنویس (مثال: «اسپرسو ×2».)\n(دموی ساده)"
    )

def _parse_name_qty(s: str):
    s = s.replace("×", "x").replace("X", "x").strip()
    if "x" in s:
        name, qty = s.split("x", 1)
        try:
            q = int(qty.strip())
        except Exception:
            q = 1
        return name.strip(), max(q, 1)
    return s.strip(), 1

async def order_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, qty = _parse_name_qty(update.effective_message.text or "")
    prod = db.find_product_by_name(name)
    if not prod:
        await update.effective_message.reply_text("محصول پیدا نشد. اول با «منو 🍬» لیست را ببین.")
        return
    u = db.upsert_user(update.effective_user.id, update.effective_user.full_name)
    order_id = db.create_order(u["user_id"])
    db.add_item(order_id, prod["product_id"], qty, float(prod["price"]))
    db.submit_order(order_id)

    msg = (
        f"سفارش #{order_id}\n"
        f"{prod['name']} × {qty}\n"
        f"مبلغ کل: {money(Decimal(prod['price']) * qty)}\n\n"
        "برای پرداخت کارت‌به‌کارت:\n"
        "5029-0810-8098-4145\n"
        "پس از پرداخت، ادمین با دستور /paid <order_id> تأیید می‌کند."
    )
    await update.effective_message.reply_text(msg)

# ---------- Admin helpers
def _is_admin(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    return uid in ADMIN_IDS

# ----- Add Product (admin)
AP_NAME, AP_PRICE, AP_PHOTO, AP_DESC = range(4)

async def addproduct_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return await update.effective_message.reply_text("دسترسی نداری.")
    context.user_data.clear()
    await update.effective_message.reply_text("نام محصول را بفرست:")
    return AP_NAME

async def ap_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = (update.effective_message.text or "").strip()
    await update.effective_message.reply_text("قیمت (تومان) را بفرست:")
    return AP_PRICE

async def ap_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.effective_message.text or "").replace(",", "").strip()
    try:
        price = float(txt)
    except Exception:
        await update.effective_message.reply_text("قیمت نامعتبر است. یک عدد بفرست.")
        return AP_PRICE
    context.user_data["price"] = price
    await update.effective_message.reply_text("عکس محصول را بفرست (یا بنویس «بدون عکس»):")
    return AP_PHOTO

async def ap_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data["photo_id"] = file_id
    else:
        context.user_data["photo_id"] = None
    await update.effective_message.reply_text("توضیحات کوتاه (اختیاری) را بفرست. اگر نمی‌خواهی بنویس «بدون توضیحات».")
    return AP_DESC

async def ap_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = (update.effective_message.text or "").strip()
    if desc in ("بدون توضیحات", "بدون توضیح", "بدون"):
        desc = None
    pid = db.add_product(
        context.user_data["name"],
        context.user_data["price"],
        context.user_data.get("photo_id"),
        desc,
    )
    await update.effective_message.reply_text(f"محصول با شناسه #{pid} ذخیره شد ✅", reply_markup=MAIN_KB)
    return ConversationHandler.END

async def ap_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("لغو شد.", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ----- Admin commands
async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return await update.effective_message.reply_text("دسترسی نداری.")
    if not context.args:
        return await update.effective_message.reply_text("مثال: /paid 123")
    try:
        order_id = int(context.args[0])
    except Exception:
        return await update.effective_message.reply_text("شناسه سفارش نامعتبر است.")
    row = db.mark_paid(order_id)
    if not row:
        return await update.effective_message.reply_text("سفارش پیدا نشد.")
    await update.effective_message.reply_text(
        f"سفارش #{order_id} paid شد. مبلغ: {money(row[1])} | کش‌بک: {money(row[2])}"
    )

async def topup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return await update.effective_message.reply_text("دسترسی نداری.")
    if len(context.args) < 2:
        return await update.effective_message.reply_text("مثال: /topup 1606170079 50000")
    tg_id = int(context.args[0])
    amount = float(context.args[1])
    u = db.get_user_by_tg(tg_id)
    if not u:
        return await update.effective_message.reply_text("کاربر یافت نشد.")
    db.topup(u["user_id"], amount, {"method": "card2card", "card": "5029081080984145"})
    bal = db.get_balance(u["user_id"])
    await update.effective_message.reply_text(f"شارژ انجام شد. موجودی جدید: {money(bal)}")

async def setcashback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return await update.effective_message.reply_text("دسترسی نداری.")
    if not context.args:
        return await update.effective_message.reply_text("مثال: /setcashback 3")
    p = int(context.args[0])
    db.set_cashback_percent(p)
    await update.effective_message.reply_text(f"درصد کش‌بک روی {p}% تنظیم شد.")

# ----- Help
async def help_cmd(update, context):
    await update.effective_message.reply_text(
        "دستورها:\n"
        "/start – شروع\n"
        "/register – ثبت‌نام (نام/شماره/آدرس)\n"
        "/addproduct – افزودن محصول (ادمین)\n"
        "/paid <order_id> – تأیید پرداخت (ادمین)\n"
        "/topup <tg_id> <amount> – شارژ کیف پول (ادمین)\n"
        "/setcashback <p> – تعیین درصد کش‌بک (ادمین)\n"
    )

# ===================== Registration Conversation =====================
REG_NAME, REG_PHONE, REG_ADDR = range(3)
PHONE_RE = re.compile(r"^(?:\+?98|0)?9\d{9}$")  # موبایل ایران

async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ایجاد/به‌روزرسانی اولیه نام تلگرام
    db.upsert_user(update.effective_user.id, update.effective_user.full_name)
    await update.effective_message.reply_text(
        "ثبت‌نام شروع شد. نامت را بفرست (یا همان نام روی پروفایل را تأیید کن):"
    )
    return REG_NAME

async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = (update.effective_message.text or "").strip()
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("ارسال مخاطب من", request_contact=True)], ["لغو"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.effective_message.reply_text(
        "شماره موبایل را بفرست (با 09 یا +989 شروع شود) یا دکمه «ارسال مخاطب من» را بزن.",
        reply_markup=kb,
    )
    return REG_PHONE

async def reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = None
    if update.message.contact and update.message.contact.phone_number:
        phone = update.message.contact.phone_number
    else:
        phone = (update.effective_message.text or "").replace(" ", "")
    # نرمال‌سازی ساده
    phone = phone.replace("+98", "0") if phone.startswith("+98") else phone
    if not PHONE_RE.match(phone):
        await update.effective_message.reply_text("شماره نامعتبر است. دوباره بفرست یا «لغو».")
        return REG_PHONE
    context.user_data["phone"] = phone
    await update.effective_message.reply_text(
        "آدرس دقیق را بفرست (خیابان/کوچه/پلاک).",
        reply_markup=ReplyKeyboardMarkup([["لغو"]], resize_keyboard=True, one_time_keyboard=True),
    )
    return REG_ADDR

async def reg_addr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    addr = (update.effective_message.text or "").strip()
    u = db.get_user_by_tg(update.effective_user.id)
    db.update_profile(u["user_id"], name=context.user_data.get("name"), phone=context.user_data.get("phone"), address=addr)
    await update.effective_message.reply_text("✅ ثبت‌نام تکمیل شد.", reply_markup=MAIN_KB)
    return ConversationHandler.END

async def reg_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("لغو شد.", reply_markup=MAIN_KB)
    return ConversationHandler.END
# =====================================================================

# ---------- Router
def build_handlers():
    addprod_conv = ConversationHandler(
        entry_points=[CommandHandler("addproduct", addproduct_start)],
        states={
            AP_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_name)],
            AP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_price)],
            AP_PHOTO: [MessageHandler((filters.PHOTO | filters.Regex("^بدون عکس$")) & ~filters.COMMAND, ap_photo)],
            AP_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_desc)],
        },
        fallbacks=[CommandHandler("cancel", ap_cancel)],
        name="addproduct",
        persistent=False,
    )

    register_conv = ConversationHandler(
        entry_points=[
            CommandHandler("register", register_start),
            MessageHandler(filters.Regex("^ثبت نام 📝$"), register_start),
        ],
        states={
            REG_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            REG_PHONE: [
                MessageHandler(filters.CONTACT, reg_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone),
            ],
            REG_ADDR:  [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_addr)],
        },
        fallbacks=[CommandHandler("cancel", reg_cancel), MessageHandler(filters.Regex("^لغو$"), reg_cancel)],
        name="register",
        persistent=False,
    )

    return [
        CommandHandler("start", start),
        CommandHandler("help", help_cmd),

        # conversations
        addprod_conv,
        register_conv,

        # admin cmds
        CommandHandler("paid", paid),
        CommandHandler("topup", topup_cmd),
        CommandHandler("setcashback", setcashback),

        # main buttons
        MessageHandler(filters.Regex("^منو 🍬$"), show_menu),
        MessageHandler(filters.Regex("^کیف پول 👛$"), wallet),
        MessageHandler(filters.Regex("^(شارژ کارت‌به‌کارت|بازگشت ⬅️)$"), wallet_actions),
        MessageHandler(filters.Regex("^سفارش 🧾$"), order_entry),

        # order text (demo)
        MessageHandler(filters.TEXT & ~filters.COMMAND, order_text),

        MessageHandler(filters.Regex("^بازی 🎮$"), lambda u, c: u.effective_message.reply_text("...به‌زودی 🎲")),
        MessageHandler(filters.Regex("^ارتباط با ما ☎️$"), lambda u, c: u.effective_message.reply_text("پیام‌ات را ارسال کن.")),
        MessageHandler(filters.Regex("^راهنما ℹ️$"), help_cmd),
    ]
