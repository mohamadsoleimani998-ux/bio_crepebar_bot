import os
import random
from typing import List, Tuple

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton,
    InlineKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    filters, ContextTypes, CallbackQueryHandler
)

import src.db as db

# تنظیمات
ADMIN_IDS = []
_admin_env = os.getenv("ADMIN_IDS", "") or os.getenv("ADMIN_ID", "")
if _admin_env:
    for x in _admin_env.replace(" ", "").split(","):
        if x:
            try:
                ADMIN_IDS.append(int(x))
            except:
                pass

CASHBACK_PERCENT = int(os.getenv("CASHBACK_PERCENT", "0"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "")

# حالت‌های گفت‌وگو برای سفارش و شارژ
(ORDER_NAME, ORDER_PHONE, ORDER_ADDRESS, ORDER_ITEMS, ORDER_CONFIRM) = range(5)
(TOPUP_AMOUNT, TOPUP_METHOD, TOPUP_REF) = range(5, 8)

def _main_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        ["/products", "/wallet"],
        ["/order", "/help"],
        ["/game", "/contact"]
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if uid not in ADMIN_IDS:
            await update.effective_message.reply_text("دسترسی ادمین ندارید.")
            return
        return await func(update, context)
    return wrapper

# ---------- دستورات پایه ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.get_or_create_user(update.effective_user.id)
    txt = (
        "سلام! به ربات خوش آمدید.\n"
        "دستورات: /products , /wallet , /order , /help\n"
        "اگر ادمین هستید، برای افزودن محصول بعدا گزینه ادمین اضافه می‌کنیم."
    )
    await update.effective_message.reply_text(txt, reply_markup=_main_keyboard())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = "راهنما:\n/products نمایش منو\n/wallet کیف پول\n/order ثبت سفارش ساده"
    await update.effective_message.reply_text(txt)

# ---------- محصولات ----------
async def products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = db.list_products()
    if not items:
        await update.effective_message.reply_text("هنوز محصولی ثبت نشده است.")
        return
    lines = []
    media: List[InputMediaPhoto] = []
    for p in items:
        lines.append(f"{p['id']}) {p['name']} - {p['price']:,} تومان")
    await update.effective_message.reply_text("\n".join(lines))
    # اگر عکس دارند جداگانه بفرستیم
    for p in items:
        if p["photo_url"]:
            try:
                await update.effective_chat.send_photo(photo=p["photo_url"], caption=f"{p['id']}) {p['name']} - {p['price']:,} تومان")
            except:
                pass

@admin_only
async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    قالب:
    /addproduct نام | قیمت | عکس(اختیاری)
    مثال:
    /addproduct کرپ نوتلا | 120000 | https://...
    """
    msg = (update.effective_message.text or "").split(" ", 1)
    if len(msg) < 2:
        await update.effective_message.reply_text("قالب: /addproduct نام | قیمت | عکس(اختیاری)")
        return
    try:
        body = msg[1]
        parts = [x.strip() for x in body.split("|")]
        name = parts[0]
        price = int(parts[1].replace(",", ""))
        photo = parts[2] if len(parts) > 2 and parts[2] else None
        db.add_product(name, price, photo)
        await update.effective_message.reply_text("محصول اضافه شد ✅")
    except Exception as e:
        await update.effective_message.reply_text(f"خطا در افزودن محصول: {e}")

@admin_only
async def edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /editproduct id | name? | price? | photo?
    هر موردی را که نمی‌خواهید تغییر کند خالی بگذارید.
    مثال:
    /editproduct 3 | | 145000 |
    """
    msg = (update.effective_message.text or "").split(" ", 1)
    if len(msg) < 2:
        await update.effective_message.reply_text("قالب: /editproduct id | name? | price? | photo?")
        return
    try:
        parts = [x.strip() for x in msg[1].split("|")]
        pid = int(parts[0])
        name = parts[1] or None if len(parts) > 1 else None
        price = int(parts[2].replace(",", "")) if len(parts) > 2 and parts[2] else None
        photo = parts[3] or None if len(parts) > 3 else None
        db.edit_product(pid, name, price, photo)
        await update.effective_message.reply_text("محصول ویرایش شد ✅")
    except Exception as e:
        await update.effective_message.reply_text(f"خطا در ویرایش: {e}")

@admin_only
async def delete_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (update.effective_message.text or "").split(" ", 1)
    if len(msg) < 2:
        await update.effective_message.reply_text("قالب: /delproduct id")
        return
    try:
        pid = int(msg[1].strip())
        db.delete_product(pid)
        await update.effective_message.reply_text("حذف شد ✅")
    except Exception as e:
        await update.effective_message.reply_text(f"خطا در حذف: {e}")

# ---------- سفارش ----------
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = db.get_or_create_user(update.effective_user.id)
    if not u.get("name"):
        await update.effective_message.reply_text("لطفا نام و نام‌خانوادگی را بفرستید:")
        return ORDER_NAME
    if not u.get("phone"):
        await update.effective_message.reply_text("لطفا شماره تماس را بفرستید:")
        return ORDER_PHONE
    if not u.get("address"):
        await update.effective_message.reply_text("لطفا آدرس را بفرستید:")
        return ORDER_ADDRESS
    await update.effective_message.reply_text("شناسه محصول و تعداد را وارد کنید (مثال: 1:2, 3:1):")
    return ORDER_ITEMS

async def order_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.update_user_profile(update.effective_user.id, name=update.effective_message.text.strip())
    await update.effective_message.reply_text("شماره تماس را بفرستید:")
    return ORDER_PHONE

async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.update_user_profile(update.effective_user.id, phone=update.effective_message.text.strip())
    await update.effective_message.reply_text("آدرس را بفرستید:")
    return ORDER_ADDRESS

async def order_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.update_user_profile(update.effective_user.id, address=update.effective_message.text.strip())
    await update.effective_message.reply_text("شناسه محصول و تعداد را وارد کنید (مثال: 1:2, 3:1):")
    return ORDER_ITEMS

def _parse_items(text: str) -> List[Tuple[int,int]]:
    out = []
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        pid, qty = part.split(":")
        out.append((int(pid), int(qty)))
    return out

async def order_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pairs = _parse_items(update.effective_message.text)
        items = []
        total = 0
        for pid, qty in pairs:
            p = db.get_product(pid)
            if not p:
                raise ValueError(f"محصول {pid} یافت نشد")
            items.append({"id": pid, "qty": qty, "name": p["name"], "price": p["price"]})
            total += p["price"] * qty
        context.user_data["order_items"] = items
        context.user_data["order_total"] = total

        lines = [f"{it['name']} × {it['qty']} = {(it['price']*it['qty']):,}"]
        lines.append(f"\nجمع کل: {total:,} تومان")
        lines.append("\nتایید می‌کنید؟ (بله/خیر)")
        await update.effective_message.reply_text("\n".join(lines))
        return ORDER_CONFIRM
    except Exception as e:
        await update.effective_message.reply_text(f"فرمت نادرست: {e}\nمثال: 1:2, 3:1")
        return ORDER_ITEMS

async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.effective_message.text or "").strip()
    if txt not in ["بله", "بلی", "آره", "ok", "OK", "Yes", "yes"]:
        await update.effective_message.reply_text("لغو شد.")
        return ConversationHandler.END

    items = context.user_data.get("order_items", [])
    total = context.user_data.get("order_total", 0)
    uid = update.effective_user.id

    order_id = db.create_order(uid, items, total, "pending")

    # کش‌بک
    if CASHBACK_PERCENT > 0:
        cashback = int(total * CASHBACK_PERCENT / 100)
        if cashback > 0:
            db.add_wallet(uid, cashback)

    # پیام به کاربر
    await update.effective_message.reply_text(f"سفارش شما ثبت شد ✅\nکد سفارش: #{order_id}\nجمع کل: {total:,} تومان")

    # پیام به ادمین
    try:
        if ADMIN_IDS:
            lines = [f"🧾 سفارش جدید #{order_id} از {uid}"]
            for it in items:
                lines.append(f"- {it['name']} × {it['qty']}")
            lines.append(f"جمع کل: {total:,} تومان")
            for aid in ADMIN_IDS:
                await context.bot.send_message(chat_id=aid, text="\n".join(lines))
    except:
        pass

    return ConversationHandler.END

