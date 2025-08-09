# -*- coding: utf-8 -*-
# Bio Crepebar Bot – Final
# PTB v20, Polling (no web server). Neon Postgres. Persian UI.

import os
import logging
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Dict, Any, Optional

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

import psycopg2
from psycopg2 import sql as psql

# ----------------- Config & Logging -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "****-****-****-****")

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL is missing")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("crepebar")

# ----------------- DB Helpers & Auto-Migrations -----------------
def _connect():
    return psycopg2.connect(DATABASE_URL)

def db_execute(query: str, params: Optional[tuple] = None, fetch: str = "none"):
    """fetch: none|one|all -> returns result accordingly"""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
        conn.commit()

def table_exists(name: str) -> bool:
    q = """
    SELECT 1 FROM information_schema.tables WHERE table_name=%s
    """
    return bool(db_execute(q, (name,), "one"))

def column_exists(table: str, col: str) -> bool:
    q = """
    SELECT 1 FROM information_schema.columns
    WHERE table_name=%s AND column_name=%s
    """
    return bool(db_execute(q, (table, col), "one"))

def run_migrations():
    # users
    db_execute("""
    CREATE TABLE IF NOT EXISTS users(
      id SERIAL PRIMARY KEY,
      tg_id BIGINT UNIQUE NOT NULL,
      name TEXT,
      phone TEXT,
      address TEXT,
      created_at TIMESTAMPTZ DEFAULT now()
    );
    """)
    if not column_exists("users", "id"):
        db_execute("ALTER TABLE users ADD COLUMN id SERIAL PRIMARY KEY;")
    if not column_exists("users", "tg_id"):
        db_execute("ALTER TABLE users ADD COLUMN tg_id BIGINT UNIQUE;")
    db_execute("CREATE INDEX IF NOT EXISTS idx_users_tg_id ON users(tg_id);")

    # wallets
    db_execute("""
    CREATE TABLE IF NOT EXISTS wallets(
      id SERIAL PRIMARY KEY,
      user_id INT UNIQUE REFERENCES users(id) ON DELETE CASCADE,
      balance NUMERIC(12,2) DEFAULT 0
    );
    """)

    # products
    db_execute("""
    CREATE TABLE IF NOT EXISTS products(
      id SERIAL PRIMARY KEY,
      name TEXT NOT NULL,
      price NUMERIC(12,2) NOT NULL,
      description TEXT,
      img_file_id TEXT,
      is_active BOOLEAN DEFAULT TRUE,
      created_at TIMESTAMPTZ DEFAULT now()
    );
    """)
    # product images gallery
    db_execute("""
    CREATE TABLE IF NOT EXISTS product_images(
      id SERIAL PRIMARY KEY,
      product_id INT REFERENCES products(id) ON DELETE CASCADE,
      file_id TEXT NOT NULL
    );
    """)

    # orders & items
    db_execute("""
    CREATE TABLE IF NOT EXISTS orders(
      id SERIAL PRIMARY KEY,
      user_id INT REFERENCES users(id) ON DELETE SET NULL,
      status TEXT DEFAULT 'draft', -- draft/awaiting_confirm/paid/cancelled
      total NUMERIC(12,2) DEFAULT 0,
      delivery_method TEXT, -- pickup/delivery
      address TEXT,
      created_at TIMESTAMPTZ DEFAULT now()
    );
    """)
    db_execute("""
    CREATE TABLE IF NOT EXISTS order_items(
      id SERIAL PRIMARY KEY,
      order_id INT REFERENCES orders(id) ON DELETE CASCADE,
      product_id INT REFERENCES products(id) ON DELETE SET NULL,
      qty INT NOT NULL DEFAULT 1,
      unit_price NUMERIC(12,2) NOT NULL
    );
    """)
    # topups (wallet charge requests)
    db_execute("""
    CREATE TABLE IF NOT EXISTS topups(
      id SERIAL PRIMARY KEY,
      user_id INT REFERENCES users(id) ON DELETE CASCADE,
      amount NUMERIC(12,2) NOT NULL,
      status TEXT DEFAULT 'pending', -- pending/approved/rejected
      created_at TIMESTAMPTZ DEFAULT now()
    );
    """)

    # music
    db_execute("""
    CREATE TABLE IF NOT EXISTS music(
      id SERIAL PRIMARY KEY,
      title TEXT,
      file_id TEXT NOT NULL,
      uploaded_by INT REFERENCES users(id) ON DELETE SET NULL,
      created_at TIMESTAMPTZ DEFAULT now()
    );
    """)

    # indexes / FKs refresh
    try:
        db_execute("""
        ALTER TABLE wallets
        DROP CONSTRAINT IF EXISTS wallets_user_id_fkey,
        ADD CONSTRAINT wallets_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        """)
        db_execute("""
        ALTER TABLE orders
        DROP CONSTRAINT IF EXISTS orders_user_id_fkey,
        ADD CONSTRAINT orders_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
        """)
    except Exception as e:
        log.info("FK refresh skipped: %s", e)

