from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode

from .base import *
from . import db

# =========================
# کیبورد اصلی
# =========================
MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("منو 🍬"), KeyboardButton("سفارش 🧾")],
        [KeyboardButton("کیف پول 👛"), KeyboardButton("بازی 🎮")],
        [KeyboardButton("ارتباط با ما ☎️"), KeyboardButton("راهنما ℹ️")],
    ],
    resize_keyboard=True
)

# =========================
# استارت
# =========================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or f"user-{u.id}")
    await update.effective_message.reply_text(
        "سلام! 👋 به ربات بایو کرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات\n"
        "• سفارش: فاکتور/نهایی‌سازی سفارش\n"
        "• کیف پول: مشاهده/شارژ، کش‌بک ۳٪ بعد هر خرید",
        reply_markup=MAIN_KB
    )

# =========================
# منو/محصولات
# =========================
def _products_keyboard(page: int = 1, page_size: int = 6):
    prods, total = db.list_products(page=page, page_size=page_size)
    rows = []
    for p in prods:
        text = f"{p['price']:,.0f}﷼ — {p['name']}"
        rows.append([InlineKeyboardButton(text, callback_data=f"prod:{p['id']}")])

    # ناوبری + دکمه فاکتور
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"pg:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{(total+page_size-1)//page_size or 1}", callback_data="noop"))
    if page * page_size < total:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"pg:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("مشاهده فاکتور 🧾", callback_data="cart")])
    return InlineKeyboardMarkup(rows)

async def show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("منو 🍬:", reply_markup=_products_keyboard(1))

# هندل کلیک‌ها در منو (فیکس + پیام تاییدی)
async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    try:
        if data.startswith("pg:"):
            page = int(data.split(":")[1])
            await q.answer()
            await q.edit_message_reply_markup(reply_markup=_products_keyboard(page))

        elif data.startswith("prod:"):
            pid = int(data.split(":")[1])
            p = db.get_product(pid)
            if not p:
                await q.answer("ناموجود", show_alert=True)
                return

            u = db.get_user(update.effective_user.id)
            oid = db.open_draft_order(u["id"])
            db.add_or_increment_item(oid, p["id"], float(p["price"]), inc=1)

            await q.answer("✅ به سبد اضافه شد")
            await q.message.reply_text(
                f"➕ «{p['name']}» به سبد اضافه شد.",
                disable_notification=True
            )

        elif data == "cart":
            await q.answer()
            await show_cart(update, ctx)

        else:
            await q.answer()

    except Exception as e:
        await q.answer("❌ خطای داخلی. دوباره تلاش کنید.", show_alert=True)
        log.exception("menu_cb error: %s", e)

# =========================
# فاکتور/سبد خرید
# =========================
def _cart_text(order, items):
    if not order or not items:
        return "🧾 فاکتور خالی است."
    lines = ["🧾 فاکتور:"]
    for it in items:
        lines.append(f"• {it['name']} × {it['qty']} = {int(it['line_total']):,} تومان")
    lines.append("—"*20)
    lines.append(f"مجموع: {int(order['total_amount']):,} تومان")
    return "\n".join(lines)

def _cart_keyboard(items):
    rows = []
    # برای هر قلم: – [نام×تعداد] +
    for it in items:
        pid = it["product_id"]
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"ci:-:{pid}"),
            InlineKeyboardButton(f"{it['name']} × {it['qty']}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"ci:+:{pid}")
        ])
        rows.append([InlineKeyboardButton("❌ حذف", callback_data=f"ci:rm:{pid}")])

    rows.append([InlineKeyboardButton("ادامه و پرداخت ✅", callback_data="checkout")])
    rows.append([InlineKeyboardButton("بازگشت به منو 🍬", callback_data="pg:1")])
    return InlineKeyboardMarkup(rows)

async def show_cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    text = _cart_text(order, items)
    kb = _cart_keyboard(items) if items else None

    m = update.effective_message
    if update.callback_query:
        # اگر از منو آمده‌ایم، پیام فعلی را ویرایش کن
        try:
            await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except:
            await m.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await m.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def cart_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        u = db.get_user(update.effective_user.id)
        oid = db.open_draft_order(u["id"])

        _, action, pid_s = q.data.split(":")
        pid = int(pid_s)

        if action == "+":
            db.change_item_qty(oid, pid, +1)
            await q.answer("➕ اضافه شد")

        elif action == "-":
            changed = db.change_item_qty(oid, pid, -1)
            await q.answer("➖ کم شد" if changed else "حذف شد")
        elif action == "rm":
            db.remove_item(oid, pid)
            await q.answer("🗑 حذف شد")
        else:
            await q.answer()
            return

        # به‌روزرسانی آنی فاکتور
        order, items = db.get_draft_with_items(u["id"])
        await q.message.edit_text(
            _cart_text(order, items),
            reply_markup=_cart_keyboard(items) if items else None,
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        await q.answer("❌ خطای داخلی", show_alert=True)
        log.exception("cart_cb error: %s", e)

# =========================
# سفارش (ورود از دکمه پایینی)
# =========================
async def order_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await show_cart(update, ctx)

# =========================
# کیف پول (ساده)
# =========================
async def wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    bal = db.get_balance(u["id"])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("شارژ کارت‌به‌کارت 💳", callback_data="topup")]
    ])
    await update.effective_message.reply_text(
        f"💳 موجودی شما: {int(bal):,} تومان\nکش‌بک فعال: ۳٪",
        reply_markup=kb
    )

# =========================
# ثبت هندلرها
# =========================
def build_handlers():
    return [
        CommandHandler("start", start),
        MessageHandler(filters.Regex("^منو"), show_menu),
        MessageHandler(filters.Regex("^سفارش"), order_cmd),
        MessageHandler(filters.Regex("^کیف پول"), wallet),
        CallbackQueryHandler(menu_cb, pattern="^(pg:|prod:|cart$|noop$)"),
        CallbackQueryHandler(cart_cb, pattern="^ci:"),
    ]
