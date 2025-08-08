import os
import re
import asyncio
from decimal import Decimal

from aiohttp import web
import psycopg2
from psycopg2.extras import RealDictCursor

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto, InputFile
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# ========= ENV =========
TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")

if not TOKEN:
    raise RuntimeError("ENV TELEGRAM_TOKEN/BOT_TOKEN is missing")
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL is missing")

# ========= DB ==========

def db():
    # Neon نیاز به ssl دارد
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    return conn

def run_migrations(conn):
    with conn:
        with conn.cursor() as cur:
            # users
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users(
              id BIGSERIAL PRIMARY KEY,
              tg_id BIGINT UNIQUE,
              name TEXT,
              phone TEXT,
              address TEXT,
              created_at TIMESTAMPTZ DEFAULT NOW()
            );""")
            for col in ("tg_id BIGINT","name TEXT","phone TEXT","address TEXT",
                        "created_at TIMESTAMPTZ DEFAULT NOW()"):
                cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col};")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_tg_id_idx ON users(tg_id);")

            # wallets
            cur.execute("""
            CREATE TABLE IF NOT EXISTS wallets(
              id BIGSERIAL PRIMARY KEY,
              user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
              balance NUMERIC(12,2) NOT NULL DEFAULT 0,
              updated_at TIMESTAMPTZ DEFAULT NOW()
            );""")
            for col in ("user_id BIGINT",
                        "balance NUMERIC(12,2) NOT NULL DEFAULT 0",
                        "updated_at TIMESTAMPTZ DEFAULT NOW()"):
                cur.execute(f"ALTER TABLE wallets ADD COLUMN IF NOT EXISTS {col};")

            # products
            cur.execute("""
            CREATE TABLE IF NOT EXISTS products(
              id BIGSERIAL PRIMARY KEY,
              name TEXT NOT NULL,
              price NUMERIC(12,2) NOT NULL DEFAULT 0,
              description TEXT,
              photo_file_id TEXT,
              is_active BOOLEAN NOT NULL DEFAULT TRUE,
              created_at TIMESTAMPTZ DEFAULT NOW()
            );""")
            for col in ("name TEXT",
                        "price NUMERIC(12,2) NOT NULL DEFAULT 0",
                        "description TEXT",
                        "photo_file_id TEXT",
                        "is_active BOOLEAN NOT NULL DEFAULT TRUE",
                        "created_at TIMESTAMPTZ DEFAULT NOW()"):
                cur.execute(f"ALTER TABLE products ADD COLUMN IF NOT EXISTS {col};")

            cur.execute("""
            CREATE TABLE IF NOT EXISTS product_photos(
              id BIGSERIAL PRIMARY KEY,
              product_id BIGINT REFERENCES products(id) ON DELETE CASCADE,
              file_id TEXT NOT NULL
            );""")
            for col in ("product_id BIGINT", "file_id TEXT"):
                cur.execute(f"ALTER TABLE product_photos ADD COLUMN IF NOT EXISTS {col};")

            # orders
            cur.execute("""
            CREATE TABLE IF NOT EXISTS orders(
              id BIGSERIAL PRIMARY KEY,
              user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
              status TEXT NOT NULL DEFAULT 'draft',
              delivery_method TEXT,
              created_at TIMESTAMPTZ DEFAULT NOW(),
              note TEXT
            );""")
            for col in ("user_id BIGINT",
                        "status TEXT NOT NULL DEFAULT 'draft'",
                        "delivery_method TEXT",
                        "created_at TIMESTAMPTZ DEFAULT NOW()",
                        "note TEXT"):
                cur.execute(f"ALTER TABLE orders ADD COLUMN IF NOT EXISTS {col};")

            # order_items
            cur.execute("""
            CREATE TABLE IF NOT EXISTS order_items(
              id BIGSERIAL PRIMARY KEY,
              order_id BIGINT REFERENCES orders(id) ON DELETE CASCADE,
              product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
              qty INT NOT NULL DEFAULT 1,
              unit_price NUMERIC(12,2) NOT NULL DEFAULT 0
            );""")
            for col in ("order_id BIGINT","product_id BIGINT",
                        "qty INT NOT NULL DEFAULT 1",
                        "unit_price NUMERIC(12,2) NOT NULL DEFAULT 0"):
                cur.execute(f"ALTER TABLE order_items ADD COLUMN IF NOT EXISTS {col};")

            # payments (wallet top-ups)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS payments(
              id BIGSERIAL PRIMARY KEY,
              user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
              amount NUMERIC(12,2) NOT NULL,
              method TEXT NOT NULL DEFAULT 'manual',
              ref TEXT,
              status TEXT NOT NULL DEFAULT 'pending', -- pending/approved/rejected
              created_at TIMESTAMPTZ DEFAULT NOW()
            );""")
            for col in ("user_id BIGINT",
                        "amount NUMERIC(12,2) NOT NULL",
                        "method TEXT NOT NULL DEFAULT 'manual'",
                        "ref TEXT",
                        "status TEXT NOT NULL DEFAULT 'pending'",
                        "created_at TIMESTAMPTZ DEFAULT NOW()"):
                cur.execute(f"ALTER TABLE payments ADD COLUMN IF NOT EXISTS {col};")

            # music
            cur.execute("""
            CREATE TABLE IF NOT EXISTS music(
              id BIGSERIAL PRIMARY KEY,
              title TEXT NOT NULL,
              file_id TEXT NOT NULL,
              created_at TIMESTAMPTZ DEFAULT NOW()
            );""")
            for col in ("title TEXT","file_id TEXT",
                        "created_at TIMESTAMPTZ DEFAULT NOW()"):
                cur.execute(f"ALTER TABLE music ADD COLUMN IF NOT EXISTS {col};")

