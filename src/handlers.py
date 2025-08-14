# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton,
    InputMediaPhoto,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters,
    ConversationHandler,
)

from .base import (
    log, ADMIN_IDS, is_admin, fmt_money, PAGE_SIZE, CATEGORIES,
    CARD_PAN, CARD_NAME, CARD_NOTE,
)
from . import db

# ---------- Keyboards ----------
def main_menu_kb():
    rows = [
        [KeyboardButton("🍭 منو"), KeyboardButton("🧾 سفارش")],
        [KeyboardButton("👛 کیف پول"), KeyboardButton("ℹ️ راهنما")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def categories_kb():
    rows = [[InlineKeyboardButton(title, callback_data=f"cat:{slug}")] for slug, title in CATEGORIES]
    return InlineKeyboardMarkup(rows)

def pagination_kb(slug: str, page: int, total: int):
    pages = (total + PAGE_SIZE - 1)//PAGE_SIZE or 1
    row = []
    if page > 1: row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"cat:{slug}:{page-1}"))
    row.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages: row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"cat:{slug}:{page+1}"))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("🔙 دسته‌ها", callback_data="menu:cats")]])

def cart_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ثبت نهایی", callback_data="order:submit")],
        [InlineKeyboardButton("💳 پرداخت کارت‌به‌کارت", callback_data="pay:card")],
        [InlineKeyboardButton("👛 پرداخت از کیف پول", callback_data="pay:wallet")],
        [InlineKeyboardButton("🔙 ادامه خرید", callback_data="menu:cats")],
    ])

def wallet_kb(balance_text: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet:topup")],
        [InlineKeyboardButton("🔙 منو", callback_data="menu:home")],
    ])

# ---------- Start / Help ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.full_name or user.username or "")
    await update.effective_chat.send_message(
        "سلام 😊\nربات فروشگاهی شما آماده است!\nاز منوی پایین استفاده کنید.",
        reply_markup=main_menu_kb(),
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "• 🍭 منو: انتخاب دسته و افزودن به سبد\n"
        "• 🧾 سفارش: مشاهده سبد و پرداخت\n"
        "• 👛 کیف پول: مشاهده موجودی و شارژ با رسید\n"
        "• پرداخت‌ها: کارت‌به‌کارت یا کیف پول",
        reply_markup=main_menu_kb(),
    )

# ---------- Menu & products ----------
async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        target = update.callback_query.message
    else:
        target = update.effective_chat
    await target.send_message("دستهٔ محصول را انتخاب کنید:", reply_markup=categories_kb())

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q: return
    await q.answer()
    parts = q.data.split(":")
    slug = parts[1]
    page = int(parts[2]) if len(parts) == 3 else 1

    prods, total = db.list_products_by_category(slug, page, PAGE_SIZE)
    if not prods:
        await q.edit_message_text("هنوز محصولی در این دسته ثبت نشده.", reply_markup=pagination_kb(slug, 1, 1))
        return

    lines = [f"📦 {p['name']} — {fmt_money(p['price'])}  ▫️ /buy_{p['id']}" for p in prods]
    text = "لیست محصولات:\n" + "\n".join(lines)
    await q.edit_message_text(text, reply_markup=pagination_kb(slug, page, total))

# /buy_<id>
async def quick_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        db.upsert_user(update.effective_user.id, update.effective_user.full_name or "")
        user = db.get_user(update.effective_user.id)

    prod_id = int(update.message.text.split("_", 1)[1])
    p = db.get_product(prod_id)
    if not p:
        await update.effective_chat.send_message("محصول یافت نشد.")
        return
    oid = db.open_draft_order(user["id"])
    db.add_or_increment_item(oid, p["id"], int(p["price"]), 1)
    await update.effective_chat.send_message(
        f"✅ «{p['name']}» به سبد اضافه شد.\n/Cart را ببین:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧾 مشاهده سبد", callback_data="order:view")]])
    )

# ---------- Cart / Order ----------
def _cart_text(order, items):
    if not order or not items:
        return "سبد خرید خالی است."
    lines = []
    for it in items:
        lines.append(f"• {it['name']} × {it['qty']} — {fmt_money(it['line_total'])}")
    lines.append(f"\nجمع کل: {fmt_money(order['total_amount'])}")
    return "\n".join(lines)

