# bot.py
# -*- coding: utf-8 -*-

import os
import asyncio
from typing import Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputFile
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# ---------------------- Config ----------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL is missing")

# ---------------------- DB helpers ----------------------
def db_conn():
    # autocommit so we can run DDL without manual commit
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn

def db_exec(sql: str, params: Tuple = ()):
    with db_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            try:
                rows = cur.fetchall()
            except psycopg2.ProgrammingError:
                rows = []
    return rows

def init_db():
    # Create tables if not exist (safe to call on every boot)
    db_exec("""
    CREATE TABLE IF NOT EXISTS users(
        id SERIAL PRIMARY KEY,
        tg_id BIGINT UNIQUE NOT NULL,
        name TEXT,
        phone TEXT,
        address TEXT,
        wallet INT NOT NULL DEFAULT 0,
        registered BOOLEAN NOT NULL DEFAULT FALSE
    );
    """)
    db_exec("""
    CREATE TABLE IF NOT EXISTS products(
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        price INT NOT NULL,
        photo_id TEXT
    );
    """)
    db_exec("""
    CREATE TABLE IF NOT EXISTS orders(
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        qty INT NOT NULL DEFAULT 1,
        delivery_method TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
    );
    """)
    db_exec("""
    CREATE TABLE IF NOT EXISTS payments(
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        amount INT NOT NULL,
        status TEXT NOT NULL DEFAULT 'requested', -- requested/approved/rejected
        ref TEXT
    );
    """)
    db_exec("""
    CREATE TABLE IF NOT EXISTS music(
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        file_id TEXT NOT NULL
    );
    """)

# ---------------------- Keyboards ----------------------
def main_menu(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("منوی محصولات ☕️", callback_data="menu_products")],
        [InlineKeyboardButton("کیف پول 💸", callback_data="wallet")],
        [InlineKeyboardButton("موزیک‌های کافه 🎶", callback_data="music")],
        [InlineKeyboardButton("بازی‌ها 🎮", callback_data="games")]
    ]
    # اینستاگرام به صورت لینک بیرونی
    rows.append([InlineKeyboardButton("اینستاگرام 📱➡️", url="https://instagram.com/")])
    if is_admin:
        rows.append([InlineKeyboardButton("➕ افزودن محصول", callback_data="admin_add_product")])
        rows.append([InlineKeyboardButton("✏️ ویرایش محصولات", callback_data="admin_edit_product")])
        rows.append([InlineKeyboardButton("🎵 افزودن موزیک", callback_data="admin_add_music")])
    return InlineKeyboardMarkup(rows)

def back_menu_kb(is_admin: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت به منو", callback_data="back_main")]])

# ---------------------- Conversations States ----------------------
# Register user
ASK_NAME, ASK_PHONE, ASK_ADDRESS = range(3)
# Add product
P_NAME, P_PRICE, P_PHOTO = range(3,6)
# Edit product
E_SELECT, E_FIELD, E_VALUE, E_PHOTO = range(6,10)
# Wallet top-up
W_AMOUNT = 10
# Order flow
O_QTY, O_DELIVERY = 11, 12
# Add music
M_TITLE, M_FILE = 13, 14

# ---------------------- Utils ----------------------
def is_admin(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    return uid == ADMIN_ID

def ensure_user(update: Update) -> Optional[dict]:
    tg_id = update.effective_user.id
    rows = db_exec("SELECT * FROM users WHERE tg_id=%s", (tg_id,))
    if rows:
        return rows[0]
    # create skeleton user
    db_exec("INSERT INTO users(tg_id) VALUES(%s) ON CONFLICT (tg_id) DO NOTHING;", (tg_id,))
    rows = db_exec("SELECT * FROM users WHERE tg_id=%s", (tg_id,))
    return rows[0] if rows else None

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = None):
    u = ensure_user(update)
    welcome = text or "به بایو کِرِپ بار خوش آمدید ☕️\nچطور می‌تونم کمک کنم؟"
    await (update.effective_message.reply_text(
        welcome, reply_markup=main_menu(is_admin(update))
    ))

# ---------------------- Start & Back ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = ensure_user(update)
    # اگر ثبت نام کامل نیست، بفرستیم تو ثبت نام
    if not u.get("registered"):
        await update.message.reply_text("برای ادامه، لطفاً ثبت‌نام کنید.\nنام و نام خانوادگی؟")
        return ASK_NAME
    await send_main_menu(update, context)

async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dummy = Update(update.update_id, message=query.message)  # hack to reuse helper
    await send_main_menu(dummy, context, "منوی اصلی:")

# ---------------------- Registration ----------------------
async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    db_exec("UPDATE users SET name=%s WHERE tg_id=%s", (name, update.effective_user.id))
    await update.message.reply_text("شماره تماس؟ (مثلاً 09xxxxxxxxx)")
    return ASK_PHONE

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    db_exec("UPDATE users SET phone=%s WHERE tg_id=%s", (phone, update.effective_user.id))
    await update.message.reply_text("آدرس کامل؟")
    return ASK_ADDRESS

async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    db_exec("UPDATE users SET address=%s, registered=TRUE WHERE tg_id=%s", (address, update.effective_user.id))
    await update.message.reply_text("ثبت‌نام تکمیل شد ✅")
    await send_main_menu(update, context)
    return ConversationHandler.END

# ---------------------- Products: list & order ----------------------
async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    products = db_exec("SELECT * FROM products ORDER BY id DESC")
    if not products:
        await query.message.reply_text("هنوز محصولی ثبت نشده است.", reply_markup=back_menu_kb(is_admin(update)))
        return
    for p in products:
        text = f"#{p['id']} • {p['name']} — {p['price']:,} تومان"
        buttons = [
            InlineKeyboardButton("سفارش 🛒", callback_data=f"order_{p['id']}"),
        ]
        if p.get("photo_id"):
            buttons.append(InlineKeyboardButton("عکس 🖼️", callback_data=f"photo_{p['id']}"))
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup([buttons]))
    await query.message.reply_text("پایان لیست.", reply_markup=back_menu_kb(is_admin(update)))