def ensure_user(tg_id:int, name:str=""):
    with db() as conn, conn.cursor() as cur:
        run_migrations(conn)
        cur.execute("SELECT id,name,phone,address FROM users WHERE tg_id=%s;", (tg_id,))
        row = cur.fetchone()
        if row: return
        cur.execute("INSERT INTO users(tg_id,name) VALUES(%s,%s);", (tg_id, name or ""))

def get_wallet_balance(tg_id:int)->Decimal:
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE tg_id=%s;", (tg_id,))
        u = cur.fetchone()
        if not u: return Decimal("0")
        cur.execute("SELECT balance FROM wallets WHERE user_id=%s;", (u[0],))
        w = cur.fetchone()
        if not w:
            cur.execute("INSERT INTO wallets(user_id,balance) VALUES(%s,0) RETURNING balance;", (u[0],))
            return Decimal("0")
        return w[0]

def add_wallet(tg_id:int, amount:Decimal):
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE tg_id=%s;", (tg_id,))
        u = cur.fetchone()
        if not u: return
        cur.execute("INSERT INTO wallets(user_id,balance) VALUES(%s,0) ON CONFLICT DO NOTHING;", (u[0],))
        cur.execute("UPDATE wallets SET balance=COALESCE(balance,0)+%s, updated_at=NOW() WHERE user_id=%s;",
                    (amount, u[0]))

# ========= UI =========

