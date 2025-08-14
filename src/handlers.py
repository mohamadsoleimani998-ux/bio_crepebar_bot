# src/handlers.py
from __future__ import annotations
import json
from dataclasses import dataclass

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters,
)
from telegram.constants import ParseMode

from .base import log, ADMIN_IDS, is_admin, fmt_money, CARD_PAN, CARD_NAME, CARD_NOTE
from . import db  # از توابع موجود db.py استفاده می‌کنیم

# -------------------------
# دسته‌بندی‌ها
# -------------------------
@dataclass(frozen=True)
class Cat:
    key: str
    title: str
CATS = [
    Cat("espresso", "اسپرسو بار گرم و سرد"),
    Cat("tea",      "چای و دمنوش"),
    Cat("mixhot",   "ترکیبی گرم"),
    Cat("mock",     "موکتل ها"),
    Cat("sky",      "اسمونی ها"),
    Cat("cool",     "خنک"),
    Cat("semi",     "دمی"),
    Cat("crepe",    "کرپ"),
    Cat("pancake",  "پنکیک"),
    Cat("diet",     "رژیمی ها"),
    Cat("matcha",   "ماچا بار"),
]
CAT_BY_KEY = {c.key: c for c in CATS}

# -------------------------
# کیبورد اصلی
# -------------------------
MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("منو 🍭"), KeyboardButton("سفارش 🧾")],
        [KeyboardButton("کیف پول 👜"), KeyboardButton("راهنما ℹ️")],
    ], resize_keyboard=True
)

# ============ کمکی‌های DB که در db.py نیست ============
def _create_product(name: str, price: float, cat_key: str) -> int:
    """محصول جدید. دسته‌بندی در description با برچسب cat:<key> ذخیره می‌شود."""
    desc = f"cat:{cat_key}"
    with db._conn() as cn, cn.cursor() as cur:
        cur.execute(
            "INSERT INTO products(name, price, description, is_active) VALUES (%s,%s,%s,TRUE) RETURNING product_id",
            (name.strip(), price, desc)
        )
        return cur.fetchone()[0]

def _list_products_by_cat(cat_key: str, limit=8, offset=0):
    """فهرست محصول بر اساس دسته."""
    with db._conn() as cn, cn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM products WHERE is_active=TRUE AND COALESCE(description,'') ILIKE %s",
                    (f"%cat:{cat_key}%",))
        total = cur.fetchone()[0]
        cur.execute(
            """SELECT product_id, name, price
               FROM products
               WHERE is_active=TRUE AND COALESCE(description,'') ILIKE %s
               ORDER BY product_id DESC
               LIMIT %s OFFSET %s""",
            (f"%cat:{cat_key}%", limit, offset)
        )
        rows = cur.fetchall()
        return rows, total

def _insert_wallet_tx(user_id: int, amount: float, kind: str, meta: dict):
    with db._conn() as cn, cn.cursor() as cur:
        cur.execute(
            "INSERT INTO wallet_transactions(user_id, kind, amount, meta) VALUES (%s,%s,%s,%s::jsonb)",
            (user_id, kind, amount, json.dumps(meta or {}))
        )

# ============ /start ============
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u:
        await context.application.create_task(
            _ensure_user(context, u.id, u.full_name)
        )
    await update.effective_chat.send_message(
        "سلام 👋 به ربات بایو کِرِپ‌بار خوش اومدی.",
        reply_markup=MAIN_KB
    )

async def _ensure_user(context: ContextTypes.DEFAULT_TYPE, tg_id: int, name: str):
    try:
        db.upsert_user(tg_id, name or "")
    except Exception as e:
        log.exception("upsert_user failed: %s", e)