run_migrations()

# ----------------- Utilities -----------------
MAIN_BTNS_USER = [
    [KeyboardButton("منوی محصولات ☕️"), KeyboardButton("کیف پول 💸")],
    [KeyboardButton("موزیک‌های کافه 🎵"), KeyboardButton("بازی 🎮")],
    [KeyboardButton("اینستاگرام 📲")],
]
MAIN_BTNS_ADMIN = MAIN_BTNS_USER + [[KeyboardButton("➕ افزودن محصول")]]

def main_kb(is_admin: bool):
    return ReplyKeyboardMarkup(
        MAIN_BTNS_ADMIN if is_admin else MAIN_BTNS_USER,
        resize_keyboard=True
    )

def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and update.effective_user.id == ADMIN_ID:
            return await func(update, context)
        await update.effective_message.reply_text("⛔️ فقط مدیر اجازه‌ی این کار را دارد.")
    return wrapper

def get_user_row(tg_id: int):
    row = db_execute("SELECT id, name, phone, address FROM users WHERE tg_id=%s", (tg_id,), "one")
    if not row:
        db_execute("INSERT INTO users(tg_id) VALUES(%s)", (tg_id,))
        # ایجاد کیف پول صفر
        uid = db_execute("SELECT id FROM users WHERE tg_id=%s", (tg_id,), "one")[0]
        db_execute("INSERT INTO wallets(user_id, balance) VALUES(%s, 0) ON CONFLICT DO NOTHING", (uid,))
        row = (uid, None, None, None)
    return row

def set_profile_field(tg_id: int, field: str, value: str):
    db_execute(psql.SQL("UPDATE users SET {}=%s WHERE tg_id=%s").format(psql.Identifier(field)), (value, tg_id))

# ----------------- State Machine (lightweight) -----------------
STATE: Dict[int, Dict[str, Any]] = {}  # user_id -> {mode, data}

def set_state(uid: int, mode: Optional[str], **data):
    if mode is None:
        STATE.pop(uid, None)
    else:
        STATE[uid] = {"mode": mode, "data": data}

def get_state(uid: int) -> Optional[Dict[str, Any]]:
    return STATE.get(uid)