# ---------- کیف پول / شارژ ----------
async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = db.get_wallet(update.effective_user.id)
    await update.effective_message.reply_text(f"موجودی کیف پول شما: {bal:,} تومان")

async def topup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("مبلغ شارژ (تومان) را بفرستید:")
    return TOPUP_AMOUNT

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = int(update.effective_message.text.replace(",", "").strip())
        context.user_data["topup_amount"] = amt
        kb = ReplyKeyboardMarkup([["کارت‌به‌کارت", "درگاه(به‌زودی)"]], resize_keyboard=True, one_time_keyboard=True)
        await update.effective_message.reply_text("روش پرداخت را انتخاب کنید:", reply_markup=kb)
        return TOPUP_METHOD
    except:
        await update.effective_message.reply_text("عدد معتبر وارد کنید:")
        return TOPUP_AMOUNT

async def topup_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message.text.strip()
    if "کارت" in m:
        context.user_data["topup_method"] = "card2card"
        await update.effective_message.reply_text("لطفا ۴ رقم آخر کارت و یا رسید را بفرستید:")
        return TOPUP_REF
    else:
        context.user_data["topup_method"] = "gateway"
        await update.effective_message.reply_text("فعلا درگاه فعال نیست. اگر مایلید کارت‌به‌کارت کنید «/topup» را دوباره بزنید.")
        return ConversationHandler.END

