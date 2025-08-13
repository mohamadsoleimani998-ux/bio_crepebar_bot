from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)

from .base import log, WELCOME, MAIN_MENU, PAGE_SIZE, fmt_money
from . import db

# ---------- helpers ----------
def main_menu_kb():
    return ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True)

def build_products_page(page:int=1):
    items, total = db.list_products(page, PAGE_SIZE)
    rows = []
    for it in items:
        # callback: sel:<product_id>
        label = f"{fmt_money(it['price'])} — {it['name']}"
        rows.append([InlineKeyboardButton(label, callback_data=f"sel:{it['id']}")])
    # pager
    pages = max(1, (total + PAGE_SIZE - 1)//PAGE_SIZE)
    rows.append([
        InlineKeyboardButton("⬅️ قبلی", callback_data=f"pg:{max(1,page-1)}"),
        InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"),
        InlineKeyboardButton("بعدی ➡️", callback_data=f"pg:{min(pages,page+1)}"),
    ])
    rows.append([InlineKeyboardButton("🧾 مشاهده فاکتور", callback_data="inv")])
    return InlineKeyboardMarkup(rows)

def build_invoice_kb(items_exist:bool, can_pay_wallet:bool):
    rows = []
    if items_exist:
        rows.append([InlineKeyboardButton("✅ پرداخت از کیف پول", callback_data="payw")])
        rows.append([InlineKeyboardButton("💳 پرداخت مستقیم", callback_data="payx")])
    rows.append([InlineKeyboardButton("🍭 بازگشت به منو", callback_data="pg:1")])
    return InlineKeyboardMarkup(rows)

def format_invoice(order, items):
    if not order:
        return "سبد خرید خالی است."
    lines = ["🧾 فاکتور:"]
    total = 0
    for it in items:
        line = f"• {it['name']} × {it['qty']} = {fmt_money(it['line_total'])}"
        lines.append(line)
        total += float(it['line_total'] or 0)
    lines.append(f"\nجمع کل: {fmt_money(total)}")
    return "\n".join(lines)

# ---------- start / menu ----------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or "")
    await update.effective_chat.send_message(WELCOME, reply_markup=main_menu_kb())

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if "منو" in txt:
        await show_menu(update, ctx, page=1)
    elif "سفارش" in txt:
        await show_invoice(update, ctx)
    elif "کیف پول" in txt:
        await show_wallet(update, ctx)
    else:
        await update.message.reply_text("از دکمه‌های پایین استفاده کن.", reply_markup=main_menu_kb())

async def show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page:int=1):
    if update.message:
        await update.message.reply_text("منو:", reply_markup=main_menu_kb())
        await update.message.reply_text("👇 روی محصول بزن:", reply_markup=build_products_page(page))
    else:
        await update.callback_query.edit_message_reply_markup(build_products_page(page))

# ---------- callbacks ----------
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    try:
        if data.startswith("pg:"):
            page = int(data.split(":")[1])
            await q.edit_message_reply_markup(build_products_page(page))
            await q.answer()
            return

        if data.startswith("sel:"):
            pid = int(data.split(":")[1])
            user = db.get_user(update.effective_user.id)
            prod = db.get_product(pid)
            if not (user and prod):
                await q.answer("نامعتبر.", show_alert=True)
                return
            oid = db.open_draft_order(user["id"])
            db.add_or_increment_item(oid, pid, float(prod["price"]), 1)
            await q.answer("اضافه شد ✅", show_alert=False)
            await show_invoice(update, ctx, edit=True)
            return

        if data == "inv":
            await show_invoice(update, ctx, edit=True)
            await q.answer()
            return

        if data.startswith("inc:") or data.startswith("dec:"):
            pid = int(data.split(":")[1])
            user = db.get_user(update.effective_user.id)
            if not user:
                await q.answer("کاربر نامعتبر.", show_alert=True); return
            oid = db.open_draft_order(user["id"])
            delta = 1 if data.startswith("inc:") else -1
            db.change_item_qty(oid, pid, delta)
            await show_invoice(update, ctx, edit=True)
            await q.answer()
            return

        if data.startswith("rm:"):
            pid = int(data.split(":")[1])
            user = db.get_user(update.effective_user.id)
            if user:
                oid = db.open_draft_order(user["id"])
                db.remove_item(oid, pid)
                await show_invoice(update, ctx, edit=True)
            await q.answer()
            return

        if data == "payw":
            user = db.get_user(update.effective_user.id)
            ok = db.pay_with_wallet(user["id"])
            if not ok:
                await q.answer("موجودی کافی نیست یا سبد خالیه.", show_alert=True)
            else:
                await q.answer("پرداخت شد! 🎉", show_alert=True)
            await show_invoice(update, ctx, edit=True)
            return

        if data == "payx":
            # درگاه مستقیم: اینجا لینک دلخواهت رو بساز
            await q.answer()
            await q.edit_message_text(
                "پرداخت مستقیم فعال نیست. لطفاً از «پرداخت از کیف‌پول» استفاده کن.",
                reply_markup=build_invoice_kb(False, False),
            )
            return

        if data == "noop":
            await q.answer(); return

        await q.answer("دستور نامعتبر.", show_alert=True)

    except Exception as e:
        log.exception("callback error")
        await q.answer("خطای غیرمنتظره.", show_alert=True)

# ---------- wallet & invoice ----------
async def show_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        db.upsert_user(update.effective_user.id, update.effective_user.full_name or "")
        user = db.get_user(update.effective_user.id)
    bal = db.get_balance(user["id"])
    txt = f"موجودی شما: {fmt_money(bal)}\nکش‌بک فعال: ۳٪"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 شارژ کارت‌به‌کارت", callback_data="noop")]])
    await update.effective_chat.send_message(txt, reply_markup=kb)

async def show_invoice(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit:bool=False):
    user = db.get_user(update.effective_user.id)
    order, items = (None, [])
    if user:
        order, items = db.get_draft_with_items(user["id"])
    txt = format_invoice(order, items)
    can_pay = bool(items) and float(order["total_amount"] or 0) > 0 if order else False
    kb = build_invoice_kb(bool(items), can_pay)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=kb)
    else:
        await update.effective_chat.send_message(txt, reply_markup=kb)

# ---------- builder ----------
def build_handlers():
    return [
        CommandHandler("start", cmd_start),
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_text),
        CallbackQueryHandler(on_callback),
    ]