# ----------------- Handlers -----------------
async def post_init(app: Application):
    # برای جلوگیری از Conflict با وب‌هوک قدیمی
    await app.bot.delete_webhook(drop_pending_updates=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    row = get_user_row(uid)
    # تکمیل پروفایل
    missing = []
    if not row[1]: missing.append("نام")
    if not row[2]: missing.append("شماره تماس")
    if not row[3]: missing.append("آدرس")
    welcome = "به بایو کرپ بار خوش آمدی ☕️\n"
    if missing:
        welcome += f"برای ادامه، لطفاً {', '.join(missing)} را تکمیل کن."
        await update.message.reply_text(welcome, reply_markup=main_kb(uid == ADMIN_ID))
        # بلافاصله از نام شروع می‌کنیم
        if not row[1]:
            set_state(uid, "ask_name")
            return await update.message.reply_text("نام و نام‌خانوادگی:")
        if not row[2]:
            set_state(uid, "ask_phone")
            return await update.message.reply_text("شماره تماس:")
        if not row[3]:
            set_state(uid, "ask_address")
            return await update.message.reply_text("آدرس:")
    else:
        await update.message.reply_text("چطور می‌تونم کمکت کنم؟", reply_markup=main_kb(uid == ADMIN_ID))

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()

    # اگر در حالت جمع‌آوری اطلاعات/افزودن محصول هستیم:
    st = get_state(uid)
    if st:
        mode = st["mode"]
        data = st["data"]
        if mode == "ask_name":
            set_profile_field(uid, "name", text)
            set_state(uid, "ask_phone")
            return await update.message.reply_text("شماره تماس:")
        if mode == "ask_phone":
            set_profile_field(uid, "phone", text)
            set_state(uid, "ask_address")
            return await update.message.reply_text("آدرس:")
        if mode == "ask_address":
            set_profile_field(uid, "address", text)
            set_state(uid, None)
            return await update.message.reply_text("پروفایل تکمیل شد ✅", reply_markup=main_kb(uid == ADMIN_ID))

        if mode == "add_product_name":
            data["name"] = text
            set_state(uid, "add_product_price", **data)
            return await update.message.reply_text("قیمت (تومان):")
        if mode == "add_product_price":
            try:
                price = Decimal(text)
            except InvalidOperation:
                return await update.message.reply_text("قیمت عددی وارد کن.")
            data["price"] = price
            set_state(uid, "add_product_desc", **data)
            return await update.message.reply_text("توضیح کوتاه (اختیاری، می‌تونی خط تیره بذاری):")
        if mode == "add_product_desc":
            data["description"] = None if text == "-" else text
            set_state(uid, "add_product_photo", **data)
            return await update.message.reply_text("لطفاً عکس محصول را ارسال کن 📷")
        if mode == "order_qty":
            try:
                qty = int(text)
                if qty <= 0: raise ValueError
            except Exception:
                return await update.message.reply_text("تعداد معتبر نیست. یک عدد مثبت بفرست.")
            # ایجاد سفارش
            pid = data["product_id"]
            prod = db_execute("SELECT id, name, price, img_file_id FROM products WHERE id=%s", (pid,), "one")
            urow = get_user_row(uid)
            db_execute("""
              INSERT INTO orders(user_id, status, total)
              VALUES (%s, 'draft', 0)
            """, (urow[0],))
            order_id = db_execute("SELECT id FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT 1", (urow[0],), "one")[0]
            db_execute("""
              INSERT INTO order_items(order_id, product_id, qty, unit_price)
              VALUES (%s, %s, %s, %s)
            """, (order_id, prod[0], qty, prod[2]))
            # محاسبه total
            total = db_execute("""
              SELECT COALESCE(SUM(qty*unit_price),0) FROM order_items WHERE order_id=%s
            """, (order_id,), "one")[0]
            db_execute("UPDATE orders SET total=%s WHERE id=%s", (total, order_id))
            set_state(uid, "order_delivery", order_id=order_id)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("تحویل حضوری", callback_data=f"deliv:pickup:{order_id}")],
                [InlineKeyboardButton("ارسال پیک", callback_data=f"deliv:delivery:{order_id}")]
            ])
            return await update.message.reply_text(
                f"✅ سفارش اولیه ثبت شد. مبلغ کل: {int(total)} تومان\nروش تحویل را انتخاب کن:",
                reply_markup=kb
            )
        if mode == "wallet_request":
            try:
                amount = Decimal(text)
                if amount <= 0: raise ValueError
            except Exception:
                return await update.message.reply_text("مبلغ معتبر نیست.")
            urow = get_user_row(uid)
            db_execute("INSERT INTO topups(user_id, amount, status) VALUES(%s,%s,'pending')", (urow[0], amount))
            set_state(uid, None)
            await update.message.reply_text(
                f"درخواست شارژ {int(amount)} تومان ثبت شد. لطفاً کارت‌به‌کارت کن:\n💳 {PAYMENT_CARD}\n"
                f"و رسید/چهار رقم آخر رو بفرست تا تایید بشه.",
            )
            # اطلاع به ادمین
            tid = db_execute("SELECT id FROM topups WHERE user_id=%s ORDER BY id DESC LIMIT 1", (urow[0],), "one")[0]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("تایید شارژ ✅", callback_data=f"topok:{tid}")],
                [InlineKeyboardButton("رد ❌", callback_data=f"toprej:{tid}")]
            ])
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"درخواست شارژ #{tid}\nUser {uid} مبلغ: {int(amount)}",
                reply_markup=kb
            )
            return

    # دکمه‌های منو
    if text == "منوی محصولات ☕️":
        prods = db_execute("SELECT id, name, price, is_active FROM products ORDER BY id DESC", fetch="all")
        if not prods:
            return await update.message.reply_text("هنوز محصولی ثبت نشده.")
        buttons = []
        lines = []
        for pid, name, price, active in prods:
            if not active: continue
            lines.append(f"#{pid} • {name} — {int(price)} تومان")
            buttons.append([InlineKeyboardButton(f"مشاهده/سفارش: {name}", callback_data=f"p:{pid}")])
        await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))
        return

    if text == "کیف پول 💸":
        urow = get_user_row(uid)
        bal = db_execute("SELECT balance FROM wallets WHERE user_id=%s", (urow[0],), "one")[0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("درخواست شارژ", callback_data="wallet:charge")],
        ])
        return await update.message.reply_text(f"موجودی کیف پول: {int(bal)} تومان", reply_markup=kb)

    if text == "اینستاگرام 📲":
        return await update.message.reply_text("instagram.com/bio_crepebar (لینک نمونه)")

    if text == "موزیک‌های کافه 🎵":
        items = db_execute("SELECT id, title FROM music ORDER BY id DESC", fetch="all")
        kb_rows = [[InlineKeyboardButton(title or f"Track #{mid}", callback_data=f"m:{mid}")] for mid, title in items] or []
        admin_row = [[InlineKeyboardButton("➕ افزودن موزیک (ادمین)", callback_data="m:add")]] if uid == ADMIN_ID else []
        return await update.message.reply_text("لیست موزیک‌ها:", reply_markup=InlineKeyboardMarkup(kb_rows + admin_row))

    if text == "بازی 🎮":
        return await update.message.reply_text("بخش بازی به‌زودی فعال می‌شود. 🎮🏆")

    if text == "➕ افزودن محصول":
        if uid != ADMIN_ID:
            return await update.message.reply_text("⛔️ فقط مدیر اجازه‌ی این کار را دارد.")
        set_state(uid, "add_product_name")
        return await update.message.reply_text("نام محصول؟")

    # ورودی آزاد: اگر هیچکدام نبود
    await update.message.reply_text("یک گزینه از منو انتخاب کن.", reply_markup=main_kb(uid == ADMIN_ID))