async def topup_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ref = update.effective_message.text.strip()
    amt = context.user_data.get("topup_amount")
    method = context.user_data.get("topup_method")
    db.create_topup(update.effective_user.id, amt, method, ref)
    await update.effective_message.reply_text("درخواست شارژ ثبت شد و پس از تایید ادمین اعمال می‌شود. ✅")
    # اطلاع به ادمین
    try:
        for aid in ADMIN_IDS:
            await context.bot.send_message(aid, f"درخواست شارژ از {update.effective_user.id}\nمبلغ: {amt:,}\nروش: {method}\nref: {ref}")
    except:
        pass
    return ConversationHandler.END

@admin_only
async def confirm_topup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /confirmtopup USER_ID AMOUNT
    """
    parts = (update.effective_message.text or "").split()
    if len(parts) != 3:
        await update.effective_message.reply_text("قالب: /confirmtopup USER_ID AMOUNT")
        return
    uid = int(parts[1]); amt = int(parts[2])
    db.confirm_topup(uid, amt)
    await update.effective_message.reply_text("اعمال شد ✅")
    try:
        await context.bot.send_message(uid, f"شارژ {amt:,} تومان به کیف پول شما اعمال شد ✅")
    except:
        pass

# ---------- ارتباط با ما ----------
async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "ارتباط با ما:\n"
        "پیام خود را بفرستید تا برای ادمین ارسال شود."
    )
    await update.effective_message.reply_text(txt)

async def any_text_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # متن آزاد را برای ادمین فوروارد می‌کنیم
    if update.effective_user.id not in ADMIN_IDS and update.effective_message and update.effective_message.text:
        try:
            for aid in ADMIN_IDS:
                await context.bot.send_message(aid, f"پیام کاربر {update.effective_user.id}:\n{update.effective_message.text}")
        except:
            pass

# ---------- بازی ساده ----------
async def game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secret = random.randint(1, 9)
    context.user_data["game_secret"] = secret
    await update.effective_message.reply_text("یک عدد بین 1 تا 9 حدس بزن 😉 (فقط یک پیام بفرست)")
    
async def game_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "game_secret" not in context.user_data:
        return
    try:
        g = int(update.effective_message.text.strip())
        s = context.user_data.pop("game_secret")
        if g == s:
            await update.effective_message.reply_text("تبریک! درست حدس زدی 🎉")
        else:
            await update.effective_message.reply_text(f"نخورد 😅 عدد {s} بود.")
    except:
        pass

# ---------- ثبت هندلرها ----------
def setup(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("products", products))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("contact", contact))
    app.add_handler(CommandHandler("game", game))

    # ادمین
    app.add_handler(CommandHandler("addproduct", add_product))
    app.add_handler(CommandHandler("editproduct", edit_product))
    app.add_handler(CommandHandler("delproduct", delete_product_cmd))
    app.add_handler(CommandHandler("confirmtopup", confirm_topup_cmd))

    # سفارش (گفت‌وگو)
    order_conv = ConversationHandler(
        entry_points=[CommandHandler("order", order_start)],
        states={
            ORDER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_name)],
            ORDER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ORDER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_address)],
            ORDER_ITEMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_items)],
            ORDER_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_confirm)],
        },
        fallbacks=[]
    )
    app.add_handler(order_conv)

    # شارژ
    topup_conv = ConversationHandler(
        entry_points=[CommandHandler("topup", topup_start)],
        states={
            TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
            TOPUP_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_method)],
            TOPUP_REF: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_ref)],
        },
        fallbacks=[]
    )
    app.add_handler(topup_conv)

    # پیام آزاد → برای ادمین فوروارد
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_text_forward))
