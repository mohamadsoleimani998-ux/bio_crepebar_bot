import os
import logging
import asyncio
from typing import Final, Optional, Dict, Any, List, Tuple
from datetime import datetime

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup,
    KeyboardButton, InputMediaPhoto, Audio
)
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes, CommandHandler,
    MessageHandler, CallbackQueryHandler, ConversationHandler, filters
)

# -------------------- Logging --------------------
logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("crepebar")

# -------------------- ENV --------------------
BOT_TOKEN: Final[str] = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")

PUBLIC_URL = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL", "")).rstrip("/")
if not PUBLIC_URL:
    raise RuntimeError("Set PUBLIC_URL (e.g. https://your-service.onrender.com)")

PORT = int(os.getenv("PORT", "10000"))

# چند ادمین می‌تونه داشته باشه، با ویرگول جدا کن
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "0")).split(",")
    if x.strip().isdigit()
}

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL (Postgres DSN) is missing")

# -------------------- DB (psycopg2) --------------------
import psycopg2
import psycopg2.extras

def db_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def db_exec(sql: str, args: Tuple = (), fetch: bool = False, many: bool = False):
    with db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if many and isinstance(args, list):
                cur.executemany(sql, args)
            else:
                cur.execute(sql, args)
            if fetch:
                return cur.fetchall()
            return None

