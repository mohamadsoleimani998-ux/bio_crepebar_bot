# src/handlers.py
from __future__ import annotations

from math import ceil
from typing import List, Tuple

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from . import db

# ---------- تنظیمات نمایشی ----------
MAIN_BTNS = [
    [ "منو 🍭", "سفارش 🧾" ],
    [ "کیف پول 👛", "بازی 🎮" ],
    [ "ارتباط با ما ☎️", "راهنما ℹ️" ],
]
PAGE_SIZE = 8  # تعداد محصولات در هر صفحه
CURRENCY = "تومان"

def _main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(MAIN_BTNS, resize_keyboard=True)

def _fmt_price(v: int | float) -> str:
    return f"{int(v):,} {CURRENCY}".replace(",", "٬")

# ---------- کمک‌متدهای UI ----------
def _products_markup(products: List[dict], page: int, total: int) -> InlineKeyboardMarkup:
    """ساخت دکمه‌های منو + صفحه‌بندی + مشاهده فاکتور"""
    rows: List[List[InlineKeyboardButton]] = []
    for p in products:
        title = f"{_fmt_price(p['price'])} — {p['name']}"
        rows.append([InlineKeyboardButton(title, callback_data=f"prod:{p['product_id']}")])

    # صفحه‌بندی
    pages = max(1, ceil(total / PAGE_SIZE))
    nav_row: List[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"menu:{page-1}"))
    nav_row.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages:
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"menu:{page+1}"))
    rows.append(nav_row)

    # فاکتور
    rows.append([InlineKeyboardButton("🧾 مشاهده فاکتور", callback_data="order:show")])
    return InlineKeyboardMarkup(rows)

async def _send_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
    """نمایش منوی محصولات با صفحه‌بندی"""
    user = update.effective_user
    u = db.upsert_user(user.id, user.full_name or user.first_name or "")
    offset = (page - 1) * PAGE_SIZE
    products = db.get_products_page(offset=offset, limit=PAGE_SIZE)
    total = db.count_products()
    if not products:
        await update.effective_chat.send_message(
            "هنوز محصولی ثبت نشده است.", reply_markup=_main_kb()
        )
        return
    await update.effective_chat.send_message(
        "منو:",
        reply_markup=_products_markup(products, page=page, total=total),
    )

# ---------- فرمان‌ها ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.full_name or user.first_name or "")
    text = (
        "سلام! 👋 به ربات بایو کرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات با نام، قیمت و عکس\n"
        "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
        "• کیف پول: مشاهده/شارژ، کش‌بک ۳٪ بعد هر خرید\n"
        "• بازی: سرگرمی\n"
        "• ارتباط با ما: پیام به ادمین\n"
        "• راهنما: دستورات"
    )
    await update.effective_chat.send_message(text, reply_markup=_main_kb())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("برای شروع «منو 🍭» یا «سفارش 🧾» را بزن.", reply_markup=_main_kb())

async def wallet_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.upsert_user(user.id, user.full_name or user.first_name or "")
    bal = db.get_balance(u["user_id"])
    percent = db.get_cashback_percent()
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("💳 شارژ کارت‌به‌کارت", callback_data="wallet:topup")]]
    )
    await update.effective_chat.send_message(
        f"موجودی شما: {_fmt_price(bal)}\nکش‌بک فعال: {percent}٪",
        reply_markup=kb,
    )