# عکس محصول در مرحله افزودن / ویرایش
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = get_state(uid)
    if not st:
        return
    mode = st["mode"]
    data = st["data"]
    if mode == "add_product_photo":
        file_id = update.message.photo[-1].file_id
        name = data["name"]
        price = data["price"]
        desc = data.get("description")
        db_execute(
            "INSERT INTO products(name, price, description, img_file_id, is_active) VALUES(%s,%s,%s,%s,TRUE)",
            (name, price, desc, file_id)
        )
        pid = db_execute("SELECT id FROM products ORDER BY id DESC LIMIT 1", fetch="one")[0]
        # به گالری هم ثبت کنیم
        db_execute("INSERT INTO product_images(product_id, file_id) VALUES(%s,%s)", (pid, file_id))
        set_state(uid, None)
        return await update.message.reply_text("✅ محصول ثبت شد.", reply_markup=main_kb(uid == ADMIN_ID))
    if mode == "edit_photo":
        pid = data["pid"]
        file_id = update.message.photo[-1].file_id
        db_execute("UPDATE products SET img_file_id=%s WHERE id=%s", (file_id, pid))
        db_execute("INSERT INTO product_images(product_id, file_id) VALUES(%s,%s)", (pid, file_id))
        set_state(uid, None)
        return await update.message.reply_text("✅ عکس محصول به‌روز شد.")

