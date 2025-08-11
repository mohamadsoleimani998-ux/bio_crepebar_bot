import os
from typing import Dict, Any, List

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, CallbackContext, CommandHandler, MessageHandler,
    ConversationHandler, filters
)

from . import db

ADMIN_IDS = {int(x) for x in (os.environ.get("ADMIN_IDS") or "").split(",") if x.strip()}
CASHBACK_PERCENT = int(os.environ.get("CASHBACK_PERCENT", "3"))

# ---------- استیت‌های گفتگو ----------
# افزودن محصول
AP_NAME, AP_PRICE, AP_PHOTO = range(3)
# سفارش ساده (جمع‌آوری اطلاعات مشتری و آیتم‌ها به صورت متن)
O_NAME, O_PHONE, O_ADDRESS, O_ITEMS, O_CONFIRM = range(5)
# کیف پول: شارژ کارت‌به‌کارت
W_TOPUP_AMOUNT, W_TOPUP_NOTE = range(2)
# تماس با ما
C_CONTACT = range(1)

# ---------- کمک‌ها ----------
def main_menu_kb() -> ReplyKeyboardMarkup:
    rows = [
        ["منو 🍬", "سفارش 🧾"],
        ["کیف پول 👜", "بازی 🎮"],
        ["ارتباط با ما ☎️", "راهنما ℹ️"]
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def ensure_user(update: Update) -> int:
    u = update.effective_user
    return db.upsert_user(u.id, u.full_name or u.username or str(u.id))

def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in ADMIN_IDS

# ---------- دستورات ساده ----------
async def start(update: Update, context: CallbackContext):
    ensure_user(update)
    txt = (
        "سلام! 👋 به ربات بایو کرپ بار خوش اومدی.\n"
        "از دکمه‌های زیر استفاده کن:\n"
        "• منو: نمایش محصولات با اسم، قیمت و عکس\n"
        "• سفارش: ثبت سفارش و دریافت آدرس/شماره\n"
        f"• کیف پول: مشاهده و شارژ (کارت‌به‌کارت / درگاه در آینده)\n"
        f"• کش‌بک: بعد از هر خرید به کیف پول اضافه می‌شود ({CASHBACK_PERCENT}%)\n"
        "• بازی: تب سرگرمی\n"
        "• ارتباط با ما: پیام به ادمین"
    )
    await update.effective_chat.send_message(txt, reply_markup=main_menu_kb())

async def help_command(update: Update, context: CallbackContext):
    await update.effective_chat.send_message("راهنما: از دکمه‌های پایین استفاده کنید.", reply_markup=main_menu_kb())

# ---------- منو محصولات ----------
async def show_menu(update: Update, context: CallbackContext):
    ensure_user(update)
    prods = db.get_products()
    if not prods:
        msg = "هنوز محصولی ثبت نشده است."
        if is_admin(update):
            msg += "\nادمین: /addproduct یا «افزودن محصول» را بزن."
        await update.effective_chat.send_message(msg, reply_markup=main_menu_kb())
        return

    # ارسال لیست — اگر عکس داشت آلبوم می‌فرستیم؛ در غیر اینصورت متن
    media: List[InputMediaPhoto] = []
    text_lines = []
    for p in prods[:10]:  # تا ۱۰ مورد
        line = f"#{p['id']} — {p['name']} — {p['price']:,} تومان"
        if p["photo_url"]:
            media.append(InputMediaPhoto(media=p["photo_url"], caption=line))
        else:
            text_lines.append(line)

    if media:
        await update.effective_chat.send_media_group(media)

    if text_lines:
        await update.effective_chat.send_message("\n".join(text_lines))

# ---------- افزودن محصول (ادمین) ----------
async def admin_add_product(update: Update, context: CallbackContext):
    if not is_admin(update):
        await update.effective_chat.send_message("فقط ادمین می‌تواند محصول اضافه کند.")
        return ConversationHandler.END
    await update.effective_chat.send_message("نام محصول را بفرستید:")
    return AP_NAME

async def ap_name(update: Update, context: CallbackContext):
    context.user_data["ap_name"] = update.message.text.strip()
    await update.effective_chat.send_message("قیمت به تومان:")
    return AP_PRICE

async def ap_price(update: Update, context: CallbackContext):
    try:
        price = int(update.message.text.strip())
    except ValueError:
        await update.effective_chat.send_message("قیمت عددی وارد کنید:")
        return AP_PRICE
    context.user_data["ap_price"] = price
    await update.effective_chat.send_message("لینک عکس (اختیاری). اگر ندارید، «-» بفرستید:")
    return AP_PHOTO

async def ap_photo(update: Update, context: CallbackContext):
    photo_url = update.message.text.strip()
    if photo_url in {"-", "—"}:
        photo_url = None
    pid = db.add_product(context.user_data["ap_name"], context.user_data["ap_price"], photo_url)
    await update.effective_chat.send_message(f"محصول با شناسه #{pid} ثبت شد ✅", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ---------- سفارش ----------
async def start_order(update: Update, context: CallbackContext):
    ensure_user(update)
    await update.effective_chat.send_message("اسم و فامیل:")
    return O_NAME

async def o_name(update: Update, context: CallbackContext):
    name = update.message.text.strip()
    context.user_data["o_name"] = name
    await update.effective_chat.send_message("شماره تماس:")
    return O_PHONE

async def o_phone(update: Update, context: CallbackContext):
    phone = update.message.text.strip()
    context.user_data["o_phone"] = phone
    await update.effective_chat.send_message("آدرس:")
    return O_ADDRESS

async def o_address(update: Update, context: CallbackContext):
    address = update.message.text.strip()
    context.user_data["o_address"] = address
    await update.effective_chat.send_message("محصولات درخواستی را بنویس (مثال: 2× #5 ، 1× #3) یا توضیح آزاد:",
                                             reply_markup=ReplyKeyboardMarkup([["انصراف"]], resize_keyboard=True))
    return O_ITEMS

def _parse_items(text: str) -> List[Dict[str, Any]]:
    # ورودی آزاد؛ فعلاً یک آیتمِ متنی به قیمت 0 می‌سازیم (برای MVP)
    return [{"id": 0, "name": text, "price": 0, "qty": 1}]

async def o_items(update: Update, context: CallbackContext):
    if update.message.text == "انصراف":
        await update.effective_chat.send_message("سفارش لغو شد.", reply_markup=main_menu_kb())
        return ConversationHandler.END
    items = _parse_items(update.message.text)
    context.user_data["o_items"] = items
    # ذخیره‌ی اطلاعات کاربر
    db.set_user_info(update.effective_user.id,
                     phone=context.user_data["o_phone"],
                     address=context.user_data["o_address"],
                     name=context.user_data["o_name"])
    # جمع کل از روی آیتم‌ها (در این نسخه 0 است؛ بعداً جمع واقعی منو را محاسبه می‌کنیم)
    total = sum(i["price"] * i.get("qty", 1) for i in items)
    context.user_data["o_total"] = total
    await update.effective_chat.send_message(
        f"تایید سفارش؟\nمشتری: {context.user_data['o_name']}\n"
        f"تلفن: {context.user_data['o_phone']}\n"
        f"آدرس: {context.user_data['o_address']}\n"
        f"جمع کل: {total:,} تومان\n\n"
        "اگر تایید است «تایید» بفرست، در غیر اینصورت «انصراف».",
        reply_markup=ReplyKeyboardMarkup([["تایید"], ["انصراف"]], resize_keyboard=True)
    )
    return O_CONFIRM

async def o_confirm(update: Update, context: CallbackContext):
    if update.message.text != "تایید":
        await update.effective_chat.send_message("سفارش لغو شد.", reply_markup=main_menu_kb())
        return ConversationHandler.END

    user = db.get_user_by_tg(update.effective_user.id)
    oid = db.create_order(user_id=user["id"],
                          items=context.user_data["o_items"],
                          total=context.user_data["o_total"],
                          address=context.user_data["o_address"],
                          phone=context.user_data["o_phone"])

    # اطلاع به ادمین
    admin_text = f"🆕 سفارش #{oid}\nاز: {user['name']} ({user['telegram_id']})\n" \
                 f"تلفن: {context.user_data['o_phone']}\n" \
                 f"آدرس: {context.user_data['o_address']}\n" \
                 f"آیتم‌ها: {context.user_data['o_items']}\n" \
                 f"جمع کل: {context.user_data['o_total']:,} تومان"
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=admin_text)
        except Exception:
            pass

    await update.effective_chat.send_message(
        f"سفارش شما با شماره {oid} ثبت شد ✅\n"
        f"کش‌بک {CASHBACK_PERCENT}% پس از پرداخت به کیف پول اضافه می‌شود.",
        reply_markup=main_menu_kb()
    )
    return ConversationHandler.END

# ---------- کیف پول ----------
async def wallet_menu(update: Update, context: CallbackContext):
    user_id = ensure_user(update)
    u = db.get_user_by_tg(update.effective_user.id)
    bal = db.wallet_balance(u["id"])
    kb = ReplyKeyboardMarkup([["شارژ کارت‌به‌کارت"], ["بازگشت"]], resize_keyboard=True)
    await update.effective_chat.send_message(f"موجودی کیف پول: {bal:,} تومان", reply_markup=kb)

async def w_topup_start(update: Update, context: CallbackContext):
    await update.effective_chat.send_message("مبلغ شارژ (تومان):")
    return W_TOPUP_AMOUNT

async def w_topup_amount(update: Update, context: CallbackContext):
    try:
        amt = int(update.message.text.strip())
        if amt <= 0: raise ValueError
    except ValueError:
        await update.effective_chat.send_message("مبلغ نامعتبر است. دوباره وارد کنید:")
        return W_TOPUP_AMOUNT
    context.user_data["topup_amt"] = amt
    await update.effective_chat.send_message("توضیح/رسید کارت‌به‌کارت (اختیاری) را بفرستید:")
    return W_TOPUP_NOTE

async def w_topup_note(update: Update, context: CallbackContext):
    note = update.message.text.strip()
    u = db.get_user_by_tg(update.effective_user.id)
    db.add_wallet(u["id"], context.user_data["topup_amt"], "topup", note)
    await update.effective_chat.send_message("شارژ ثبت شد ✅ (تایید دستی).", reply_markup=main_menu_kb())
    # اطلاع به ادمین
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, f"درخواست شارژ {context.user_data['topup_amt']:,} تومان از {u['name']} – {note}")
        except Exception:
            pass
    return ConversationHandler.END