def main_menu(is_admin: bool):
    rows = [
        [KeyboardButton("منوی محصولات ☕️"), KeyboardButton("کیف پول 💸")],
        [KeyboardButton("اینستاگرام 📲")],
    ]
    if is_admin:
        rows.append([KeyboardButton("افزودن محصول ➕")])
        rows.append([KeyboardButton("موزیک 🎵")])
    else:
        rows.append([KeyboardButton("موزیک 🎵")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ========= Handlers =========

ASK_NAME, ASK_PHONE, ASK_ADDRESS = range(3)
ADD_NAME, ADD_PRICE, ADD_DESC, ADD_PHOTO = range(10,14)
TOPUP_AMOUNT, TOPUP_REF = range(20,22)
MUSIC_WAIT = 30
EDIT_WAIT = 40
EDIT_FIELD, EDIT_VALUE, EDIT_PHOTO = range(41,44)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.full_name or user.username or "")
    # چک پروفایل
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT name,phone,address FROM users WHERE tg_id=%s;", (user.id,))
        name, phone, addr = cur.fetchone()
    if not (name and phone and addr):
        await update.message.reply_text(
            "به بایو کرپ بار خوش اومدی ☕️\nبرای شروع، لطفاً اطلاعاتت رو تکمیل کن.\nاسم و فامیل؟",
            reply_markup=ReplyKeyboardRemove()
        )
        return ASK_NAME

    await update.message.reply_text(
        "به بایو کرپ بار خوش اومدی ☕️\nچطور می‌تونم کمکت کنم؟",
        reply_markup=main_menu(user.id == ADMIN_ID)
    )
    return ConversationHandler.END

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data["name"] = name
    await update.message.reply_text("شماره موبایل؟ (مثلاً 09xxxxxxxxx)")
    return ASK_PHONE

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data["phone"] = phone
    await update.message.reply_text("آدرس کامل؟")
    return ASK_ADDRESS

async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    addr = update.message.text.strip()
    user = update.effective_user
    with db() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE users SET name=%s,phone=%s,address=%s WHERE tg_id=%s;""",
                    (context.user_data["name"], context.user_data["phone"], addr, user.id))
    await update.message.reply_text("اطلاعات ذخیره شد ✅", reply_markup=main_menu(user.id==ADMIN_ID))
    return ConversationHandler.END

# ---- Products ----

def list_products_keyboard(rows):
    # rows: [(id,name,price,has_photo)]
    buttons = []
    for pid, name, price, has_photo in rows:
        cap = f"{name} — {price:.0f} تومان"
        row_btns = [InlineKeyboardButton(cap, callback_data=f"p.show.{pid}")]
        if has_photo:
            row_btns.append(InlineKeyboardButton("🖼️ عکس", callback_data=f"p.photo.{pid}"))
        buttons.append(row_btns)
    return InlineKeyboardMarkup(buttons)

async def products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id,name,price,(photo_file_id IS NOT NULL) AS hp
                       FROM products WHERE is_active=TRUE ORDER BY id DESC LIMIT 50;""")
        rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.", reply_markup=main_menu(update.effective_user.id==ADMIN_ID))
        return
    await update.message.reply_text("منوی محصولات:", reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text(
        "برای دیدن عکس روی دکمه «🖼️ عکس» بزن.",
        reply_markup=list_products_keyboard(rows)
    )

async def cb_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.split(".")
    action, pid = data[1], int(data[2])
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM products WHERE id=%s;", (pid,))
        p = cur.fetchone()
    if not p:
        await q.edit_message_text("محصول پیدا نشد.")
        return
    if action == "photo":
        if p["photo_file_id"]:
            await q.message.reply_photo(p["photo_file_id"], caption=f"{p['name']} — {int(p['price'])} تومان")
        else:
            await q.edit_message_text("عکسی برای این محصول ثبت نشده.")
    elif action == "show":
        text = f"☕️ {p['name']}\nقیمت: {int(p['price'])} تومان"
        if p.get("description"):
            text += f"\n\n{p['description']}"
        kb = []
        if p["photo_file_id"]:
            kb.append([InlineKeyboardButton("🖼️ عکس", callback_data=f"p.photo.{pid}")])
        if update.effective_user.id == ADMIN_ID:
            kb.append([InlineKeyboardButton("✏️ ویرایش", callback_data=f"p.edit.{pid}")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb or [[]]))
    elif action == "edit":
        if update.effective_user.id != ADMIN_ID:
            await q.edit_message_text("دسترسی ندارید.")
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("نام", callback_data=f"e.name.{pid}"),
             InlineKeyboardButton("قیمت", callback_data=f"e.price.{pid}")],
            [InlineKeyboardButton("توضیح", callback_data=f"e.desc.{pid}"),
             InlineKeyboardButton("عکس", callback_data=f"e.photo.{pid}")],
            [InlineKeyboardButton(("🔕 غیر‌فعال" if p["is_active"] else "🔔 فعال"), callback_data=f"e.toggle.{pid}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"e.delete.{pid}")]
        ])
        await q.edit_message_text(f"ویرایش {p['name']}", reply_markup=kb)