# ============ منو ============
async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(c.title, callback_data=f"cat:{c.key}")] for c in CATS]
    await update.effective_chat.send_message(
        "دستهٔ محصول را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ============ نمایش محصولات یک دسته ============
async def cb_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, cat_key = q.data.split(":", 1)
    page = int(context.user_data.get("cat_page", 1))
    rows, total = _list_products_by_cat(cat_key, limit=8, offset=(page-1)*8)

    if not rows:
        await q.edit_message_text("فعلاً محصولی در این دسته ثبت نشده است.")
        return

    buttons = []
    for pid, name, price in rows:
        buttons.append([InlineKeyboardButton(f"{name} — {fmt_money(price)}", callback_data=f"noop")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"catpg:{cat_key}:{page-1}"))
    if page*8 < total:
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"catpg:{cat_key}:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 بازگشت به دسته‌ها", callback_data="cats")])

    await q.edit_message_text(
        f"«{CAT_BY_KEY.get(cat_key).title}»", reply_markup=InlineKeyboardMarkup(buttons)
    )

async def cb_cat_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, cat_key, page = q.data.split(":", 2)
    context.user_data["cat_page"] = int(page)
    # فراخوانی مجدد
    q.data = f"cat:{cat_key}"
    await cb_category(update, context)

async def cb_back_to_cats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # پیام جدید برای تمیز بودن
    await show_categories(update, context)

# ============ کیف پول ============
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    me = db.get_user(u.id)
    bal = fmt_money(me["balance"] if me else 0)
    kb = [
        [InlineKeyboardButton("شارژ کارت‌به‌کارت 🧾", callback_data="topup:card")],
    ]
    await update.effective_chat.send_message(
        f"موجودی شما: {bal}",
        reply_markup=InlineKeyboardMarkup(kb)
    )

TOPUP_AMT, TOPUP_RECEIPT = range(2)

async def cb_topup_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    text = (
        f"برای شارژ کیف پول، ابتدا مبلغ را بنویسید (عدد):\n\n"
        f"کارت مقصد: <code>{CARD_PAN}</code>\n"
        f"به نام: {CARD_NAME}\n{CARD_NOTE}"
    )
    await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardRemove())
    return TOPUP_AMT

async def topup_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amt_txt = update.effective_message.text.replace(",", "").replace("٬", "")
    if not amt_txt.isdigit():
        await update.effective_message.reply_text("لطفاً فقط عدد وارد کنید (مثلاً 150000).")
        return TOPUP_AMT
    amt = float(amt_txt)
    context.user_data["topup_amt"] = amt
    await update.effective_message.reply_text(
        "حالا رسید کارت‌به‌کارت را به صورت «عکس» بفرستید."
    )
    return TOPUP_RECEIPT

async def topup_get_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    photo = update.effective_message.photo
    if not photo:
        await update.effective_message.reply_text("لطفاً تصویر رسید را ارسال کنید.")
        return TOPUP_RECEIPT

    amt = context.user_data.get("topup_amt", 0)
    me = db.get_user(u.id)
    if not me:
        db.upsert_user(u.id, u.full_name or "")

    # ارسال برای ادمین‌ها
    sent_ids = []
    for admin_id in ADMIN_IDS:
        try:
            p = photo[-1]  # بهترین کیفیت
            caption = f"درخواست شارژ از {u.full_name} (id={u.id})\nمبلغ: {fmt_money(amt)}\n/approve_{u.id}_{int(amt)}  |  /reject_{u.id}"
            m = await context.bot.send_photo(admin_id, p.file_id, caption=caption)
            sent_ids.append(m.message_id)
        except Exception as e:
            log.warning("forward to admin %s failed: %s", admin_id, e)

    await update.effective_message.reply_text(
        "درخواست شما ثبت شد و برای ادمین ارسال شد. پس از تایید، کیف پول‌تان شارژ می‌شود.",
        reply_markup=MAIN_KB
    )
    return ConversationHandler.END

