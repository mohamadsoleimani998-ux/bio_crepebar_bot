import os
import json
import logging
import asyncio
import threading
from typing import List, Dict, Any

from flask import Flask, request, Response

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("crepebar-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("ENV BOT_TOKEN is missing")
if not WEBHOOK_URL:
    raise RuntimeError("ENV WEBHOOK_URL is missing")

# ===== In-Memory Data (later -> DB) =====
PRODUCTS: List[Dict[str, Any]] = []

# ===== Flask =====
app = Flask(__name__)

# ===== Telegram Application =====
application: Application
loop = asyncio.new_event_loop()

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def main_menu_kb(is_admin_user: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("منوی محصولات ☕️", callback_data="menu:list")],
        [InlineKeyboardButton("کیف پول 💸", callback_data="wallet:open")],
        [InlineKeyboardButton("اینستاگرام 📱➡️", url="https://instagram.com/")],
    ]
    if is_admin_user:
        rows.append([InlineKeyboardButton("➕ افزودن محصول", callback_data="admin:add")])
    return InlineKeyboardMarkup(rows)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id if update.effective_user else 0
    await (update.effective_message or update.message).reply_text(
        "به بایو کرپ بار خوش اومدی ☕️",
        reply_markup=main_menu_kb(is_admin(uid)),
    )

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_main_menu(update, context)

def build_products_list_kb() -> InlineKeyboardMarkup:
    rows = []
    if PRODUCTS:
        for i, p in enumerate(PRODUCTS):
            title = f"🔹 {p['name']} — {p['price']} تومان"
            rows.append([InlineKeyboardButton(title, callback_data=f"menu:view:{i}")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="menu:back")])
    return InlineKeyboardMarkup(rows)

async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "menu:list":
        if not PRODUCTS:
            await q.edit_message_text(
                "هنوز محصولی ثبت نشده است.",
                reply_markup=build_products_list_kb(),
            )
        else:
            await q.edit_message_text("لیست محصولات:", reply_markup=build_products_list_kb())
        return

    if data.startswith("menu:view:"):
        idx = int(data.split(":")[-1])
        if 0 <= idx < len(PRODUCTS):
            p = PRODUCTS[idx]
            caption = f"**{p['name']}**\nقیمت: {p['price']} تومان"
            if p.get("photo_file_id"):
                await q.message.reply_photo(
                    photo=p["photo_file_id"], caption=caption, parse_mode=ParseMode.MARKDOWN
                )
            else:
                await q.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)

            rows = [[InlineKeyboardButton("⬅️ بازگشت به لیست", callback_data="menu:list")]]
            if is_admin(q.from_user.id):
                rows.append(
                    [
                        InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"admin:editname:{idx}"),
                        InlineKeyboardButton("💵 ویرایش قیمت", callback_data=f"admin:editprice:{idx}"),
                    ]
                )
                rows.append(
                    [
                        InlineKeyboardButton("🖼 ویرایش عکس", callback_data=f"admin:editphoto:{idx}"),
                        InlineKeyboardButton("🗑 حذف", callback_data=f"admin:delete:{idx}"),
                    ]
                )
            await q.message.reply_text("گزینه‌ها:", reply_markup=InlineKeyboardMarkup(rows))
        else:
            await q.message.reply_text("محصول یافت نشد.")
        return

    if data == "menu:back":
        await q.edit_message_text("منو:", reply_markup=main_menu_kb(is_admin(q.from_user.id)))
        return

async def cb_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer("به‌زودی…")
    await q.message.reply_text("کیف پول به‌زودی فعال می‌شود.")

# ===== Add / Edit product (Conversation) =====
NAME, PRICE, PHOTO = range(3)

async def admin_add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        await q.answer()
        user_id = q.from_user.id
        message = q.message
    else:
        user_id = update.effective_user.id
        message = update.effective_message

    if not is_admin(user_id):
        await message.reply_text("فقط ادمین می‌تواند محصول اضافه کند.")
        return ConversationHandler.END

    await message.reply_text("نام محصول را ارسال کنید:")
    return NAME

async def admin_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_product"] = {"name": update.message.text.strip()}
    await update.message.reply_text("قیمت را به تومان ارسال کنید (فقط عدد):")
    return PRICE

async def admin_add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip().replace(",", "")
    if not txt.isdigit():
        await update.message.reply_text("قیمت باید عدد باشد. دوباره بفرستید:")
        return PRICE
    context.user_data["new_product"]["price"] = int(txt)
    await update.message.reply_text("اگر عکس دارید ارسال کنید، وگرنه /skip بزنید.")
    return PHOTO