async def show_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.split("_")[1])
    row = db_exec("SELECT name, photo_id FROM products WHERE id=%s", (pid,))
    if not row or not row[0]["photo_id"]:
        await query.message.reply_text("برای این محصول عکسی ثبت نشده.", reply_markup=back_menu_kb(is_admin(update)))
        return
    await query.message.reply_photo(row[0]["photo_id"], caption=row[0]["name"])

async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.split("_")[1])
    context.user_data["order_pid"] = pid
    await query.message.reply_text("تعداد مورد نظر را بفرستید (عدد).")
    return O_QTY

async def order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty < 1: raise ValueError()
    except:
        await update.message.reply_text("لطفاً فقط عدد معتبر بفرستید.")
        return O_QTY
    context.user_data["order_qty"] = qty
    # انتخاب روش تحویل
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ارسال به آدرس 🛵", callback_data="dlv_send")],
        [InlineKeyboardButton("تحویل حضوری 🏪", callback_data="dlv_pickup")]
    ])
    await update.message.reply_text("نحوه‌ی تحویل را انتخاب کنید:", reply_markup=kb)
    return O_DELIVERY

async def order_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = "delivery" if query.data == "dlv_send" else "pickup"
    pid = context.user_data.get("order_pid")
    qty = context.user_data.get("order_qty", 1)
    # ensure user id
    u = ensure_user(update)
    # create order
    db_exec("INSERT INTO orders(user_id, product_id, qty, delivery_method, status) VALUES(%s,%s,%s,%s,'pending');",
            (u["id"], pid, qty, method))
    await query.message.reply_text("سفارش ثبت شد ✅ (در وضعیت pending)", reply_markup=back_menu_kb(is_admin(update)))
    return ConversationHandler.END

# ---------------------- Wallet ----------------------
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = ensure_user(update)
    text = f"موجودی کیف پول: {u['wallet']:,} تومان"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("درخواست شارژ ➕", callback_data="wallet_topup")]
    ])
    await query.message.reply_text(text, reply_markup=kb)

async def wallet_topup_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("مبلغ شارژ (تومان) را وارد کنید:")
    return W_AMOUNT

async def wallet_topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip())
        if amount <= 0: raise ValueError()
    except:
        await update.message.reply_text("عدد معتبر بفرستید.")
        return W_AMOUNT
    u = ensure_user(update)
    # create payment request
    row = db_exec("INSERT INTO payments(user_id, amount, status) VALUES(%s,%s,'requested') RETURNING id;",
                  (u["id"], amount))
    pid = row[0]["id"]
    await update.message.reply_text("درخواست شارژ ثبت شد. منتظر تایید ادمین باشید ✅")
    # notify admin
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔔 درخواست شارژ کیف پول\nUserID:{u['tg_id']}\nAmount:{amount:,} تومان",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("تایید ✅", callback_data=f"payok_{pid}"),
                InlineKeyboardButton("رد ❌", callback_data=f"payno_{pid}")
            ]])
        )
    except:
        pass
    return ConversationHandler.END