async def order_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش فاکتور سفارش جاری"""
    user = update.effective_user
    u = db.upsert_user(user.id, user.full_name or user.first_name or "")
    order_id = db.ensure_draft_order(u["user_id"])
    items, meta = db.get_order_summary(order_id)
    if not items:
        await update.effective_chat.send_message("فاکتور خالی است. از «منو 🍭» محصول انتخاب کن.", reply_markup=_main_kb())
        return
    lines = ["🧾 فاکتور جاری:"]
    for it in items:
        lines.append(f"• {it['name']} ×{it['qty']} — {_fmt_price(it['line_total'])}")
    lines.append(f"\nجمع کل: {_fmt_price(meta['total_amount'])}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ پرداخت از کیف پول", callback_data="pay:wallet")],
        [InlineKeyboardButton("💳 پرداخت مستقیم", callback_data="pay:direct")],
    ])
    await update.effective_chat.send_message("\n".join(lines), reply_markup=kb)

# ---------- کلیک‌ روی دکمه‌ها ----------
async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """صفحه‌بندی منو"""
    q = update.callback_query
    await q.answer()
    try:
        page = int(q.data.split(":")[1])
    except Exception:
        page = 1
    await _send_menu(update, context, page=page)

async def cb_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

async def cb_show_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    # پاس بده به همون هندلر سفارش
    # (اینجا از edit_message_text هم می‌شه استفاده کرد؛ ساده نگه داشتیم)
    await order_msg(update, context)

async def cb_pick_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """افزودن محصول به سفارش (از دکمه منو)"""
    q = update.callback_query
    await q.answer("به سبد اضافه شد ✅", show_alert=False)
    user = update.effective_user
    u = db.upsert_user(user.id, user.full_name or user.first_name or "")
    order_id = db.ensure_draft_order(u["user_id"])
    product_id = int(q.data.split(":")[1])
    db.add_or_inc_item(order_id, product_id, qty=1)
    # آپدیت Toast کافیست؛ اگر خواستی می‌توانی دکمه فاکتور را هم جدا بفرستی
    # هیچ تغییر دیگری لازم نیست.

async def cb_pay_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = update.effective_user
    u = db.upsert_user(user.id, user.full_name or user.first_name or "")
    order_id = db.ensure_draft_order(u["user_id"])
    items, meta = db.get_order_summary(order_id)

    total = int(meta["total_amount"])
    bal = int(db.get_balance(u["user_id"]))
    if total <= 0 or not items:
        await q.edit_message_text("فاکتور خالی است.")
        return

    if bal < total:
        await q.edit_message_text(
            f"موجودی کافی نیست. موجودی: {_fmt_price(bal)} — مبلغ فاکتور: {_fmt_price(total)}\n"
            "از «کیف پول 👛» شارژ کنید."
        )
        return

    # در db.py باید پرداخت از کیف پول پیاده‌سازی شده باشد (کسر موجودی + تغییر وضعیت)
    # معمولاً با ثبت tx منفی (kind='order') و set_order_status('paid')
    # اینجا فقط پیام می‌دهیم؛ جزئیات را به همان تابع‌های db می‌سپاریم:
    # db.pay_with_wallet(u['user_id'], order_id)  <-- اگر چنین تابعی دارید
    # برای سازگاری با نسخه فعلی فقط پیام می‌دهیم:
    await q.edit_message_text("پرداخت از کیف پول ثبت شد ✅ (دمو)")
    # اگر تابع دارید، بعد از موفقیت، می‌توانید: db.set_order_status(order_id, 'paid')

async def cb_pay_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "پرداخت مستقیم به‌زودی…\nفعلاً از «کیف پول 👛» استفاده کنید."
    )

async def cb_wallet_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "برای شارژ کارت‌به‌کارت:\n"
        "💳 5029 0810 8098 4145\n"
        "فیش را همین‌جا ارسال کنید تا شارژ شود."
    )

# ---------- تطبیق پیام‌های متنی با منو ----------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if txt.startswith("منو"):
        await _send_menu(update, context, page=1)
    elif txt.startswith("سفارش"):
        await order_msg(update, context)
    elif txt.startswith("کیف پول"):
        await wallet_msg(update, context)
    elif txt.startswith("راهنما"):
        await help_cmd(update, context)
    elif txt.startswith("ارتباط"):
        await update.effective_chat.send_message("برای ارتباط: @YourAdmin", reply_markup=_main_kb())
    elif txt.startswith("بازی"):
        await update.effective_chat.send_message("…به‌زودی", reply_markup=_main_kb())
    else:
        await update.effective_chat.send_message("از منوی پایین انتخاب کن ✨", reply_markup=_main_kb())

# ---------- ثبت هندلرها ----------
def build_handlers():
    return [
        CommandHandler("start", start_cmd),
        CommandHandler("help", help_cmd),

        # پیام‌های منویی
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_router),

        # کال‌بک‌ها
        CallbackQueryHandler(cb_pick_product, pattern=r"^prod:\d+$"),
        CallbackQueryHandler(cb_menu,         pattern=r"^menu:\d+$"),
        CallbackQueryHandler(cb_noop,         pattern=r"^noop$"),
        CallbackQueryHandler(cb_show_order,   pattern=r"^order:show$"),
        CallbackQueryHandler(cb_pay_wallet,   pattern=r"^pay:wallet$"),
        CallbackQueryHandler(cb_pay_direct,   pattern=r"^pay:direct$"),
        CallbackQueryHandler(cb_wallet_topup, pattern=r"^wallet:topup$"),
    ]