# کال‌بک‌ها
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    # محصول
    if data.startswith("p:"):
        pid = int(data.split(":")[1])
        row = db_execute("SELECT id, name, price, description, img_file_id FROM products WHERE id=%s", (pid,), "one")
        if not row:
            return await q.edit_message_text("محصول پیدا نشد.")
        pid, name, price, desc, img = row
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("سفارش", callback_data=f"order:{pid}")],
            [InlineKeyboardButton("عکس‌های بیشتر", callback_data=f"pgal:{pid}")]
        ] + ([[InlineKeyboardButton("ویرایش (ادمین)", callback_data=f"edit:{pid}")]] if uid == ADMIN_ID else [])
        if img:
            try:
                await q.message.reply_photo(photo=img, caption=f"{name}\n{int(price)} تومان\n{desc or ''}", reply_markup=kb)
            except Exception:
                await q.edit_message_text(f"{name}\n{int(price)} تومان\n{desc or ''}", reply_markup=kb)
        else:
            await q.edit_message_text(f"{name}\n{int(price)} تومان\n{desc or ''}", reply_markup=kb)
        return

    if data.startswith("pgal:"):
        pid = int(data.split(":")[1])
        imgs = db_execute("SELECT file_id FROM product_images WHERE product_id=%s ORDER BY id DESC LIMIT 10", (pid,), "all")
        if not imgs:
            return await q.edit_message_text("گالری خالی است.")
        media = [InputMediaPhoto(i[0]) for i in imgs]
        return await q.message.reply_media_group(media)

    if data.startswith("order:"):
        pid = int(data.split(":")[1])
        set_state(uid, "order_qty", product_id=pid)
        return await q.edit_message_text("تعداد مورد نظر را بفرست:")

    if data.startswith("deliv:"):
        _, method, order_id = data.split(":")
        order_id = int(order_id)
        addr = db_execute("SELECT address FROM users WHERE tg_id=%s", (uid,), "one")[0]
        if method == "delivery" and not addr:
            set_state(uid, "ask_address")
            return await q.edit_message_text("برای ارسال، لطفاً آدرس را بفرست:")
        db_execute("UPDATE orders SET delivery_method=%s WHERE id=%s", (method, order_id))
        # پرداخت کارت به کارت
        db_execute("UPDATE orders SET status='awaiting_confirm' WHERE id=%s", (order_id,))
        total = db_execute("SELECT total FROM orders WHERE id=%s", (order_id,), "one")[0]
        await q.edit_message_text(
            f"✅ سفارش ثبت شد.\nمبلغ قابل پرداخت: {int(total)} تومان\n"
            f"لطفاً به کارت زیر واریز کن و رسید/چهار رقم آخر رو بفرست:\n💳 {PAYMENT_CARD}\n"
            f"پس از تایید، سفارش نهایی می‌شود."
        )
        # اطلاع به ادمین
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("تایید پرداخت ✅", callback_data=f"ordok:{order_id}")],
            [InlineKeyboardButton("رد سفارش ❌", callback_data=f"ordrej:{order_id}")]
        ])
        await context.bot.send_message(ADMIN_ID, f"سفارش #{order_id} از کاربر {uid} منتظر تایید پرداخت است.", reply_markup=kb)
        return

    # ادمین: تایید/رد سفارش
    if data.startswith("ordok:"):
        oid = int(data.split(":")[1])
        db_execute("UPDATE orders SET status='paid' WHERE id=%s", (oid,))
        await q.edit_message_text(f"سفارش #{oid} تایید شد ✅")
        # پیام به کاربر
        u = db_execute("SELECT user_id FROM orders WHERE id=%s", (oid,), "one")[0]
        tid = db_execute("SELECT tg_id FROM users WHERE id=%s", (u,), "one")[0]
        await context.bot.send_message(tid, f"سفارش #{oid} تایید شد ✅. ممنونیم! ☕️")
        return
    if data.startswith("ordrej:"):
        oid = int(data.split(":")[1])
        db_execute("UPDATE orders SET status='cancelled' WHERE id=%s", (oid,))
        await q.edit_message_text(f"سفارش #{oid} رد شد ❌")
        u = db_execute("SELECT user_id FROM orders WHERE id=%s", (oid,), "one")[0]
        tid = db_execute("SELECT tg_id FROM users WHERE id=%s", (u,), "one")[0]
        await context.bot.send_message(tid, f"سفارش #{oid} رد شد. برای راهنمایی به ما پیام بده.")
        return

    # کیف پول
    if data == "wallet:charge":
        set_state(uid, "wallet_request")
        return await q.edit_message_text("مبلغ شارژ را بنویس:")
    if data.startswith("topok:"):
        tid = int(data.split(":")[1])
        row = db_execute("SELECT user_id, amount FROM topups WHERE id=%s", (tid,), "one")
        if not row: return await q.edit_message_text("یافت نشد.")
        user_id, amount = row
        db_execute("UPDATE topups SET status='approved' WHERE id=%s", (tid,))
        db_execute("UPDATE wallets SET balance = balance + %s WHERE user_id=%s", (amount, user_id))
        await q.edit_message_text(f"Topup #{tid} تایید شد.")
        tg = db_execute("SELECT tg_id FROM users WHERE id=%s", (user_id,), "one")[0]
        await context.bot.send_message(tg, f"شارژ کیف پول به مبلغ {int(amount)} تومان تایید شد ✅")
        return
    if data.startswith("toprej:"):
        tid = int(data.split(":")[1])
        db_execute("UPDATE topups SET status='rejected' WHERE id=%s", (tid,))
        await q.edit_message_text(f"Topup #{tid} رد شد ❌")
        return

    # موزیک
    if data == "m:add":
        if uid != ADMIN_ID:
            return await q.edit_message_text("فقط ادمین.")
        set_state(uid, "music_wait")
        return await q.edit_message_text("فایل موزیک را به‌صورت Audio بفرست و در کپشن عنوان را بنویس.")
    if data.startswith("m:"):
        mid = int(data.split(":")[1])
        row = db_execute("SELECT title, file_id FROM music WHERE id=%s", (mid,), "one")
        if not row: return await q.edit_message_text("یافت نشد.")
        title, fid = row
        try:
            await q.message.reply_audio(audio=fid, caption=title or "")
        except Exception:
            await q.edit_message_text(title or "Track")
        return

    # ادمین: ویرایش محصول
    if data.startswith("edit:"):
        if uid != ADMIN_ID:
            return await q.edit_message_text("فقط ادمین.")
        pid = int(data.split(":")[1])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("نام", callback_data=f"e:name:{pid}"),
             InlineKeyboardButton("قیمت", callback_data=f"e:price:{pid}")],
            [InlineKeyboardButton("توضیح", callback_data=f"e:desc:{pid}"),
             InlineKeyboardButton("عکس", callback_data=f"e:photo:{pid}")],
            [InlineKeyboardButton("فعال/غیرفعال", callback_data=f"e:toggle:{pid}"),
             InlineKeyboardButton("حذف ❌", callback_data=f"e:del:{pid}")]
        ])
        return await q.edit_message_text("کدام بخش را ویرایش کنیم؟", reply_markup=kb)

    if data.startswith("e:"):
        _, field, pid = data.split(":")
        pid = int(pid)
        if field == "name":
            set_state(uid, "edit_name", pid=pid)
            return await q.edit_message_text("نام جدید را بفرست:")
        if field == "price":
            set_state(uid, "edit_price", pid=pid)
            return await q.edit_message_text("قیمت جدید (عدد):")
        if field == "desc":
            set_state(uid, "edit_desc", pid=pid)
            return await q.edit_message_text("توضیح جدید را بفرست (یا '-' برای خالی):")
        if field == "photo":
            set_state(uid, "edit_photo", pid=pid)
            return await q.edit_message_text("عکس جدید را ارسال کن:")
        if field == "toggle":
            cur = db_execute("SELECT is_active FROM products WHERE id=%s", (pid,), "one")[0]
            db_execute("UPDATE products SET is_active=%s WHERE id=%s", (not cur, pid))
            return await q.edit_message_text(f"وضعیت محصول تغییر کرد: {'فعال' if not cur else 'غیرفعال'}")
        if field == "del":
            db_execute("DELETE FROM products WHERE id=%s", (pid,))
            return await q.edit_message_text("محصول حذف شد.")