async def admin_pay_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.callback_query.answer("ادمین نیستی")
        return
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split("_")[1])
    pay = db_exec("SELECT * FROM payments WHERE id=%s", (pid,))
    if not pay:
        await q.message.edit_text("یافت نشد.")
        return
    p = pay[0]
    if q.data.startswith("payok_"):
        # approve
        db_exec("UPDATE payments SET status='approved' WHERE id=%s", (pid,))
        db_exec("UPDATE users SET wallet = wallet + %s WHERE id=%s", (p["amount"], p["user_id"]))
        await q.message.edit_text(f"پرداخت #{pid} تایید شد ✅")
    else:
        db_exec("UPDATE payments SET status='rejected' WHERE id=%s", (pid,))
        await q.message.edit_text(f"پرداخت #{pid} رد شد ❌")

# ---------------------- Admin: add/edit product ----------------------
async def admin_add_product_begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.callback_query.answer("ادمین نیستی")
        return ConversationHandler.END
    await update.callback_query.message.reply_text("نام محصول؟")
    return P_NAME

async def admin_add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان)؟")
    return P_PRICE

async def admin_add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
        if price <= 0: raise ValueError()
    except:
        await update.message.reply_text("قیمت عددی معتبر بفرست.")
        return P_PRICE
    context.user_data["p_price"] = price
    await update.message.reply_text("عکس محصول را بفرست یا بنویس «ندارم».")
    return P_PHOTO

async def admin_add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = None
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    else:
        if update.message.text and update.message.text.strip() != "":
            # user typed e.g. "ندارم"
            photo_id = None
    name = context.user_data.get("p_name")
    price = context.user_data.get("p_price")
    db_exec("INSERT INTO products(name, price, photo_id) VALUES(%s,%s,%s)", (name, price, photo_id))
    await update.message.reply_text("محصول ذخیره شد ✅")
    return ConversationHandler.END

# ویرایش
async def admin_edit_product_begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.callback_query.answer("ادمین نیستی")
        return ConversationHandler.END
    prods = db_exec("SELECT id,name FROM products ORDER BY id DESC")
    if not prods:
        await update.callback_query.message.reply_text("محصولی نیست.")
        return ConversationHandler.END
    kb = [[InlineKeyboardButton(f"#{p['id']} {p['name']}", callback_data=f"e_pick_{p['id']}")] for p in prods]
    await update.callback_query.message.reply_text("یک محصول برای ویرایش انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))
    return E_SELECT

async def admin_edit_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = int(update.callback_query.data.split("_")[2])
    context.user_data["edit_pid"] = pid
    await update.callback_query.message.reply_text(
        "چه چیزی را می‌خواهی ویرایش کنی؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("نام", callback_data="e_field_name"),
             InlineKeyboardButton("قیمت", callback_data="e_field_price")],
            [InlineKeyboardButton("عکس", callback_data="e_field_photo")]
        ])
    )
    await update.callback_query.answer()
    return E_FIELD

async def admin_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    fld = update.callback_query.data.split("_")[-1]
    context.user_data["edit_field"] = fld
    if fld == "photo":
        await update.callback_query.message.reply_text("عکس جدید را بفرست.")
        return E_PHOTO
    else:
        await update.callback_query.message.reply_text("مقدار جدید را بفرست.")
        return E_VALUE

async def admin_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.get("edit_pid")
    fld = context.user_data.get("edit_field")
    val = update.message.text.strip()
    if fld == "price":
        try:
            val = int(val)
        except:
            await update.message.reply_text("قیمت باید عدد باشد.")
            return E_VALUE
    db_exec(f"UPDATE products SET {fld}=%s WHERE id=%s", (val, pid))
    await update.message.reply_text("ویرایش انجام شد ✅")
    return ConversationHandler.END

async def admin_edit_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.get("edit_pid")
    if not update.message.photo:
        await update.message.reply_text("لطفاً عکس بفرست.")
        return E_PHOTO
    photo_id = update.message.photo[-1].file_id
    db_exec("UPDATE products SET photo_id=%s WHERE id=%s", (photo_id, pid))
    await update.message.reply_text("عکس بروزرسانی شد ✅")
    return ConversationHandler.END

# ---------------------- Music ----------------------
async def music_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rows = db_exec("SELECT * FROM music ORDER BY id DESC")
    if not rows:
        await query.message.reply_text("هنوز موزیکی ثبت نشده.", reply_markup=back_menu_kb(is_admin(update)))
        return
    for m in rows:
        await query.message.reply_audio(m["file_id"], caption=f"#{m['id']} • {m['title']}")
    await query.message.reply_text("پایان لیست.", reply_markup=back_menu_kb(is_admin(update)))

