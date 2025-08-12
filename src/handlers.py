# src/handlers.py
from __future__ import annotations
import os, re
from typing import List, Tuple

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
from telegram.ext import (
    Application, ContextTypes,
    CommandHandler, MessageHandler, ConversationHandler, filters
)
import src.db as db

ADMIN_IDS = {int(x) for x in (os.getenv("ADMIN_IDS") or "").split(",") if x.strip().isdigit()}

# ---------- UI ----------
MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("منو 🍬"), KeyboardButton("سفارش 🧾")],
        [KeyboardButton("کیف پول 👜"), KeyboardButton("بازی 🎮")],
        [KeyboardButton("ارتباط با ما ☎️"), KeyboardButton("راهنما ℹ️")],
        [KeyboardButton("افزودن محصول")],  # فقط برای ادمین عمل می‌کند
    ],
    resize_keyboard=True
)

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ---------- startup warmup ----------
def startup_warmup(application: Application):
    db.init_db()

# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.upsert_user(u.id, u.full_name or u.username or str(u.id))
    await update.effective_chat.send_message(
        "سلام! 👋 به ربات بایو کرپ‌بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن.",
        reply_markup=MAIN_KB
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("راهنما: از دکمه‌های پایین استفاده کنید.", reply_markup=MAIN_KB)

# ---------- MENU ----------
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products()
    if not prods:
        msg = "هنوز محصولی ثبت نشده."
        if _is_admin(update.effective_user.id):
            msg += "\n— ادمین: «افزودن محصول» یا /addproduct"
        await update.effective_chat.send_message(msg, reply_markup=MAIN_KB)
        return
    media: List[InputMediaPhoto] = []
    text_lines: List[str] = []
    for p in prods[:10]:
        line = f"#{p['id']} — {p['name']} — {int(p['price']):,} تومان"
        if p.get("photo_url"):
            media.append(InputMediaPhoto(media=p["photo_url"], caption=line))
        else:
            text_lines.append(line)
    if media:
        await update.effective_chat.send_media_group(media)
    if text_lines:
        await update.effective_chat.send_message("\n".join(text_lines), reply_markup=MAIN_KB)

# ---------- ADMIN: add product ----------
AP_NAME, AP_PRICE, AP_PHOTO = range(3)

async def admin_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.effective_chat.send_message("فقط ادمین اجازه دارد.", reply_markup=MAIN_KB)
        return ConversationHandler.END
    await update.effective_chat.send_message("نام محصول را بفرست:")
    return AP_NAME

async def ap_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = update.message.text.strip()
    await update.effective_chat.send_message("قیمت به تومان (عدد):")
    return AP_PRICE

async def ap_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip().replace(",", ""))
    except ValueError:
        await update.effective_chat.send_message("عدد صحیح وارد کن.")
        return AP_PRICE
    context.user_data["p_price"] = price
    await update.effective_chat.send_message("لینک عکس (اختیاری). اگر نداری «-» بفرست:")
    return AP_PHOTO

async def ap_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_url = update.message.text.strip()
    if photo_url in {"-", "—"}:
        photo_url = None
    row = db.add_product(context.user_data["p_name"], context.user_data["p_price"], photo_url)
    await update.effective_chat.send_message(f"ثبت شد ✅ (#{row['id']})", reply_markup=MAIN_KB)
    context.user_data.clear()
    return ConversationHandler.END

# ---------- ORDER (name -> qty -> address/phone -> confirm) ----------
O_PICK_NAME, O_SET_QTY, O_SET_ADDR, O_SET_PHONE, O_CONFIRM = range(5)

async def start_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = db.list_products()
    if not prods:
        await update.effective_chat.send_message("فعلاً محصولی نداریم.", reply_markup=MAIN_KB)
        return ConversationHandler.END
    names = "، ".join([p["name"] for p in prods[:15]])
    await update.effective_chat.send_message(f"نام محصول را بنویس (از بین: {names})")
    return O_PICK_NAME

async def o_pick_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    prod = db.get_product_by_name(name)
    if not prod:
        await update.effective_chat.send_message("نام محصول پیدا نشد. دوباره تلاش کن.")
        return O_PICK_NAME
    context.user_data["ord_product"] = prod
    await update.effective_chat.send_message("تعداد را وارد کن (عدد):")
    return O_SET_QTY

async def o_set_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty <= 0: raise ValueError
    except ValueError:
        await update.effective_chat.send_message("تعداد نامعتبر. دوباره عدد بفرست.")
        return O_SET_QTY
    context.user_data["ord_qty"] = qty
    await update.effective_chat.send_message("آدرس را بفرست:")
    return O_SET_ADDR

async def o_set_addr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ord_addr"] = update.message.text.strip()
    await update.effective_chat.send_message("شماره تماس را بفرست:")
    return O_SET_PHONE

async def o_set_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ord_phone"] = update.message.text.strip()
    p = context.user_data["ord_product"]
    q = context.user_data["ord_qty"]
    total = int(p["price"]) * q
    context.user_data["ord_total"] = total
    await update.effective_chat.send_message(
        f"تایید سفارش؟\n"
        f"{p['name']} × {q}\nمبلغ: {total:,} تومان\n"
        f"آدرس: {context.user_data['ord_addr']}\n"
        f"تلفن: {context.user_data['ord_phone']}\n\n"
        "«تایید» یا «انصراف»"
    )
    return O_CONFIRM