def init_db():
    db_exec("""
    CREATE TABLE IF NOT EXISTS users(
      id BIGINT PRIMARY KEY,
      name TEXT,
      phone TEXT,
      address TEXT,
      wallet BIGINT DEFAULT 0,
      created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS products(
      id SERIAL PRIMARY KEY,
      name TEXT NOT NULL,
      price BIGINT NOT NULL,
      photo_file_id TEXT,
      active BOOLEAN DEFAULT TRUE
    );
    CREATE TABLE IF NOT EXISTS orders(
      id SERIAL PRIMARY KEY,
      user_id BIGINT REFERENCES users(id),
      status TEXT DEFAULT 'new',
      total BIGINT DEFAULT 0,
      delivery_method TEXT,
      created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS order_items(
      id SERIAL PRIMARY KEY,
      order_id INT REFERENCES orders(id) ON DELETE CASCADE,
      product_id INT REFERENCES products(id),
      qty INT NOT NULL,
      price BIGINT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS wallet_tx(
      id SERIAL PRIMARY KEY,
      user_id BIGINT REFERENCES users(id),
      amount BIGINT NOT NULL,
      status TEXT DEFAULT 'pending', -- pending/approved/rejected
      evidence_file_id TEXT,
      created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS music(
      id SERIAL PRIMARY KEY,
      title TEXT,
      file_id TEXT NOT NULL,
      uploaded_by BIGINT,
      created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    log.info("DB ready.")

# -------------------- Helpers --------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def main_menu_kb(is_admin_flag: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton("منوی محصولات ☕️"), KeyboardButton("کیف پول 💸")],
        [KeyboardButton("موزیک کافه 🎵"), KeyboardButton("بازی‌ها 🎮")],
        [KeyboardButton("اینستاگرام 📲")],
    ]
    if is_admin_flag:
        rows.append([KeyboardButton("افزودن محصول ➕"), KeyboardButton("مدیریت محصولات ⚙️")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[Dict[str, Any]]:
    uid = update.effective_user.id
    rows = db_exec("SELECT * FROM users WHERE id=%s", (uid,), fetch=True)
    return rows[0] if rows else None

# -------------------- Profile Flow --------------------
ASK_NAME, ASK_PHONE, ASK_ADDRESS = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update, context)
    if not user:
        await update.message.reply_text("به بایو کرپ بار خوش اومدی ☕️\nاول یه معرفی کوچیک 👍\nاسم و فامیلت رو بفرست:")
        return ASK_NAME
    await update.message.reply_text(
        "☕️ به بایو کرپ بار خوش اومدی!",
        reply_markup=main_menu_kb(is_admin(update.effective_user.id))
    )
    return ConversationHandler.END

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = (update.message.text or "").strip()
    await update.message.reply_text("شماره موبایلت رو بفرست:")
    return ASK_PHONE

async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = (update.message.text or "").strip()
    await update.message.reply_text("آدرس تحویل رو بفرست:")
    return ASK_ADDRESS

async def finish_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("name", "")
    phone = context.user_data.get("phone", "")
    address = (update.message.text or "").strip()
    uid = update.effective_user.id
    db_exec(
        "INSERT INTO users(id,name,phone,address) VALUES(%s,%s,%s,%s) "
        "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, phone=EXCLUDED.phone, address=EXCLUDED.address",
        (uid, name, phone, address)
    )
    await update.message.reply_text("پروفایلت ثبت شد ✅", reply_markup=main_menu_kb(is_admin(uid)))
    return ConversationHandler.END

async def cancel_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.", reply_markup=main_menu_kb(is_admin(update.effective_user.id)))
    return ConversationHandler.END

# -------------------- Products (Admin) --------------------
ADD_NAME, ADD_PRICE, ADD_PHOTO = range(10, 13)
EDIT_CHOOSE, EDIT_FIELD, EDIT_VALUE, EDIT_PHOTO = range(13, 17)

async def add_product_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("فقط ادمین می‌تواند محصول اضافه کند.")
    await update.message.reply_text("نام محصول؟")
    return ADD_NAME

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = (update.message.text or "").strip()
    await update.message.reply_text("قیمت (تومان)؟")
    return ADD_PRICE

async def add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int((update.message.text or "0").replace(",", "").strip())
    except:
        return await update.message.reply_text("عدد معتبر وارد کن.")
    context.user_data["p_price"] = price
    await update.message.reply_text("عکس محصول رو بفرست (یا /skip برای بدون عکس).")
    return ADD_PHOTO

async def save_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = None
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    name = context.user_data["p_name"]
    price = context.user_data["p_price"]
    db_exec("INSERT INTO products(name,price,photo_file_id) VALUES(%s,%s,%s)", (name, price, photo_id))
    await update.message.reply_text("محصول ثبت شد ✅")
    return ConversationHandler.END

async def skip_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data["p_name"]
    price = context.user_data["p_price"]
    db_exec("INSERT INTO products(name,price) VALUES(%s,%s)", (name, price))
    await update.message.reply_text("محصول بدون عکس ثبت شد ✅")
    return ConversationHandler.END

async def admin_list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("اجازه دسترسی نداری.")
    rows = db_exec("SELECT * FROM products ORDER BY id DESC", fetch=True)
    if not rows:
        return await update.message.reply_text("هنوز محصولی نداریم.")
    kb = []
    for r in rows:
        kb.append([InlineKeyboardButton(f"#{r['id']} • {r['name']} ({r['price']:,})", callback_data=f"adm_edit:{r['id']}")])
    await update.message.reply_text("مدیریت محصولات:", reply_markup=InlineKeyboardMarkup(kb))

async def admin_edit_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    context.user_data["edit_pid"] = pid
    kb = [
        [InlineKeyboardButton("نام", callback_data="edit_field:name"),
         InlineKeyboardButton("قیمت", callback_data="edit_field:price")],
        [InlineKeyboardButton("عکس", callback_data="edit_field:photo"),
         InlineKeyboardButton("حذف", callback_data="edit_field:delete")],
        [InlineKeyboardButton("بستن", callback_data="edit_field:close")]
    ]
    await q.edit_message_text(f"ویرایش محصول #{pid}", reply_markup=InlineKeyboardMarkup(kb))
    return EDIT_CHOOSE

async def admin_edit_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, field = q.data.split(":")
    pid = context.user_data.get("edit_pid")
    if field == "name":
        await q.edit_message_text(f"نام جدید برای #{pid} را بفرست:")
        return EDIT_VALUE
    if field == "price":
        await q.edit_message_text(f"قیمت جدید برای #{pid} را بفرست:")
        context.user_data["expect_price"] = True
        return EDIT_VALUE
    if field == "photo":
        await q.edit_message_text(f"عکس جدید برای #{pid} را بفرست:")
        return EDIT_PHOTO
    if field == "delete":
        db_exec("DELETE FROM products WHERE id=%s", (pid,))
        await q.edit_message_text("حذف شد ✅")
        return ConversationHandler.END
    await q.edit_message_text("بسته شد.")
    return ConversationHandler.END

async def admin_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.get("edit_pid")
    if context.user_data.get("expect_price"):
        try:
            price = int((update.message.text or "0").replace(",", ""))
        except:
            return await update.message.reply_text("عدد معتبر وارد کن:")
        db_exec("UPDATE products SET price=%s WHERE id=%s", (price, pid))
        context.user_data.pop("expect_price", None)
        await update.message.reply_text("قیمت به‌روزرسانی شد ✅")
        return ConversationHandler.END
    else:
        name = (update.message.text or "").strip()
        db_exec("UPDATE products SET name=%s WHERE id=%s", (name, pid))
        await update.message.reply_text("نام به‌روزرسانی شد ✅")
        return ConversationHandler.END

async def admin_edit_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.get("edit_pid")
    if not update.message.photo:
        return await update.message.reply_text("لطفاً عکس بفرست.")
    file_id = update.message.photo[-1].file_id
    db_exec("UPDATE products SET photo_file_id=%s WHERE id=%s", (file_id, pid))
    await update.message.reply_text("عکس به‌روزرسانی شد ✅")
    return ConversationHandler.END

# -------------------- Products (User) & Cart --------------------
def cart_get(ctx: ContextTypes.DEFAULT_TYPE) -> Dict[int, int]:
    return ctx.user_data.setdefault("cart", {})

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db_exec("SELECT * FROM products WHERE active=TRUE ORDER BY id DESC", fetch=True)
    if not rows:
        return await update.message.reply_text("هنوز محصولی ثبت نشده.")
    kb = []
    for r in rows:
        kb.append([InlineKeyboardButton(f"{r['name']} • {r['price']:,} تومان", callback_data=f"p:{r['id']}")])
    await update.message.reply_text("منوی محصولات:", reply_markup=InlineKeyboardMarkup(kb))

async def product_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    rows = db_exec("SELECT * FROM products WHERE id=%s", (pid,), fetch=True)
    if not rows: 
        return await q.edit_message_text("پیدا نشد.")
    p = rows[0]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن به سبد", callback_data=f"add:{pid}")],
        [InlineKeyboardButton("بازگشت", callback_data="back:menu")]
    ])
    caption = f"{p['name']}\nقیمت: {p['price']:,} تومان"
    if p["photo_file_id"]:
        await q.message.reply_photo(p["photo_file_id"], caption=caption, reply_markup=kb)
        try: await q.delete_message()
        except: pass
    else:
        await q.edit_message_text(caption, reply_markup=kb)

async def add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    rows = db_exec("SELECT id,name,price FROM products WHERE id=%s", (pid,), fetch=True)
    if not rows:
        return await q.answer("یافت نشد", show_alert=True)
    cart = cart_get(context)
    cart[pid] = cart.get(pid, 0) + 1
    await q.answer("به سبد اضافه شد ✅", show_alert=False)

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    fake_update = Update.de_json({}, context.application.bot)  # فقط برای استفاده از تابع
    fake_update.effective_user = q.from_user  # type: ignore
    fake_update.message = q.message  # type: ignore
    await show_menu(q, context)  # type: ignore

async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cart = cart_get(context)
    if not cart:
        return await update.message.reply_text("سبد خالیه.")
    items = []
    total = 0
    for pid, qty in cart.items():
        r = db_exec("SELECT id,name,price FROM products WHERE id=%s", (pid,), fetch=True)
        if not r: continue
        name, price = r[0]["name"], r[0]["price"]
        items.append(f"- {name} × {qty} = {(price*qty):,}")
        total += price * qty
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("تسویه و ثبت سفارش ✅", callback_data="checkout")],
        [InlineKeyboardButton("خالی کردن سبد 🗑", callback_data="emptycart")]
    ])
    await update.message.reply_text("سبد خرید:\n" + "\n".join(items) + f"\n\nمجموع: {total:,} تومان", reply_markup=kb)

async def cart_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "emptycart":
        context.user_data["cart"] = {}
        return await q.edit_message_text("سبد خالی شد.")
    if q.data == "checkout":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("ارسال پیک 🚚", callback_data="deliver:post")],
            [InlineKeyboardButton("تحویل حضوری 🏠", callback_data="deliver:pickup")]
        ])
        return await q.edit_message_text("روش تحویل رو انتخاب کن:", reply_markup=kb)

async def checkout_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    method = "ارسال" if q.data.endswith("post") else "حضوری"
    cart = cart_get(context)
    if not cart:
        return await q.edit_message_text("سبد خالیه.")
    uid = q.from_user.id
    # محاسبه مبلغ
    total = 0
    rows_to_add = []
    for pid, qty in cart.items():
        p = db_exec("SELECT id,price FROM products WHERE id=%s", (pid,), fetch=True)[0]
        total += p["price"] * qty
        rows_to_add.append((pid, qty, p["price"]))
    # ایجاد سفارش
    db_exec("INSERT INTO orders(user_id,status,total,delivery_method) VALUES(%s,%s,%s,%s)", (uid, "new", total, method))
    order_id = db_exec("SELECT currval(pg_get_serial_sequence('orders','id'))", fetch=True)[0]['currval']
    db_exec("INSERT INTO order_items(order_id,product_id,qty,price) VALUES (%s,%s,%s,%s)",
            [(order_id, pid, qty, price) for (pid, qty, price) in rows_to_add], many=True)
    context.user_data["cart"] = {}
    await q.edit_message_text(f"سفارش #{order_id} ثبت شد ✅\nمبلغ: {total:,} تومان\nروش تحویل: {method}")

# -------------------- Wallet --------------------
CHARGE_AMT, CHARGE_EVIDENCE = range(30, 32)

async def wallet_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    r = db_exec("SELECT wallet FROM users WHERE id=%s", (uid,), fetch=True)
    balance = r[0]["wallet"] if r else 0
    await update.message.reply_text(f"موجودی: {balance:,} تومان\nبرای شارژ، «/charge» رو بزن.")

async def charge_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مبلغ شارژ (تومان) را بفرست:")
    return CHARGE_AMT

async def charge_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = int((update.message.text or "0").replace(",", ""))
        if amt <= 0:
            raise ValueError
    except:
        return await update.message.reply_text("عدد معتبر بفرست:")
    context.user_data["charge_amt"] = amt
    await update.message.reply_text("رسید (عکس/اسکرین‌شات) را بفرست. /skip اگر فعلاً نداری.")
    return CHARGE_EVIDENCE

async def charge_evidence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    amt = context.user_data["charge_amt"]
    file_id = update.message.photo[-1].file_id if update.message.photo else None
    db_exec("INSERT INTO wallet_tx(user_id,amount,status,evidence_file_id) VALUES(%s,%s,'pending',%s)", (uid, amt, file_id))
    tx_id = db_exec("SELECT currval(pg_get_serial_sequence('wallet_tx','id'))", fetch=True)[0]['currval']
    await update.message.reply_text("درخواست شارژ ثبت شد ✅. پس از تأیید ادمین اعمال می‌شود.")
    # پیام به ادمین‌ها
    for admin in ADMIN_IDS:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("تأیید ✅", callback_data=f"tx:ok:{tx_id}:{uid}:{amt}"),
                                    InlineKeyboardButton("رد ❌", callback_data=f"tx:no:{tx_id}:{uid}:{amt}")]])
        if file_id:
            await context.bot.send_photo(admin, file_id, caption=f"درخواست شارژ #{tx_id}\nUser: {uid}\nAmount: {amt:,}", reply_markup=kb)
        else:
            await context.bot.send_message(admin, f"درخواست شارژ #{tx_id}\nUser: {uid}\nAmount: {amt:,}", reply_markup=kb)
    return ConversationHandler.END

async def charge_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # بدون عکس
    return await charge_evidence(update, context)

async def tx_admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, action, tx_id, uid, amt = q.data.split(":")
    tx_id, uid, amt = int(tx_id), int(uid), int(amt)
    if not is_admin(q.from_user.id):
        return await q.answer("اجازه نداری", show_alert=True)
    if action == "ok":
        # اعمال به کیف پول
        db_exec("UPDATE wallet_tx SET status='approved' WHERE id=%s", (tx_id,))
        db_exec("UPDATE users SET wallet = COALESCE(wallet,0) + %s WHERE id=%s", (amt, uid))
        await q.edit_message_caption(caption=(q.message.caption + "\n✅ تأیید شد") if q.message.caption else "✅ تأیید شد")
        await context.bot.send_message(uid, f"شارژ کیف پول به مبلغ {amt:,} تومان تأیید شد ✅")
    else:
        db_exec("UPDATE wallet_tx SET status='rejected' WHERE id=%s", (tx_id,))
        await q.edit_message_caption(caption=(q.message.caption + "\n❌ رد شد") if q.message.caption else "❌ رد شد")
        await context.bot.send_message(uid, f"درخواست شارژ #{tx_id} رد شد ❌")

# -------------------- Music --------------------
async def music_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db_exec("SELECT * FROM music ORDER BY id DESC LIMIT 20", fetch=True)
    if not rows:
        return await update.message.reply_text("فعلاً موزیکی موجود نیست.")
    for r in rows:
        await update.message.reply_audio(r["file_id"], caption=r.get("title") or "Cafe Music")

async def music_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    a: Audio = update.message.audio
    if not a:
        return
    title = a.title or a.file_name or "Cafe Music"
    db_exec("INSERT INTO music(title,file_id,uploaded_by) VALUES(%s,%s,%s)", (title, a.file_id, update.effective_user.id))
    await update.message.reply_text("موزیک ذخیره شد ✅")

# -------------------- Command/Text Router --------------------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    uid = update.effective_user.id
    if txt == "منوی محصولات ☕️":
        return await show_menu(update, context)
    if txt == "کیف پول 💸":
        return await wallet_info(update, context)
    if txt == "اینستاگرام 📲":
        return await update.message.reply_text("instagram.com/yourpage")
    if txt == "موزیک کافه 🎵":
        return await music_list(update, context)
    if txt == "افزودن محصول ➕":
        if is_admin(uid):
            return await add_product_entry(update, context)
        return await update.message.reply_text("اجازه دسترسی نداری.")
    if txt == "مدیریت محصولات ⚙️":
        return await admin_list_products(update, context)
    if txt == "بازی‌ها 🎮":
        return await update.message.reply_text("بخش بازی‌ها به‌زودی… 🎯")
    if txt == "/cart":
        return await show_cart(update, context)
    return await update.message.reply_text("از منو استفاده کن یا /cart برای دیدن سبد.")

# -------------------- Webhook boot --------------------
async def run() -> None:
    init_db()
    app: Application = ApplicationBuilder().token(BOT_TOKEN).build()

    # profile
    profile_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_profile)],
        },
        fallbacks=[CommandHandler("cancel", cancel_profile)],
    )
    app.add_handler(profile_conv)

    # add product
    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^افزودن محصول ➕$"), add_product_entry)],
        states={
            ADD_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            ADD_PRICE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_photo)],
            ADD_PHOTO:  [
                MessageHandler(filters.PHOTO, save_product),
                CommandHandler("skip", skip_product_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_profile)],
        name="add_product",
        persistent=False
    )
    app.add_handler(add_conv)

    # edit product (admin)
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_entry, pattern=r"^adm_edit:\d+$")],
        states={
            EDIT_CHOOSE: [CallbackQueryHandler(admin_edit_choose, pattern=r"^edit_field:")],
            EDIT_VALUE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_value)],
            EDIT_PHOTO:  [MessageHandler(filters.PHOTO, admin_edit_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel_profile)],
        name="edit_product",
        persistent=False
    )
    app.add_handler(edit_conv)

    # products / cart / checkout
    app.add_handler(MessageHandler(filters.Regex("^منوی محصولات ☕️$"), show_menu))
    app.add_handler(CallbackQueryHandler(product_detail, pattern=r"^p:\d+$"))
    app.add_handler(CallbackQueryHandler(add_to_cart, pattern=r"^add:\d+$"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern=r"^back:menu$"))
    app.add_handler(CommandHandler("cart", show_cart))
    app.add_handler(CallbackQueryHandler(cart_buttons, pattern=r"^(emptycart|checkout)$"))
    app.add_handler(CallbackQueryHandler(checkout_delivery, pattern=r"^deliver:(post|pickup)$"))

    # wallet
    app.add_handler(CommandHandler("wallet", wallet_info))
    charge_conv = ConversationHandler(
        entry_points=[CommandHandler("charge", charge_start)],
        states={
            CHARGE_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, charge_amount)],
            CHARGE_EVIDENCE: [
                MessageHandler(filters.PHOTO, charge_evidence),
                CommandHandler("skip", charge_skip),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_profile)],
        name="charge",
        persistent=False
    )
    app.add_handler(charge_conv)
    app.add_handler(CallbackQueryHandler(tx_admin_buttons, pattern=r"^tx:(ok|no):"))

    # music
    app.add_handler(MessageHandler(filters.AUDIO, music_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # webhook
    url_path = BOT_TOKEN
    webhook_url = f"{PUBLIC_URL}/{url_path}"
    await app.bot.set_webhook(webhook_url, drop_pending_updates=True)
    await app.run_webhook(listen="0.0.0.0", port=PORT, url_path=url_path, webhook_url=webhook_url)

if __name__ == "__main__":
    asyncio.run(run())