async def admin_add_music_begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.callback_query.answer("ادمین نیستی")
        return ConversationHandler.END
    await update.callback_query.message.reply_text("عنوان موزیک؟")
    return M_TITLE

async def admin_add_music_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["m_title"] = update.message.text.strip()
    await update.message.reply_text("فایل موزیک را به صورت Audio بفرست.")
    return M_FILE

async def admin_add_music_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.audio:
        await update.message.reply_text("فایل Audio بفرست.")
        return M_FILE
    file_id = update.message.audio.file_id
    title = context.user_data.get("m_title")
    db_exec("INSERT INTO music(title, file_id) VALUES(%s,%s)", (title, file_id))
    await update.message.reply_text("موزیک ذخیره شد ✅")
    return ConversationHandler.END

# ---------------------- Games (placeholder) ----------------------
async def games_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("بخش بازی به‌زودی فعال می‌شود 🎮", reply_markup=back_menu_kb(is_admin(update)))

# ---------------------- Router (buttons) ----------------------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data

    if data == "back_main":
        await back_main(update, context)
    elif data == "menu_products":
        await show_products(update, context)
    elif data.startswith("photo_"):
        await show_photo(update, context)
    elif data.startswith("order_"):
        return await order_start(update, context)
    elif data in ("dlv_send", "dlv_pickup"):
        return await order_delivery(update, context)
    elif data == "wallet":
        await wallet_menu(update, context)
    elif data == "wallet_topup":
        return await wallet_topup_ask(update, context)
    elif data.startswith("payok_") or data.startswith("payno_"):
        await admin_pay_decide(update, context)
    elif data == "admin_add_product":
        return await admin_add_product_begin(update, context)
    elif data == "admin_edit_product":
        return await admin_edit_product_begin(update, context)
    elif data.startswith("e_pick_"):
        return await admin_edit_pick(update, context)
    elif data.startswith("e_field_"):
        return await admin_edit_field(update, context)
    elif data == "music":
        await music_list(update, context)
    elif data == "admin_add_music":
        return await admin_add_music_begin(update, context)
    elif data == "games":
        await games_placeholder(update, context)
    else:
        await update.callback_query.answer("نامشخص", show_alert=True)

# ---------------------- Main ----------------------
def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ثبت نام
    reg = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
        },
        fallbacks=[CommandHandler("start", start)],
        name="registration",
        persistent=False
    )
    app.add_handler(reg)

    # سفارش: تعداد و تحویل
    order_conv = ConversationHandler(
        entry_points=[],
        states={
            O_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_qty)],
            O_DELIVERY: [CallbackQueryHandler(order_delivery, pattern="^(dlv_send|dlv_pickup)$")]
        },
        fallbacks=[CallbackQueryHandler(back_main, pattern="^back_main$")],
        name="order",
        persistent=False
    )
    app.add_handler(order_conv)

    # کیف پول
    wallet_conv = ConversationHandler(
        entry_points=[],
        states={W_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_topup_amount)]},
        fallbacks=[],
        name="wallet",
        persistent=False
    )
    app.add_handler(wallet_conv)

    # افزودن محصول
    add_prod = ConversationHandler(
        entry_points=[],
        states={
            P_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_name)],
            P_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_price)],
            P_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, admin_add_product_photo)],
        },
        fallbacks=[],
        name="add_product",
        persistent=False
    )
    app.add_handler(add_prod)

    # ویرایش محصول
    edit_prod = ConversationHandler(
        entry_points=[],
        states={
            E_SELECT: [CallbackQueryHandler(admin_edit_pick, pattern=r"^e_pick_\d+$")],
            E_FIELD: [CallbackQueryHandler(admin_edit_field, pattern=r"^e_field_(name|price|photo)$")],
            E_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_value)],
            E_PHOTO: [MessageHandler(filters.PHOTO & ~filters.COMMAND, admin_edit_photo)],
        },
        fallbacks=[],
        name="edit_product",
        persistent=False
    )
    app.add_handler(edit_prod)

    # موزیک
    add_music = ConversationHandler(
        entry_points=[],
        states={
            M_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_music_title)],
            M_FILE: [MessageHandler(filters.AUDIO & ~filters.COMMAND, admin_add_music_file)],
        },
        fallbacks=[],
        name="add_music",
        persistent=False
    )
    app.add_handler(add_music)

    # دکمه‌ها
    app.add_handler(CallbackQueryHandler(on_button))

    # دستور start (برای مواقعی که ثبت‌نام تکمیل شده)
    app.add_handler(CommandHandler("start", start))

    return app

async def run():
    init_db()
    app = build_app()
    # Polling مناسب Render Web Service (بدون نیاز به باز کردن پورت)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    # running forever
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(run())