async def o_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text != "تایید":
        await update.effective_chat.send_message("لغو شد.", reply_markup=MAIN_KB)
        return ConversationHandler.END
    u = update.effective_user
    p = context.user_data["ord_product"]
    q = context.user_data["ord_qty"]
    addr = context.user_data["ord_addr"]
    phone = context.user_data["ord_phone"]
    # ذخیره‌ی اطلاعات تماس کاربر
    db.set_user_contact(u.id, phone=phone, address=addr, name=u.full_name)
    # ایجاد سفارش + کش‌بک
    result = db.create_order(u.id, items=[(p["id"], q)], address=addr, phone=phone, use_wallet=False)
    await update.effective_chat.send_message(
        f"ثبت شد ✅ شماره سفارش: {result['order_id']}\n"
        f"مبلغ کل: {int(float(result['total'])):,} | پرداختی: {int(float(result['payable'])):,}\n"
        f"کش‌بک: {int(float(result['cashback'])):,} تومان",
        reply_markup=MAIN_KB
    )
    # پیام به ادمین
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(
                aid,
                f"🆕 سفارش #{result['order_id']} از {u.full_name} ({u.id})\n"
                f"{p['name']} × {q}\n"
                f"آدرس: {addr}\nتلفن: {phone}\n"
                f"مبلغ: {int(float(result['total'])):,} | پرداختی: {int(float(result['payable'])):,}"
            )
        except Exception:
            pass
    context.user_data.clear()
    return ConversationHandler.END

# ---------- Wallet ----------
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = db.get_wallet(update.effective_user.id)
    await update.effective_chat.send_message(f"موجودی کیف پول: {int(bal):,} تومان", reply_markup=MAIN_KB)

# ---------- Game (simple) ----------
async def game_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.effective_chat.send_dice(emoji="🎯")
    if msg.dice.value >= 5:
        db.add_wallet(update.effective_user.id, 1000, "جایزه بازی")
        await update.effective_chat.send_message("تبریک! ۱,۰۰۰ تومان به کیف پولت اضافه شد 🎉", reply_markup=MAIN_KB)

# ---------- Contact ----------
C_CONTACT = range(1)
async def contact_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message("پیامت رو بنویس تا برای ادمین ارسال بشه:")
    return C_CONTACT

async def contact_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = f"پیام کاربر {update.effective_user.full_name} ({update.effective_user.id}):\n{update.message.text}"
    for aid in ADMIN_IDS:
        try: await context.bot.send_message(aid, txt)
        except Exception: pass
    await update.effective_chat.send_message("پیامت ارسال شد ✅", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ---------- Register all ----------
def register(application: Application):
    # Commands (Latin)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("order", start_order))
    application.add_handler(CommandHandler("wallet", wallet_menu))
    application.add_handler(CommandHandler("game", game_menu))
    application.add_handler(CommandHandler("contact", contact_menu))
    application.add_handler(CommandHandler("addproduct", admin_add_product))

    # Persian via MessageHandler
    application.add_handler(MessageHandler(filters.Regex(r"^شروع$"), start))
    application.add_handler(MessageHandler(filters.Regex(r"^راهنما"), help_command))
    application.add_handler(MessageHandler(filters.Regex(r"^منو"), show_menu))
    application.add_handler(MessageHandler(filters.Regex(r"^سفارش"), start_order))
    application.add_handler(MessageHandler(filters.Regex(r"^کیف پول"), wallet_menu))
    application.add_handler(MessageHandler(filters.Regex(r"^بازی"), game_menu))
    application.add_handler(MessageHandler(filters.Regex(r"^ارتباط با ما"), contact_menu))
    application.add_handler(MessageHandler(filters.Regex(r"^افزودن محصول$"), admin_add_product))

    # Admin add product (conversation)
    application.add_handler(ConversationHandler(
        name="add_product",
        entry_points=[
            CommandHandler("addproduct", admin_add_product),
            MessageHandler(filters.Regex(r"^افزودن محصول$"), admin_add_product),
        ],
        states={
            AP_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_name)],
            AP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_price)],
            AP_PHOTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_photo)],
        },
        fallbacks=[],
    ))

    # Order conversation
    application.add_handler(ConversationHandler(
        name="order_flow",
        entry_points=[
            CommandHandler("order", start_order),
            MessageHandler(filters.Regex(r"^سفارش"), start_order),
        ],
        states={
            O_PICK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_pick_name)],
            O_SET_QTY:   [MessageHandler(filters.TEXT & ~filters.COMMAND, o_set_qty)],
            O_SET_ADDR:  [MessageHandler(filters.TEXT & ~filters.COMMAND, o_set_addr)],
            O_SET_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_set_phone)],
            O_CONFIRM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, o_confirm)],
        },
        fallbacks=[],
    ))

    # Contact conversation
    application.add_handler(ConversationHandler(
        name="contact_flow",
        entry_points=[CommandHandler("contact", contact_menu),
                      MessageHandler(filters.Regex(r"^ارتباط با ما"), contact_menu)],
        states={C_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_forward)]},
        fallbacks=[],
    ))