async def view_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    u = db.get_user(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    await (update.callback_query.message if update.callback_query else update.effective_chat).send_message(
        _cart_text(order, items), reply_markup=cart_kb()
    )

async def submit_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u = db.get_user(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    if not items:
        await q.edit_message_text("سبد خالی است.")
        return
    await q.edit_message_text("روش پرداخت را انتخاب کنید:", reply_markup=cart_kb())

# ---------- Payments ----------
async def pay_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u = db.get_user(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    if not items:
        await q.edit_message_text("سبد خالی است."); return
    total = int(order["total_amount"])
    balance = db.get_balance(u["id"])
    if balance < total:
        await q.edit_message_text(f"موجودی کافی نیست. موجودی: {fmt_money(balance)}")
        return
    db.add_wallet_tx(u["id"], "order", -total, {"order_id": order["order_id"]})
    db.set_order_status(order["order_id"], "paid")
    await q.edit_message_text(f"پرداخت از کیف پول انجام شد ✅\nمبلغ: {fmt_money(total)}")
    # فاکتور کوتاه
    await q.message.chat.send_message("🧾 فاکتور شما ثبت شد. سپاس 🙏")

async def pay_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u = db.get_user(update.effective_user.id)
    order, items = db.get_draft_with_items(u["id"])
    if not items:
        await q.edit_message_text("سبد خالی است."); return
    total = int(order["total_amount"])
    await q.edit_message_text(
        "اطلاعات کارت به کارت:\n"
        f"• شماره کارت: <code>{CARD_PAN}</code>\n"
        f"• به نام: {CARD_NAME}\n"
        f"• مبلغ: <b>{fmt_money(total)}</b>\n"
        f"• توضیح: {CARD_NOTE}\n\n"
        "پس از واریز، «رسید» را همین‌جا ارسال کنید تا ادمین تأیید کند.",
        parse_mode=ParseMode.HTML
    )
    context.user_data["await_receipt_for_order"] = order["order_id"]

async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # رسید کارت به کارت یا شارژ کیف پول
    user = db.get_user(update.effective_user.id)
    photo = update.message.photo[-1] if update.message.photo else None
    caption = (update.message.caption or "").strip()
    if not photo:
        return

    # اگر برای سفارش در انتظار رسید بود:
    order_id = context.user_data.pop("await_receipt_for_order", None)
    if order_id:
        amount = caption.strip() or "0"
        try:
            amount_int = int(amount.replace(",", ""))
        except Exception:
            # اگر مبلغ ننویسن، از جمع سفارش بخوانیم
            order, _ = db.get_draft_with_items(user["id"])
            amount_int = int(order["total_amount"]) if order else 0

        file_id = photo.file_id
        text = (f"رسید سفارش جدید 📥\n"
                f"کاربر: {update.effective_user.full_name} ({update.effective_user.id})\n"
                f"مبلغ: {fmt_money(amount_int)}\n"
                f"order_id={order_id}")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ تأیید سفارش", callback_data=f"admin:approve_order:{user['id']}:{order_id}:{amount_int}:{file_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"admin:reject:{user['id']}:order"),
        ]])
        for admin in ADMIN_IDS:
            try:
                await context.bot.send_photo(admin, file_id, caption=text, reply_markup=kb)
            except Exception as e:
                log.warning("send to admin failed: %s", e)
        await update.effective_chat.send_message("رسید ارسال شد. منتظر تأیید ادمین بمانید ✅")
        return

    # شارژ کیف پول
    amount_int = 0
    try:
        amount_int = int(caption.replace(",", ""))
    except Exception:
        pass
    if amount_int <= 0:
        await update.effective_chat.send_message("برای شارژ کیف پول، مبلغ را در کپشن بنویسید. مثال: 150000")
        return

    file_id = photo.file_id
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تأیید شارژ", callback_data=f"admin:approve_topup:{user['id']}:{amount_int}:{file_id}"),
        InlineKeyboardButton("❌ رد", callback_data=f"admin:reject:{user['id']}:topup"),
    ]])
    text = f"درخواست شارژ کیف پول 💳\nکاربر: {update.effective_user.full_name} ({update.effective_user.id})\nمبلغ: {fmt_money(amount_int)}"
    for admin in ADMIN_IDS:
        try:
            await context.bot.send_photo(admin, file_id, caption=text, reply_markup=kb)
        except Exception as e:
            log.warning("send to admin failed: %s", e)
    await update.effective_chat.send_message("رسید شارژ ارسال شد. پس از تأیید ادمین، موجودی شارژ می‌شود.")

# ---------- Wallet ----------
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    bal = db.get_balance(u["id"])
    await (update.callback_query.message if update.callback_query else update.effective_chat).send_message(
        f"موجودی شما: {fmt_money(bal)}", reply_markup=wallet_kb(fmt_money(bal))
    )

async def wallet_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "برای شارژ کیف پول:\n"
        f"۱) کارت به کارت به شماره <code>{CARD_PAN}</code> ({CARD_NAME})\n"
        "۲) رسید پرداخت را همین‌جا به‌صورت عکس ارسال کنید.\n"
        "۳) مبلغ را در کپشن عکس بنویسید. مثال: 200000",
        parse_mode=ParseMode.HTML
    )

# ---------- Admin: add product ----------
ADD_CAT, ADD_NAME, ADD_PRICE, ADD_PHOTO, ADD_DESC = range(5)

async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.effective_chat.send_message(
        "پنل ادمین:\n/add_product برای افزودن محصول\n/approve برای لیست در انتظار",
        reply_markup=main_menu_kb(),
    )

async def add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return ConversationHandler.END
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=f"addcat:{s}")] for s, t in CATEGORIES])
    await update.effective_chat.send_message("دسته را انتخاب کنید:", reply_markup=kb)
    return ADD_CAT