async def cb_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    typ, field, pid = q.data.split(".")
    pid = int(pid)
    context.user_data["edit_pid"] = pid
    if field == "toggle":
        with db() as conn, conn.cursor() as cur:
            cur.execute("UPDATE products SET is_active = NOT is_active WHERE id=%s RETURNING is_active;", (pid,))
            new = cur.fetchone()[0]
        await q.edit_message_text("وضعیت محصول: " + ("فعال ✅" if new else "غیرفعال ⛔️"))
        return
    if field == "delete":
        with db() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM products WHERE id=%s;", (pid,))
        await q.edit_message_text("محصول حذف شد.")
        return
    context.user_data["edit_field"] = field
    if field == "photo":
        await q.edit_message_text("عکس جدید را بفرستید.")
        return EDIT_PHOTO
    prompt = {"name":"نام جدید؟","price":"قیمت جدید؟ (تومان عدد)","desc":"توضیح جدید؟"}.get(field,"مقدار جدید؟")
    await q.edit_message_text(prompt)
    return EDIT_VALUE

async def edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.get("edit_pid")
    field = context.user_data.get("edit_field")
    val = update.message.text.strip()
    with db() as conn, conn.cursor() as cur:
        if field == "price":
            val = Decimal(re.sub(r"[^\d]", "", val) or "0")
            cur.execute("UPDATE products SET price=%s WHERE id=%s;", (val, pid))
        elif field == "name":
            cur.execute("UPDATE products SET name=%s WHERE id=%s;", (val, pid))
        elif field == "desc":
            cur.execute("UPDATE products SET description=%s WHERE id=%s;", (val, pid))
    await update.message.reply_text("ذخیره شد ✅")
    return ConversationHandler.END

async def edit_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.get("edit_pid")
    if not update.message.photo:
        await update.message.reply_text("لطفاً عکس بفرستید.")
        return EDIT_PHOTO
    fid = update.message.photo[-1].file_id
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE products SET photo_file_id=%s WHERE id=%s;", (fid, pid))
    await update.message.reply_text("عکس ذخیره شد ✅")
    return ConversationHandler.END

# ---- Add product (admin) ----

async def add_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("فقط ادمین!")
        return ConversationHandler.END
    await update.message.reply_text("نام محصول؟", reply_markup=ReplyKeyboardRemove())
    return ADD_NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت (تومان عدد)؟")
    return ADD_PRICE

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    num = re.sub(r"[^\d]", "", update.message.text or "")
    if not num:
        await update.message.reply_text("فقط عدد بفرست.")
        return ADD_PRICE
    context.user_data["p_price"] = Decimal(num)
    await update.message.reply_text("توضیحات کوتاه (اختیاری). اگر نمی‌خوای «-» بفرست.")
    return ADD_DESC

async def add_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = update.message.text.strip()
    context.user_data["p_desc"] = ("" if d == "-" else d)
    await update.message.reply_text("حالا عکس محصول رو ارسال کن (اختیاری). اگر عکس نداری «-» بفرست.")
    return ADD_PHOTO