# ویرایش متن‌ها برای حالت‌های ادیت
async def edit_text_collector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = get_state(uid)
    if not st: return
    mode = st["mode"]; data = st["data"]
    if mode == "edit_name":
        db_execute("UPDATE products SET name=%s WHERE id=%s", (update.message.text, data["pid"]))
        set_state(uid, None); return await update.message.reply_text("نام به‌روزرسانی شد.")
    if mode == "edit_price":
        try:
            price = Decimal(update.message.text)
        except Exception:
            return await update.message.reply_text("عدد معتبر نیست.")
        db_execute("UPDATE products SET price=%s WHERE id=%s", (price, data["pid"]))
        set_state(uid, None); return await update.message.reply_text("قیمت به‌روزرسانی شد.")
    if mode == "edit_desc":
        desc = None if update.message.text.strip() == "-" else update.message.text
        db_execute("UPDATE products SET description=%s WHERE id=%s", (desc, data["pid"]))
        set_state(uid, None); return await update.message.reply_text("توضیح به‌روزرسانی شد.")

# دریافت فایل‌های موزیک ادمین
async def audio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = get_state(uid)
    if not st or st["mode"] != "music_wait":
        return
    title = (update.message.caption or "").strip() or None
    file_id = update.message.audio.file_id
    urow = get_user_row(uid)
    db_execute("INSERT INTO music(title, file_id, uploaded_by) VALUES(%s,%s,%s)", (title, file_id, urow[0]))
    set_state(uid, None)
    await update.message.reply_text("✅ موزیک ثبت شد.")

# ----------------- Admin Add Product entry -----------------
@admin_only
async def add_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_state(update.effective_user.id, "add_product_name")
    await update.message.reply_text("نام محصول؟")

# ----------------- Bootstrapping -----------------
def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_product_cmd))  # شورت‌کات ادمین

    app.add_handler(CallbackQueryHandler(callback_router))

    # ورودی‌های متنی
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, edit_text_collector))  # ابتدا ادیت‌ها
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.AUDIO, audio_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))  # سپس روتر عمومی

    return app

if __name__ == "__main__":
    app = build_app()
    # Polling (بدون وب‌هوک و بدون پورت)
    app.run_polling(close_loop=False)
