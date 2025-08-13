from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from .base import log, tman, is_admin
from . import db

# -------- Keyboards --------
MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🍭 منو"), KeyboardButton("🧾 سفارش")],
        [KeyboardButton("👛 کیف پول"), KeyboardButton("🎮 بازی")],
        [KeyboardButton("☎️ ارتباط با ما"), KeyboardButton("ℹ️ راهنما")],
    ],
    resize_keyboard=True
)

def _pager_buttons(page, total, page_size, prefix):
    pages = max(1, (total + page_size - 1) // page_size)
    txt = f"{page}/{pages}"
    prev_btn = InlineKeyboardButton("⬅️ قبلی", callback_data=f"{prefix}:pg:{max(1,page-1)}") if page > 1 else None
    next_btn = InlineKeyboardButton("بعدی ➡️", callback_data=f"{prefix}:pg:{min(pages,page+1)}") if page < pages else None
    row = [b for b in (prev_btn, InlineKeyboardButton(txt, callback_data="noop"), next_btn) if b]
    return row

# -------- Views --------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.first_name or "User")
    text = (
        "سلام! 👋 به ربات بایو کرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو 🍭: نمایش محصولات با نام و قیمت\n"
        "• سفارش 🧾: ثبت سفارش و مشاهده فاکتور\n"
        "• کیف پول 👛: موجودی/شارژ و کش‌بک ۳٪ بعد هر خرید\n"
        "• بازی 🎮: سرگرمی\n"
        "• ارتباط با ما ☎️: پیام به ادمین\n"
        "• راهنما ℹ️: دستورات"
    )
    await update.effective_message.reply_text(text, reply_markup=MAIN_KB)

# ---- Wallet
async def on_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user.id
    rec = db.get_user(tg)
    if not rec:
        await update.effective_message.reply_text("کاربر یافت نشد.")
        return
    text = f"موجودی شما: {tman(rec['balance'])}\nکش‌بک فعال: ۳٪"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("شارژ کارت‌به‌کارت 🧾", callback_data="wallet:topup")]])
    await update.effective_message.reply_text(text, reply_markup=kb)

# ---- Menu (products list as buttons)
PAGE_SIZE = 6

async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page:int=1):
    prods, total = db.list_products(page=page, page_size=PAGE_SIZE)
    if not prods:
        await update.effective_message.reply_text("هنوز محصول فعالی ثبت نشده.")
        return
    rows = []
    for p in prods:
        rows.append([InlineKeyboardButton(f"{tman(p['price'])} — {p['name']}", callback_data=f"prod:{p['id']}")])
    rows.append(_pager_buttons(page, total, PAGE_SIZE, "menu"))
    rows.append([InlineKeyboardButton("🧾 مشاهده فاکتور", callback_data="order:invoice")])
    await update.effective_message.reply_text("منو:", reply_markup=InlineKeyboardMarkup(rows))

# ---- Order / Cart
def _invoice_text(order, items):
    if not order or not items:
        return "سبد خرید خالی است."
    lines = ["🧾 فاکتور:", ""]
    s = 0
    for it in items:
        lines.append(f"{it['name']} × {it['qty']} = {tman(it['line_total'])}")
        s += float(it["line_total"])
    lines += ["", f"جمع کل: {tman(order['total_amount'])}"]
    return "\n".join(lines)

async def on_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    txt = _invoice_text(order, items)
    kb = []
    if items:
        kb.append([InlineKeyboardButton("✅ تسویه از کیف پول", callback_data="pay:wallet")])
        kb.append([InlineKeyboardButton("💳 پرداخت مستقیم (دمو)", url="https://example.com/pay")])
    kb.append([InlineKeyboardButton("بازگشت به منو 🍭", callback_data="menu:pg:1")])
    await update.effective_message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))

# ---- Callbacks
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    await q.answer()
    # menu pagination
    if data.startswith("menu:pg:"):
        page = int(data.split(":")[-1])
        await on_menu(update, context, page)
        return
    # show invoice
    if data == "order:invoice":
        await on_invoice(update, context)
        return
    # select product
    if data.startswith("prod:"):
        pid = int(data.split(":")[1])
        prod = db.get_product(pid)
        if not prod:
            await q.edit_message_text("این محصول دیگر در دسترس نیست.")
            return
        # add to cart
        u = db.get_user(update.effective_user.id)
        oid = db.open_draft_order(u["id"])
        db.add_or_increment_item(oid, pid, float(prod["price"]), 1)
        await q.edit_message_text(f"✅ «{prod['name']}» به سبد اضافه شد.\n"
                                  f"قیمت: {tman(prod['price'])}",
                                  reply_markup=InlineKeyboardMarkup([
                                      [InlineKeyboardButton("➕ یکی دیگه", callback_data=f"prod:{pid}")],
                                      [InlineKeyboardButton("🧾 مشاهده فاکتور", callback_data="order:invoice")],
                                      [InlineKeyboardButton("⬅️ بازگشت به منو", callback_data="menu:pg:1")]
                                  ]))
        return
    # wallet pay (demo: فقط از موجودی کم می‌کنیم و سفارش را paid نمی‌کنیم کامل)
    if data == "pay:wallet":
        u = db.get_user(update.effective_user.id)
        order, items = db.get_draft_with_items(u["id"])
        if not order or not items:
            await q.edit_message_text("سبد خالی است.")
            return
        bal = db.get_balance(u["id"])
        total = float(order["total_amount"])
        if bal < total:
            await q.edit_message_text("موجودی کیف پول کافی نیست. ابتدا شارژ کنید.")
            return
        # ثبت تراکنش منفی
        from psycopg2 import sql
        with db._conn() as cn, cn.cursor() as cur:
            cur.execute("""INSERT INTO wallet_transactions(user_id, kind, amount, meta)
                           VALUES (%s,'order', %s * -1, jsonb_build_object('order_id',%s))""",
                        (u["id"], total, order["order_id"]))
            # سفارش را paid
            cur.execute("UPDATE orders SET status='paid' WHERE order_id=%s", (order["order_id"],))
        await q.edit_message_text("✅ پرداخت از کیف پول انجام شد. ممنون! ✨")
        return

    # ignore
    if data == "noop":
        return

# ---- Text router
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.effective_message.text or "").strip()
    if txt in ("منو", "🍭 منو"):
        await on_menu(update, context, 1)
    elif txt in ("سفارش", "🧾 سفارش"):
        await on_invoice(update, context)
    elif txt in ("کیف پول", "👛 کیف پول"):
        await on_wallet(update, context)
    elif txt in ("بازی", "🎮 بازی"):
        await update.effective_message.reply_text("به‌زودی...")
    elif txt in ("راهنما", "ℹ️ راهنما"):
        await update.effective_message.reply_text("از دکمه‌ها استفاده کن؛ همه‌چیز واضحه 🤝")
    else:
        await update.effective_message.reply_text("گزینه‌ای انتخاب کن:", reply_markup=MAIN_KB)

def build_handlers():
    return [
        CommandHandler("start", cmd_start),
        CallbackQueryHandler(on_cb),
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_text),
    ]