async def add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fid = None
    if update.message.text and update.message.text.strip() == "-":
        fid = None
    elif update.message.photo:
        fid = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("یا عکس بفرست یا «-»")
        return ADD_PHOTO

    with db() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO products(name,price,description,photo_file_id,is_active)
                       VALUES(%s,%s,%s,%s,TRUE) RETURNING id;""",
                    (context.user_data["p_name"], context.user_data["p_price"],
                     context.user_data["p_desc"], fid))
        pid = cur.fetchone()[0]
    await update.message.reply_text(f"محصول با موفقیت ثبت شد ✅ (ID: {pid})",
                                    reply_markup=main_menu(update.effective_user.id==ADMIN_ID))
    return ConversationHandler.END

# ---- Wallet / Top-up ----

async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = get_wallet_balance(update.effective_user.id)
    kb = ReplyKeyboardMarkup([[KeyboardButton("درخواست شارژ 💳")],
                              [KeyboardButton("برگشت ⬅️")]], resize_keyboard=True)
    await update.message.reply_text(f"موجودی کیف پول: {int(bal)} تومان", reply_markup=kb)

async def wallet_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if txt == "درخواست شارژ 💳":
        await update.message.reply_text("مبلغ شارژ (تومان)؟", reply_markup=ReplyKeyboardRemove())
        return TOPUP_AMOUNT
    if txt == "برگشت ⬅️":
        await start(update, context)
        return ConversationHandler.END

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    num = re.sub(r"[^\d]", "", update.message.text or "")
    if not num:
        await update.message.reply_text("فقط عدد بفرست.")
        return TOPUP_AMOUNT
    context.user_data["topup_amount"] = Decimal(num)
    await update.message.reply_text("کد پیگیری/رسید کارت‌به‌کارت رو بفرست (یا عکس رسید).")
    return TOPUP_REF

async def topup_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ref = None
    if update.message.text:
        ref = update.message.text.strip()
    elif update.message.photo:
        ref = update.message.photo[-1].file_id  # فایل آیدی رسید
    amount = context.user_data["topup_amount"]

    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE tg_id=%s;", (user.id,))
        uid = cur.fetchone()[0]
        cur.execute("""INSERT INTO payments(user_id,amount,method,ref,status)
                       VALUES(%s,%s,'manual',%s,'pending') RETURNING id;""", (uid, amount, ref))
        pay_id = cur.fetchone()[0]

    # اعلان به ادمین
    if ADMIN_ID:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("تأیید ✅", callback_data=f"pay.ok.{pay_id}.{user.id}.{amount}"),
             InlineKeyboardButton("رد ❌", callback_data=f"pay.no.{pay_id}.{user.id}")]
        ])
        await context.bot.send_message(
            ADMIN_ID,
            f"درخواست شارژ از @{user.username or user.id}\nمبلغ: {int(amount)}\nکد/رسید: {ref}",
            reply_markup=keyboard
        )

    await update.message.reply_text("درخواست ثبت شد. پس از تأیید ادمین، کیف‌پولت شارژ میشه ✅",
                                    reply_markup=main_menu(user.id==ADMIN_ID))
    return ConversationHandler.END

async def cb_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, action, pay_id, tg_id, *rest = q.data.split(".")
    pay_id = int(pay_id); tg_id = int(tg_id)
    if update.effective_user.id != ADMIN_ID:
        await q.edit_message_text("فقط ادمین.")
        return
    with db() as conn, conn.cursor() as cur:
        if action == "ok":
            amount = Decimal(rest[0])
            cur.execute("UPDATE payments SET status='approved' WHERE id=%s;", (pay_id,))
            conn.commit()
            add_wallet(tg_id, amount)
            await context.bot.send_message(tg_id, f"شارژ {int(amount)} تومان تأیید شد ✅")
            await q.edit_message_text("تأیید شد و به کیف پول واریز گردید.")
        else:
            cur.execute("UPDATE payments SET status='rejected' WHERE id=%s;", (pay_id,))
            await context.bot.send_message(tg_id, "درخواست شارژ رد شد ❌")
            await q.edit_message_text("رد شد.")

# ---- Music ----

async def music_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("برای افزودن موزیک، فایل صوتی را بفرستید و عنوان را در کپشن بنویسید.\n"
                                        "برای دیدن لیست، بنویس: لیست موزیک")
        return MUSIC_WAIT
    # کاربر عادی -> فهرست
    await list_music(update, context)
    return ConversationHandler.END

async def music_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    if update.message.text and update.message.text.strip() == "لیست موزیک":
        await list_music(update, context)
        return MUSIC_WAIT
    if not update.message.audio:
        await update.message.reply_text("فایل صوتی بفرست و عنوان را در کپشن بنویس.")
        return MUSIC_WAIT
    title = (update.message.caption or "بدون عنوان").strip()
    fid = update.message.audio.file_id
    with db() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO music(title,file_id) VALUES(%s,%s);", (title, fid))
    await update.message.reply_text("موزیک ذخیره شد ✅")
    return MUSIC_WAIT

async def list_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id,title,file_id FROM music ORDER BY id DESC LIMIT 20;")
        rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("هنوز موزیکی ثبت نشده.")
        return
    await update.message.reply_text("🎵 پلی‌لیست کافه:")
    for mid, title, fid in rows:
        await update.message.reply_audio(fid, caption=title)

# ========= dispatcher =========

def build_application() -> Application:
    app = Application.builder().token(TOKEN).build()

    # /start + تکمیل پروفایل
    profile_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
        },
        fallbacks=[CommandHandler("start", start)],
        name="profile_conv",
        persistent=False,
    )

    # افزودن محصول (ادمین)
    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن محصول ➕$"), add_product_entry)],
        states={
            ADD_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
            ADD_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_desc)],
            ADD_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, add_photo)],
        },
        fallbacks=[CommandHandler("start", start)],
        name="add_product",
        persistent=False,
    )

    # ویرایش محصول (callback)
    app.add_handler(CallbackQueryHandler(cb_products, pattern=r"^p\.(show|photo|edit)\.\d+$"))
    app.add_handler(CallbackQueryHandler(cb_edit, pattern=r"^e\.(name|price|desc|photo|toggle|delete)\.\d+$"))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.PRIVATE, edit_value), group=1)
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, edit_photo), group=2)

    # لیست محصولات
    app.add_handler(MessageHandler(filters.Regex("^منوی محصولات ☕️$"), products_menu))

    # کیف پول
    wallet_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^کیف پول 💸$"), wallet_menu)],
        states={
            TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
            TOPUP_REF:    [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, topup_ref)],
        },
        fallbacks=[CommandHandler("start", start),
                   MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_buttons)],
        name="wallet",
        persistent=False,
    )
    app.add_handler(wallet_conv)
    app.add_handler(CallbackQueryHandler(cb_payment, pattern=r"^pay\.(ok|no)\.\d+\.\d+(\.\d+)?$"))

    # موزیک
    music_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^موزیک 🎵$"), music_menu)],
        states={MUSIC_WAIT: [MessageHandler((filters.AUDIO | filters.TEXT) & ~filters.COMMAND, music_admin)]},
        fallbacks=[CommandHandler("start", start)],
        name="music",
        persistent=False,
    )
    app.add_handler(music_conv)

    # دکمه اینستاگرام
    async def insta(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("اینستاگرام: https://instagram.com/yourpage")
    app.add_handler(MessageHandler(filters.Regex("^اینستاگرام 📲$"), insta))

    # دکمه برگشت
    async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await start(update, context)
    app.add_handler(MessageHandler(filters.Regex("^برگشت ⬅️$"), go_back))

    # Conflict safety: پاسخ به /whoami برای تست
    async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(str(update.effective_user.id))
    app.add_handler(CommandHandler("whoami", whoami))

    # پرداخت conflict logs یا هر پیام دیگر نادیده
    return app

# ========= tiny HTTP server to satisfy Render port scan =========
async def health(request):
    return web.Response(text="ok")

async def start_http_server():
    app = web.Application()
    app.add_routes([web.get("/", health), web.get("/health", health)])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ========= main =========
async def main():
    # warmup & migrations
    with db() as conn:
        run_migrations(conn)

    # start http server (for Render) + start bot polling
    await start_http_server()

    application = build_application()
    # drop_pending_updates برای جلوگیری از ارور Conflict در ابتدای اجرا
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    # wait forever
    await application.updater.wait()
    await application.stop()
    await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