# ---------- بازی (ساده) ----------
async def game_menu(update: Update, context: CallbackContext):
    msg = await update.effective_chat.send_dice(emoji="🎯")
    val = msg.dice.value
    if val >= 5:
        u = db.get_user_by_tg(update.effective_user.id)
        db.add_wallet(u["id"], 1000, "game", "جایزه بازی")
        await update.effective_chat.send_message("تبریک! ۱,۰۰۰ تومان جایزه به کیف پولت اضافه شد 🎉", reply_markup=main_menu_kb())

# ---------- تماس با ما ----------
async def contact_menu(update: Update, context: CallbackContext):
    await update.effective_chat.send_message("پیام خود را بنویسید تا برای ادمین ارسال شود:")
    return C_CONTACT

async def contact_forward(update: Update, context: CallbackContext):
    txt = f"پیام کاربر {update.effective_user.full_name} ({update.effective_user.id}):\n\n{update.message.text}"
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, txt)
        except Exception:
            pass
    await update.effective_chat.send_message("پیام شما ارسال شد ✅", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ---------- ثبت هندلرها ----------
from telegram.ext import MessageHandler, filters

def register(application: Application):
    # کامندهای رسمی (لاتین)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("order", start_order))
    application.add_handler(CommandHandler("wallet", wallet_menu))
    application.add_handler(CommandHandler("game", game_menu))
    application.add_handler(CommandHandler("contact", contact_menu))
    application.add_handler(CommandHandler("addproduct", admin_add_product))

    # معادل‌های فارسی با MessageHandler
    application.add_handler(MessageHandler(filters.Regex(r"^منو"), show_menu))
    application.add_handler(MessageHandler(filters.Regex(r"^سفارش"), start_order))
    application.add_handler(MessageHandler(filters.Regex(r"^کیف پول"), wallet_menu))
    application.add_handler(MessageHandler(filters.Regex(r"^بازی"), game_menu))
    application.add_handler(MessageHandler(filters.Regex(r"^ارتباط با ما"), contact_menu))
    application.add_handler(MessageHandler(filters.Regex(r"^راهنما"), help_command))
    application.add_handler(MessageHandler(filters.Regex(r"^افزودن محصول"), admin_add_product))

    # افزودن محصول (گفتگو)
    application.add_handler(ConversationHandler(
        name="add_product",
        entry_points=[
            CommandHandler("addproduct", admin_add_product),
            MessageHandler(filters.Regex(r"^افزودن محصول$"), admin_add_product),
        ],
        states={
            AP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_name)],
            AP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_price)],
            AP_PHOTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ap_photo)],
        },
        fallbacks=[],
    ))

    # سفارش (گفتگو)
    application.add_handler(ConversationHandler(
        name="order_flow",
        entry_points=[
            CommandHandler("order", start_order),
            MessageHandler(filters.Regex(r"^سفارش"), start_order),
        ],
        states={
            O_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_name)],
            O_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_phone)],
            O_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_address)],
            O_ITEMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_items)],
            O_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, o_confirm)],
        },
        fallbacks=[],
    ))

    # کیف پول – شارژ کارت‌به‌کارت
    application.add_handler(ConversationHandler(
        name="wallet_topup",
        entry_points=[MessageHandler(filters.Regex(r"^شارژ کارت‌به‌کارت$"), w_topup_start)],
        states={
            W_TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, w_topup_amount)],
            W_TOPUP_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, w_topup_note)],
        },
        fallbacks=[],
    ))

    # تماس با ما
    application.add_handler(ConversationHandler(
        name="contact",
        entry_points=[
            CommandHandler("contact", contact_menu),
            MessageHandler(filters.Regex(r"^ارتباط با ما"), contact_menu),
        ],
        states={C_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_forward)]},
        fallbacks=[],
    ))

# برای warmup از bot.py فراخوانی می‌شود
def startup_warmup(application: Application):
    db.init_db()
