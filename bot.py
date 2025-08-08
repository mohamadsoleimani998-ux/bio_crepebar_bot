import os
import asyncio
from typing import Dict, Any, Optional, List, Tuple

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    filters, ContextTypes
)

import psycopg2
from psycopg2.extras import RealDictCursor

# ===================== ENV =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # ضروری
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))      # تلگرام آی‌دی ادمین
DATABASE_URL = os.getenv("DATABASE_URL")        # Postgres DSN

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL is missing")

# ===================== DB ======================
def db_conn():
    return psycopg2.connect(DATABASE_URL)

def db_exec(sql: str, params: Tuple = (), fetch: bool = False, many: bool = False):
    def _run():
        with db_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if many:
                    cur.executemany(sql, params)
                else:
                    cur.execute(sql, params)
                if fetch:
                    return cur.fetchall()
                return None
    return asyncio.to_thread(_run)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  tg_id BIGINT UNIQUE NOT NULL,
  full_name TEXT, phone TEXT, address TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS wallets (
  user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  balance BIGINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS products (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  price BIGINT NOT NULL CHECK (price>=0),
  description TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  main_photo_file_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS product_photos (
  id BIGSERIAL PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  file_id TEXT NOT NULL,
  is_main BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS orders (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  status TEXT NOT NULL DEFAULT 'draft',
  total_amount BIGINT NOT NULL DEFAULT 0,
  delivery_method TEXT,
  delivery_address TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS order_items (
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
  quantity INT NOT NULL CHECK (quantity>0),
  unit_price BIGINT NOT NULL CHECK (unit_price>=0)
);
CREATE TABLE IF NOT EXISTS payments (
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT REFERENCES orders(id) ON DELETE CASCADE,
  amount BIGINT NOT NULL CHECK (amount>=0),
  method TEXT NOT NULL DEFAULT 'card_to_card',
  ref_no TEXT,
  confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS music (
  id BIGSERIAL PRIMARY KEY,
  title TEXT,
  file_id TEXT NOT NULL,
  added_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_tg_id        ON users(tg_id);
CREATE INDEX IF NOT EXISTS idx_photos_product     ON product_photos(product_id);
CREATE INDEX IF NOT EXISTS idx_orders_user        ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_items_order        ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_items_product      ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_payments_order     ON payments(order_id);
"""

async def ensure_schema():
    await db_exec(SCHEMA_SQL)

async def ensure_user(tg_id: int, name: str) -> int:
    rows = await db_exec("SELECT id FROM users WHERE tg_id=%s", (tg_id,), fetch=True)
    if rows:
        return rows[0]["id"]
    await db_exec("INSERT INTO users (tg_id, full_name) VALUES (%s,%s)", (tg_id, name))
    rows = await db_exec("SELECT id FROM users WHERE tg_id=%s", (tg_id,), fetch=True)
    return rows[0]["id"]

# ================== KEYBOARDS ==================
def main_kb(is_admin: bool = False):
    rows = [
        [KeyboardButton("منوی محصولات ☕"), KeyboardButton("کیف پول 💸")],
        [KeyboardButton("اینستاگرام 📲"), KeyboardButton("🎵 موزیک‌ها")],
        [KeyboardButton("🕹️ بازی")]  # placeholder
    ]
    if is_admin:
        rows.append([KeyboardButton("➕ افزودن محصول"), KeyboardButton("✏️ ویرایش محصول")])
        rows.append([KeyboardButton("✅ تأیید شارژها")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def wallet_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("افزایش موجودی"), KeyboardButton("موجودی من")],
         [KeyboardButton("بازگشت ⬅️")]],
        resize_keyboard=True
    )

def back_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("بازگشت ⬅️")]], resize_keyboard=True)

# ============ Conversation States ============
(ASK_FULLNAME, ASK_PHONE, ASK_ADDRESS,
 P_ADD_NAME, P_ADD_PRICE, P_ADD_DESC, P_ADD_PHOTO,
 P_EDIT_SELECT, P_EDIT_FIELD, P_EDIT_NEW_VALUE,
 WALLET_AMOUNT, WALLET_REF,
 MUSIC_WAIT_TITLE, MUSIC_WAIT_FILEID) = range(14)

# =============== /start ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_schema()

    user = update.effective_user
    uid = await ensure_user(user.id, user.full_name or user.first_name or "")
    # تکمیل پروفایل اگر ناقص باشد
    rows = await db_exec("SELECT full_name, phone, address FROM users WHERE id=%s", (uid,), fetch=True)
    u = rows[0]
    if not u["full_name"]:
        await update.message.reply_text("لطفاً نام و نام‌خانوادگی‌تان را بفرستید:", reply_markup=back_kb())
        return ASK_FULLNAME
    if not u["phone"]:
        await update.message.reply_text("شماره موبایل را بفرستید (مثلاً 09xxxxxxxxx):", reply_markup=back_kb())
        return ASK_PHONE
    if not u["address"]:
        await update.message.reply_text("آدرس تحویل را بفرستید:", reply_markup=back_kb())
        return ASK_ADDRESS

    is_admin = (user.id == ADMIN_ID)
    await update.message.reply_text("☕ به بایو کرِپ بار خوش آمدید.", reply_markup=main_kb(is_admin))
    return ConversationHandler.END

# ===== Profile filling handlers =====
async def on_fullname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt == "بازگشت ⬅️":
        return await start(update, context)
    uid = await ensure_user(update.effective_user.id, txt)
    await db_exec("UPDATE users SET full_name=%s WHERE id=%s", (txt, uid))
    await update.message.reply_text("شماره موبایل را بفرستید:", reply_markup=back_kb())
    return ASK_PHONE

async def on_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt == "بازگشت ⬅️":
        return await start(update, context)
    uid = await ensure_user(update.effective_user.id, update.effective_user.full_name or "")
    await db_exec("UPDATE users SET phone=%s WHERE id=%s", (txt, uid))
    await update.message.reply_text("آدرس تحویل را بفرستید:", reply_markup=back_kb())
    return ASK_ADDRESS

async def on_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt == "بازگشت ⬅️":
        return await start(update, context)
    uid = await ensure_user(update.effective_user.id, update.effective_user.full_name or "")
    await db_exec("UPDATE users SET address=%s WHERE id=%s", (txt, uid))
    await update.message.reply_text("✅ اطلاعات تکمیل شد.", reply_markup=main_kb(update.effective_user.id == ADMIN_ID))
    return ConversationHandler.END

# =============== Products list ===============
async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await db_exec("SELECT id,name,price,description FROM products WHERE is_active = TRUE ORDER BY id DESC", fetch=True)
    if not rows:
        await update.message.reply_text("هنوز محصولی ثبت نشده است.")
        return
    lines = [f"#{r['id']} — {r['name']} — {r['price']:,} ریال" + (f"\n      {r['description']}" if r['description'] else "") for r in rows]
    await update.message.reply_text("منوی محصولات:\n\n" + "\n\n".join(lines))

# =========== Add Product (Admin) ============
async def add_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("نام محصول را بفرست:", reply_markup=back_kb())
    return P_ADD_NAME

async def p_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "بازگشت ⬅️":
        return await start(update, context)
    context.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("قیمت به ریال:", reply_markup=back_kb())
    return P_ADD_PRICE

async def p_add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "بازگشت ⬅️":
        return await start(update, context)
    try:
        price = int(update.message.text.replace(",", "").strip())
    except Exception:
        await update.message.reply_text("قیمت نامعتبر است. عدد بفرست.")
        return P_ADD_PRICE
    context.user_data["p_price"] = price
    await update.message.reply_text("توضیح کوتاه (اختیاری). اگر نمی‌خواهی «-» بفرست.")
    return P_ADD_DESC

async def p_add_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if desc == "-":
        desc = None
    context.user_data["p_desc"] = desc
    await update.message.reply_text("اگر می‌خواهی عکس اصلی محصول را بفرستی، الان یک عکس بفرست؛ وگرنه «بازگشت ⬅️» را بزن تا بدون عکس ثبت شود.")
    return P_ADD_PHOTO

async def p_add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ثبت محصول
    name = context.user_data.get("p_name")
    price = context.user_data.get("p_price")
    desc = context.user_data.get("p_desc")

    main_photo = None
    if update.message.photo:
        main_photo = update.message.photo[-1].file_id

    await db_exec(
        "INSERT INTO products (name, price, description, main_photo_file_id) VALUES (%s,%s,%s,%s)",
        (name, price, desc, main_photo)
    )
    await update.message.reply_text("✅ محصول با موفقیت ثبت شد.", reply_markup=main_kb(update.effective_user.id == ADMIN_ID))
    return ConversationHandler.END

# =========== Edit Product (Admin) ===========
async def edit_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    rows = await db_exec("SELECT id,name FROM products ORDER BY id DESC", fetch=True)
    if not rows:
        await update.message.reply_text("محصولی برای ویرایش نیست.")
        return ConversationHandler.END
    txt = "آیدی محصولی که می‌خواهی ویرایش کنی را بفرست:\n" + ", ".join([f"#{r['id']} {r['name']}" for r in rows])
    await update.message.reply_text(txt, reply_markup=back_kb())
    return P_EDIT_SELECT

async def p_edit_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "بازگشت ⬅️":
        return await start(update, context)
    pid = int(update.message.text.strip().lstrip("#"))
    context.user_data["edit_pid"] = pid
    await update.message.reply_text("کدام بخش را ویرایش کنیم؟\n- name\n- price\n- description\n- photo(main)")
    return P_EDIT_FIELD

async def p_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = update.message.text.strip().lower()
    context.user_data["edit_field"] = field
    if field == "photo" or field == "photo(main)":
        await update.message.reply_text("عکس جدید را بفرست.")
    else:
        await update.message.reply_text("مقدار جدید را بفرست.")
    return P_EDIT_NEW_VALUE

async def p_edit_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data["edit_pid"]
    field = context.user_data["edit_field"]
    if field.startswith("photo"):
        if not update.message.photo:
            await update.message.reply_text("عکس نفرستادی!")
            return P_EDIT_NEW_VALUE
        file_id = update.message.photo[-1].file_id
        await db_exec("UPDATE products SET main_photo_file_id=%s WHERE id=%s", (file_id, pid))
    elif field == "name":
        await db_exec("UPDATE products SET name=%s WHERE id=%s", (update.message.text.strip(), pid))
    elif field == "price":
        val = int(update.message.text.replace(",", "").strip())
        await db_exec("UPDATE products SET price=%s WHERE id=%s", (val, pid))
    elif field == "description":
        await db_exec("UPDATE products SET description=%s WHERE id=%s", (update.message.text.strip(), pid))
    else:
        await update.message.reply_text("فیلد ناشناخته بود.")
        return ConversationHandler.END

    await update.message.reply_text("✅ ویرایش انجام شد.", reply_markup=main_kb(update.effective_user.id == ADMIN_ID))
    return ConversationHandler.END

# =============== Wallet =======================
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مدیریت کیف پول:", reply_markup=wallet_kb())

async def wallet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مبلغ شارژ (ریال) را بفرست:", reply_markup=back_kb())
    return WALLET_AMOUNT

async def wallet_amount_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "بازگشت ⬅️":
        await wallet_menu(update, context)
        return ConversationHandler.END
    amount = int(update.message.text.replace(",", "").strip())
    context.user_data["wallet_amount"] = amount
    await update.message.reply_text(
        f"مبلغ {amount:,} ریال را کارت‌به‌کارت کنید و رسید یا ۴ رقم آخر کارت را بفرستید.",
        reply_markup=back_kb()
    )
    return WALLET_REF

async def wallet_ref_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = await ensure_user(update.effective_user.id, update.effective_user.full_name or "")
    amount = context.user_data.get("wallet_amount", 0)
    ref = update.message.text
    # پرداخت معلق (order_id = NULL)
    await db_exec("INSERT INTO payments (order_id, amount, method, ref_no, confirmed) VALUES (NULL,%s,'card_to_card',%s,false)",
                  (amount, ref))
    await update.message.reply_text("✅ درخواست شارژ ثبت شد. پس از تأیید ادمین اعمال می‌شود.", reply_markup=main_kb(update.effective_user.id == ADMIN_ID))
    if ADMIN_ID:
        await update.get_bot().send_message(
            chat_id=ADMIN_ID,
            text=f"درخواست شارژ جدید:\nمبلغ: {amount:,}\nاز کاربر: {update.effective_user.id}\nرفرنس: {ref}\nبرای تأیید: /confirm <payment_id>"
        )
    return ConversationHandler.END

# ادمین: لیست و تأیید شارژها
async def admin_confirm_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    rows = await db_exec("SELECT id, amount, ref_no, confirmed FROM payments WHERE confirmed=false ORDER BY id", fetch=True)
    if not rows:
        await update.message.reply_text("شارژ معوقی نداریم.")
        return
    txt = "شارژهای منتظر تأیید:\n" + "\n".join([f"#{r['id']} — {r['amount']:,} — ref:{r['ref_no'] or '-'}" for r in rows])
    txt += "\n\nبرای تأیید: /confirm <id>"
    await update.message.reply_text(txt)

async def admin_confirm_one(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        pid = int(context.args[0])
    except Exception:
        await update.message.reply_text("فرمت: /confirm 123")
        return
    rows = await db_exec("SELECT id, amount FROM payments WHERE id=%s AND confirmed=false", (pid,), fetch=True)
    if not rows:
        await update.message.reply_text("موردی یافت نشد.")
        return
    amount = rows[0]["amount"]
    # برای سادگی، به اولین کاربر درخواست‌دهنده نسبت نمی‌دهیم (چون پرداخت آزاد است)،
    # در عمل می‌توانی payments جدول را به user_id هم مجهز کنی. فعلاً فقط تأیید را ثبت می‌کنیم.
    await db_exec("UPDATE payments SET confirmed=true WHERE id=%s", (pid,))
    await update.message.reply_text(f"✅ پرداخت #{pid} تأیید شد.")
    # اینجا می‌توانی به‌دلخواه موجودی کیف‌پول کاربر را نیز زیاد کنی اگر payments به user_id وصل شد.

# =============== Music ========================
async def music_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("فایل موزیک را به صورت Audio ارسال کن تا ذخیره شود.", reply_markup=back_kb())
    return MUSIC_WAIT_FILEID

async def music_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.audio:
        await update.message.reply_text("Audio لازم است.")
        return MUSIC_WAIT_FILEID
    file_id = update.message.audio.file_id
    title = update.message.audio.title or update.message.audio.file_name
    uid = await ensure_user(update.effective_user.id, update.effective_user.full_name or "")
    await db_exec("INSERT INTO music (title,file_id,added_by_user_id) VALUES (%s,%s,%s)", (title, file_id, uid))
    await update.message.reply_text("✅ موزیک ذخیره شد.", reply_markup=main_kb(update.effective_user.id == ADMIN_ID))
    return ConversationHandler.END

# =============== Instagram, Game =============
async def instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اینستاگرام: https://instagram.com/yourpage", disable_web_page_preview=True)

async def game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("بخش بازی به‌زودی... (لیگ هفتگی و جایزه شارژ کیف‌پول)")

# =============== Router =======================
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    uid = update.effective_user.id
    is_admin = (uid == ADMIN_ID)

    if txt == "منوی محصولات ☕":
        return await list_products(update, context)
    if txt == "کیف پول 💸":
        return await wallet_menu(update, context)
    if txt == "افزایش موجودی":
        return await wallet_amount(update, context)
    if txt == "موجودی من":
        rows = await db_exec("""SELECT w.balance FROM wallets w 
                                JOIN users u ON u.id=w.user_id WHERE u.tg_id=%s""", (uid,), fetch=True)
        bal = rows[0]["balance"] if rows else 0
        return await update.message.reply_text(f"موجودی شما: {bal:,} ریال")
    if txt == "بازگشت ⬅️":
        return await start(update, context)
    if txt == "اینستاگرام 📲":
        return await instagram(update, context)
    if txt == "🎵 موزیک‌ها":
        return await music_menu(update, context)
    if txt == "🕹️ بازی":
        return await game(update, context)

    if is_admin and txt == "➕ افزودن محصول":
        return await add_product_entry(update, context)
    if is_admin and txt == "✏️ ویرایش محصول":
        return await edit_product_entry(update, context)
    if is_admin and txt == "✅ تأیید شارژها":
        return await admin_confirm_list(update, context)

    await update.message.reply_text("دستور ناشناخته بود. از منو استفاده کن.")

# =============== MAIN =========================
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # conversations
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_FULLNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_fullname)],
            ASK_PHONE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, on_phone)],
            ASK_ADDRESS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, on_address)],
        },
        fallbacks=[MessageHandler(filters.Regex("^بازگشت ⬅️$"), start)],
        name="profile", persistent=False
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ افزودن محصول$"), add_product_entry)],
        states={
            P_ADD_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, p_add_name)],
            P_ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_add_price)],
            P_ADD_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, p_add_desc)],
            P_ADD_PHOTO: [MessageHandler((filters.PHOTO | filters.Regex("^بازگشت ⬅️$")) & ~filters.COMMAND, p_add_photo)],
        },
        fallbacks=[MessageHandler(filters.Regex("^بازگشت ⬅️$"), start)],
        name="add_product", persistent=False
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✏️ ویرایش محصول$"), edit_product_entry)],
        states={
            P_EDIT_SELECT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, p_edit_select)],
            P_EDIT_FIELD:     [MessageHandler(filters.TEXT & ~filters.COMMAND, p_edit_field)],
            P_EDIT_NEW_VALUE: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, p_edit_new_value)],
        },
        fallbacks=[MessageHandler(filters.Regex("^بازگشت ⬅️$"), start)],
        name="edit_product", persistent=False
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزایش موجودی$"), wallet_amount)],
        states={
            WALLET_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_amount_get)],
            WALLET_REF:    [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_ref_get)],
        },
        fallbacks=[MessageHandler(filters.Regex("^بازگشت ⬅️$"), start)],
        name="wallet", persistent=False
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎵 موزیک‌ها$"), music_menu)],
        states={MUSIC_WAIT_FILEID: [MessageHandler(filters.AUDIO, music_save)]},
        fallbacks=[MessageHandler(filters.Regex("^بازگشت ⬅️$"), start)],
        name="music", persistent=False
    ))

    app.add_handler(CommandHandler("confirm", admin_confirm_one))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    return app

async def main():
    await ensure_schema()
    app = build_app()
    # Long Polling (برای Render مناسب است)
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.run(main())