async def admin_quick_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستورات سریع: /approve_123456789_150000  یا /reject_123456789"""
    txt = update.effective_message.text or ""
    if not is_admin(update.effective_user.id):
        return
    if txt.startswith("/approve_"):
        try:
            _, uid, amt = txt.split("_", 2)
            uid = int(uid); amt = float(amt)
            _insert_wallet_tx(uid, amt, "topup", {"by": "admin"})
            await update.effective_message.reply_text(f"✅ تایید شد. کیف پول کاربر {uid} به مبلغ {fmt_money(amt)} شارژ شد.")
        except Exception as e:
            log.exception("approve failed: %s", e)
            await update.effective_message.reply_text("خطا در تایید.")
    elif txt.startswith("/reject_"):
        try:
            _, uid = txt.split("_", 1)
            await update.effective_message.reply_text(f"⛔️ رد شد (user {uid}).")
        except Exception:
            pass

# ============ پنل ادمین: افزودن محصول ============
ADMIN_ADD_CAT, ADMIN_ADD_NAME, ADMIN_ADD_PRICE = range(3)

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    kb = [
        [InlineKeyboardButton("➕ افزودن محصول", callback_data="admin:add")],
    ]
    await update.effective_chat.send_message(
        "پنل ادمین:", reply_markup=InlineKeyboardMarkup(kb)
    )

async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    kb = [[InlineKeyboardButton(c.title, callback_data=f"aac:{c.key}")]
          for c in CATS]
    await q.message.reply_text("دستهٔ محصول را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_ADD_CAT

async def admin_add_choose_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, cat_key = q.data.split(":", 1)
    context.user_data["admin_cat"] = cat_key
    await q.message.reply_text("نام محصول را وارد کنید:")
    return ADMIN_ADD_NAME

async def admin_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["admin_name"] = update.effective_message.text.strip()
    await update.effective_message.reply_text("قیمت را (به تومان) وارد کنید:")
    return ADMIN_ADD_PRICE

async def admin_add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.effective_message.text.replace(",", "").replace("٬", "")
    if not txt.isdigit():
        await update.effective_message.reply_text("فقط عدد. مثال: 85000")
        return ADMIN_ADD_PRICE
    price = float(txt)
    name = context.user_data.get("admin_name")
    cat_key = context.user_data.get("admin_cat")
    try:
        pid = _create_product(name, price, cat_key)
        await update.effective_message.reply_text(
            f"✅ محصول ثبت شد.\n#{pid} — {name} — {fmt_money(price)}\nدسته: {CAT_BY_KEY[cat_key].title}",
            reply_markup=MAIN_KB
        )
    except Exception as e:
        log.exception("create_product failed: %s", e)
        await update.effective_message.reply_text("❌ خطا در ثبت محصول.", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ============ راهنما ============
async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "• منو 🍭: دیدن دسته‌ها و محصولات\n"
        "• کیف پول 👜: مشاهده موجودی و شارژ کارت‌به‌کارت\n"
        "• ادمین: /admin",
        reply_markup=MAIN_KB
    )

# =====================================================
# ثبت همه‌ی هندلرها روی Application
# =====================================================
def build_handlers(app: Application):
    # Start / Help / Main buttons
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:راهنما|راهنما ℹ️)$"), show_help))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:منو|منو 🍭)$"), show_categories))
    app.add_handler(MessageHandler(filters.Regex(r"^(?:کیف پول|کیف پول 👜)$"), wallet_menu))

    # دسته‌ها & صفحه‌بندی
    app.add_handler(CallbackQueryHandler(cb_category, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(cb_cat_page, pattern=r"^catpg:"))
    app.add_handler(CallbackQueryHandler(cb_back_to_cats, pattern=r"^cats$"))

    # کیف پول: تاپاپ کارت‌به‌کارت
    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_topup_card, pattern=r"^topup:card$")],
        states={
            TOPUP_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_get_amount)],
            TOPUP_RECEIPT: [MessageHandler(filters.PHOTO, topup_get_receipt)],
        },
        fallbacks=[],
        name="topup_conv",
        persistent=False,
    )
    app.add_handler(topup_conv)

    # ادمین
    app.add_handler(CommandHandler("admin", cmd_admin))
    admin_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_start, pattern=r"^admin:add$")],
        states={
            ADMIN_ADD_CAT: [CallbackQueryHandler(admin_add_choose_cat, pattern=r"^aac:")],
            ADMIN_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_name)],
            ADMIN_ADD_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_price)],
        },
        fallbacks=[],
        name="admin_add_conv",
        persistent=False
    )
    app.add_handler(admin_add_conv)

    # دستورات سریع ادمین برای تایید/رد شارژ
    app.add_handler(MessageHandler(filters.Regex(r"^/(?:approve_\d+_\d+|reject_\d+)$"), admin_quick_approve))