async def admin_add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1] if update.message.photo else None
    if photo:
        context.user_data["new_product"]["photo_file_id"] = photo.file_id
    PRODUCTS.append(context.user_data["new_product"])
    await update.message.reply_text("✅ محصول ثبت شد.")
    await show_main_menu(update, context)
    return ConversationHandler.END

async def admin_add_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    PRODUCTS.append(context.user_data["new_product"])
    await update.message.reply_text("✅ محصول بدون عکس ثبت شد.")
    await show_main_menu(update, context)
    return ConversationHandler.END

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.")
    return ConversationHandler.END

async def cb_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.message.reply_text("برای ادمین است.")
        return

    _, action, idx_s = q.data.split(":")
    idx = int(idx_s)

    if not (0 <= idx < len(PRODUCTS)):
        await q.message.reply_text("محصول یافت نشد.")
        return

    context.user_data["edit_idx"] = idx

    if action == "delete":
        p = PRODUCTS.pop(idx)
        await q.message.reply_text(f"حذف شد: {p['name']}")
        return

    if action == "editname":
        context.user_data["edit_field"] = "name"
        await q.message.reply_text("نام جدید را بفرستید:")
        return
    if action == "editprice":
        context.user_data["edit_field"] = "price"
        await q.message.reply_text("قیمت جدید (عدد) را بفرستید:")
        return
    if action == "editphoto":
        context.user_data["edit_field"] = "photo"
        await q.message.reply_text("عکس جدید را ارسال کنید:")
        return

async def any_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("edit_field")
    idx = context.user_data.get("edit_idx")
    if field and idx is not None and 0 <= idx < len(PRODUCTS):
        if field == "name":
            PRODUCTS[idx]["name"] = update.message.text.strip()
            await update.message.reply_text("✅ نام بروزرسانی شد.")
        elif field == "price":
            val = update.message.text.strip().replace(",", "")
            if not val.isdigit():
                await update.message.reply_text("قیمت باید عدد باشد.")
                return
            PRODUCTS[idx]["price"] = int(val)
            await update.message.reply_text("✅ قیمت بروزرسانی شد.")
        context.user_data.pop("edit_field", None)
        context.user_data.pop("edit_idx", None)
        return
    await show_main_menu(update, context)

async def any_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("edit_field")
    idx = context.user_data.get("edit_idx")
    if field == "photo" and idx is not None and 0 <= idx < len(PRODUCTS):
        photo = update.message.photo[-1] if update.message.photo else None
        if photo:
            PRODUCTS[idx]["photo_file_id"] = photo.file_id
            await update.message.reply_text("✅ عکس بروزرسانی شد.")
        context.user_data.pop("edit_field", None)
        context.user_data.pop("edit_idx", None)
        return
    await update.message.reply_text("عکس دریافت شد.")

def setup_handlers(app_: Application):
    app_.add_handler(CommandHandler("start", start_cmd))
    app_.add_handler(CallbackQueryHandler(cb_menu, pattern=r"^menu:"))
    app_.add_handler(CallbackQueryHandler(cb_wallet, pattern=r"^wallet:"))
    app_.add_handler(CallbackQueryHandler(cb_admin, pattern=r"^admin:(editname|editprice|editphoto|delete):\d+$"))

    add_flow = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_entry, pattern=r"^admin:add$")],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_name)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_price)],
            PHOTO: [
                MessageHandler(filters.PHOTO, admin_add_photo),
                CommandHandler("skip", admin_add_skip_photo),
            ],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
        name="add_product_flow",
        persistent=False,
    )
    app_.add_handler(add_flow)

    app_.add_handler(MessageHandler(filters.PHOTO, any_photo))
    app_.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_text))

@app.get("/")
def root():
    return "OK", 200

@app.get("/health")
def health():
    return "healthy", 200

@app.post(f"/webhook/{BOT_TOKEN}")
def telegram_webhook():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True)
        if not data:
            return Response(status=400)
        update = Update.de_json(data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        return Response(status=200)
    return Response(status=405)

def start_telegram():
    global application
    asyncio.set_event_loop(loop)
    application = Application.builder().token(BOT_TOKEN).build()
    setup_handlers(application)

    async def _init():
        await application.initialize()
        await application.start()
        await application.bot.set_webhook(
            url=f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}",
            drop_pending_updates=True,
        )
        log.info("Webhook set to %s/webhook/%s", WEBHOOK_URL, BOT_TOKEN)

    loop.run_until_complete(_init())
    threading.Thread(target=loop.run_forever, daemon=True).start()

start_telegram()