async def add_product_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    slug = q.data.split(":",1)[1]
    context.user_data["new_product"] = {"category": slug}
    await q.edit_message_text("نام محصول را بفرست:")
    return ADD_NAME

async def add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_product"]["name"] = update.message.text.strip()
    await update.message.reply_text("قیمت به تومان (فقط عدد):")
    return ADD_PRICE

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.replace(",", ""))
    except Exception:
        await update.message.reply_text("قیمت عددی نیست. دوباره بفرست:")
        return ADD_PRICE
    context.user_data["new_product"]["price"] = price
    await update.message.reply_text("اگر عکس دارید بفرستید؛ در غیر اینصورت /skip را بزنید.")
    return ADD_PHOTO

async def add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = update.message.photo[-1].file_id if update.message.photo else None
    context.user_data["new_product"]["photo"] = file_id
    await update.message.reply_text("توضیح کوتاه (اختیاری). اگر ندارید /skip را بزنید.")
    return ADD_DESC

async def add_product_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # برای /skip در مراحل عکس/توضیح
    return await add_product_desc(update, context)

async def add_product_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text and not update.message.text.startswith("/skip"):
        context.user_data["new_product"]["desc"] = update.message.text.strip()
    data = context.user_data.pop("new_product")
    pid = db.add_product(
        data.get("name"), data.get("price"), data.get("category"),
        data.get("photo"), data.get("desc"),
    )
    await update.effective_chat.send_message(f"محصول ثبت شد ✅ (id={pid})")
    return ConversationHandler.END

# ---------- Admin approvals ----------
async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not is_admin(update.effective_user.id):
        await q.answer("اجازه ندارید", show_alert=True); return
    parts = q.data.split(":")
    action = parts[1]
    if action == "approve_topup":
        user_id, amount, file_id = int(parts[2]), int(parts[3]), parts[4]
        db.add_wallet_tx(user_id, "topup", amount, {"by":"admin"})
        await q.edit_message_caption(caption="✅ شارژ تأیید شد.")
        await context.bot.send_message(user_id, f"شارژ کیف پول شما تأیید شد: {fmt_money(amount)}")
    elif action == "approve_order":
        user_id, order_id, amount, file_id = int(parts[2]), int(parts[3]), int(parts[4]), parts[5]
        # (واریزی برای سفارش) – اینجا بدون برداشت از کیف پول فقط ثبت پرداخت و تغییر وضعیت
        db.set_order_status(order_id, "paid")
        await q.edit_message_caption(caption="✅ پرداخت سفارش تأیید شد.")
        await context.bot.send_message(user_id, "پرداخت شما تأیید شد. سفارش ثبت شد ✅")
    elif action == "reject":
        user_id, kind = int(parts[2]), parts[3]
        await q.edit_message_caption(caption="❌ رد شد.")
        await context.bot.send_message(user_id, "درخواست شما توسط ادمین رد شد.")

# ---------- Router ----------
def build_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.Regex("^🍭 منو$"), show_categories))
    app.add_handler(MessageHandler(filters.Regex("^🧾 سفارش$"), view_order))
    app.add_handler(MessageHandler(filters.Regex("^👛 کیف پول$"), wallet_menu))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ راهنما$"), help_cmd))

    app.add_handler(CallbackQueryHandler(lambda u,c: show_categories(u,c), pattern="^menu:cats$"))
    app.add_handler(CallbackQueryHandler(lambda u,c: start(u,c), pattern="^menu:home$"))

    app.add_handler(CallbackQueryHandler(show_products, pattern=r"^cat:"))
    app.add_handler(MessageHandler(filters.Regex(r"^/buy_\d+$"), quick_buy))

    app.add_handler(CallbackQueryHandler(view_order, pattern="^order:view$"))
    app.add_handler(CallbackQueryHandler(submit_order, pattern="^order:submit$"))
    app.add_handler(CallbackQueryHandler(pay_wallet, pattern="^pay:wallet$"))
    app.add_handler(CallbackQueryHandler(pay_card, pattern="^pay:card$"))

    app.add_handler(CallbackQueryHandler(wallet_topup, pattern="^wallet:topup$"))
    app.add_handler(CallbackQueryHandler(admin_callbacks, pattern=r"^admin:"))

    # رسیدها (عکس با کپشن مبلغ)
    app.add_handler(MessageHandler(filters.PHOTO, handle_receipt))

    # ادمین
    app.add_handler(CommandHandler("admin", admin_entry))

    conv = ConversationHandler(
        entry_points=[CommandHandler("add_product", add_product_start)],
        states={
            ADD_CAT: [CallbackQueryHandler(add_product_cat, pattern="^addcat:")],
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            ADD_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            ADD_PHOTO:[MessageHandler(filters.PHOTO, add_product_photo),
                       CommandHandler("skip", add_product_skip)],
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_desc),
                       CommandHandler("skip", add_product_desc)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
    )
    app.add_handler(conv)
