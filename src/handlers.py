# src/handlers.py
from __future__ import annotations
import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler,
    ConversationHandler, filters
)
from . import db

# --- Admins from env (e.g. "1606170079, 12345")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(",", " ").split() if x.strip().isdigit()}

# Persian labels (exact match)
LBL_MENU    = "منو 🍬"
LBL_ORDER   = "سفارش 🧾"
LBL_WALLET  = "کیف پول 👛"
LBL_GAME    = "بازی 🎮"
LBL_CONTACT = "ارتباط با ما ☎️"
LBL_HELP    = "راهنما ℹ️"

def _kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(LBL_MENU),   KeyboardButton(LBL_ORDER)],
            [KeyboardButton(LBL_WALLET), KeyboardButton(LBL_GAME)],
            [KeyboardButton(LBL_CONTACT), KeyboardButton(LBL_HELP)],
        ], resize_keyboard=True
    )

async def _ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not u:
        return
    try:
        db.upsert_user(u.id, u.full_name or u.username or str(u.id))
    except Exception as e:
        context.application.logger.info(f"upsert warning: {e}")

def _is_admin(update: Update) -> bool:
    u = update.effective_user
    return bool(u and u.id in ADMIN_IDS)

# --- main commands ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update, context)
    txt = (
        "سلام! 👋 به ربات بایو کرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات با نام/قیمت و عکس\n"
        "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
        "• کیف پول: مشاهده/شارژ/کش‌بک\n"
        "• بازی: سرگرمی\n"
        "• ارتباط با ما: پیام به ادمین\n"
        "• راهنما: لیست دستورات"
    )
    await update.effective_message.reply_text(txt, reply_markup=_kb())

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update, context)
    try:
        rows = db.list_products()
    except Exception:
        rows = []
    if not rows:
        await update.effective_message.reply_text("فعلاً محصولی ثبت نشده.\nادمین: با /addproduct محصول اضافه کن.")
        return
    lines = ["🍬 منو:"]
    for i, r in enumerate(rows, 1):
        name, price = r[0], r[1]
        lines.append(f"{i}. {name} — {price:,} تومان")
    await update.effective_message.reply_text("\n".join(lines))

async def cmd_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update, context)
    await update.effective_message.reply_text("🧾 ثبت سفارش: محصول/آدرس/تلفن را ارسال کنید (نسخه ساده).")

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update, context)
    await update.effective_message.reply_text("👛 کیف پول: موجودی/شارژ/کش‌بک — به‌زودی.")

async def cmd_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update, context)
    await update.effective_message.reply_text("🎮 بازی: به‌زودی!")

async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ensure_user(update, context)
    await update.effective_message.reply_text("☎️ پیام‌تان را بفرستید تا به ادمین منتقل شود.")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "دستورات:\n/menu /order /wallet /game /contact /help\nادمین: /addproduct"
    )

# --- add product (admin) ---
ADD_NAME, ADD_PRICE, ADD_PHOTO = range(3)

async def addproduct_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.effective_message.reply_text("این دستور فقط برای ادمین فعاله.")
        return ConversationHandler.END
    await update.effective_message.reply_text("نام محصول را بفرست:")
    return ADD_NAME

async def addproduct_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.effective_message.text or "").strip()
    if not name:
        await update.effective_message.reply_text("نام خالیه. دوباره بفرست:")
        return ADD_NAME
    context.user_data["p_name"] = name
    await update.effective_message.reply_text("قیمت (تومان) را بفرست:")
    return ADD_PRICE

async def addproduct_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.effective_message.text or "").replace(",", "").strip()
    if not txt.isdigit():
        await update.effective_message.reply_text("قیمت باید عدد باشد. دوباره بفرست:")
        return ADD_PRICE
    context.user_data["p_price"] = int(txt)
    await update.effective_message.reply_text("عکس محصول را بفرست (یا بنویس «بدون عکس»):")
    return ADD_PHOTO

async def addproduct_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("p_name")
    price = context.user_data.get("p_price")
    photo_file_id = None
    if update.message and update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
    try:
        db.create_product(name=name, price=price, photo_file_id=photo_file_id, description=None)
        await update.effective_message.reply_text("✅ محصول اضافه شد.")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ خطا در ذخیره: {e}")
    context.user_data.clear()
    return ConversationHandler.END

async def addproduct_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text("لغو شد.")
    return ConversationHandler.END

async def fallback_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "متوجه نشدم؛ از دکمه‌های زیر یا دستورات /menu /order /wallet /game /contact /help استفاده کن.",
        reply_markup=_kb()
    )

def build_handlers():
    hs = []
    # slash
    hs += [
        CommandHandler("start", cmd_start),
        CommandHandler("menu", cmd_menu),
        CommandHandler("order", cmd_order),
        CommandHandler("wallet", cmd_wallet),
        CommandHandler("game", cmd_game),
        CommandHandler("contact", cmd_contact),
        CommandHandler("help", cmd_help),
    ]
    # buttons (exact regex)
    hs += [
        MessageHandler(filters.Regex(rf"^{LBL_MENU}$"),    cmd_menu),
        MessageHandler(filters.Regex(rf"^{LBL_ORDER}$"),   cmd_order),
        MessageHandler(filters.Regex(rf"^{LBL_WALLET}$"),  cmd_wallet),
        MessageHandler(filters.Regex(rf"^{LBL_GAME}$"),    cmd_game),
        MessageHandler(filters.Regex(rf"^{LBL_CONTACT}$"), cmd_contact),
        MessageHandler(filters.Regex(rf"^{LBL_HELP}$"),    cmd_help),
    ]
    # add product conv (before fallback)
    conv = ConversationHandler(
        entry_points=[CommandHandler("addproduct", addproduct_entry)],
        states={
            ADD_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_price)],
            ADD_PHOTO: [
                MessageHandler(filters.PHOTO, addproduct_photo),
                MessageHandler(filters.Regex(r"^(بدون عکس|بدون‌عکس)$"), addproduct_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", addproduct_cancel)],
        name="addproduct_conv",
        persistent=False,
    )
    hs.append(conv)

    # final fallback (CATCH-ALL)
    hs.append(MessageHandler(filters.ALL, fallback_unknown))
    return hs
