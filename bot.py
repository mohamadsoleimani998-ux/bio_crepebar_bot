import os, re, asyncio, logging
from typing import Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from aiohttp import web

# -------- Logging --------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bio-crepebar-bot")

# -------- Config --------
TOKEN = os.environ.get("TELEGRAM_TOKEN")            # تو Render ست کن
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
PORT = int(os.environ.get("PORT", "10000"))

# -------- Data (in-memory) --------
products: Dict[str, int] = {
    "اسپرسو ۷۰ روبوستا": 80000,
    "اسپرسو ۷۰ عربیکا": 84000,
    "اسپرسو ۱۰۰ عربیکا": 96000,
}
users: Dict[int, Dict] = {}   # {uid: {"wallet":int, "name":str|None, "phone":str|None}}
cashback_percent = 3

# -------- Helpers --------
EMOJI_RE = re.compile(r'[\u200d\uFE0F\u2600-\u27BF\U0001F300-\U0001FAFF]+')
def norm(s: str) -> str:
    return EMOJI_RE.sub("", s or "").replace(" ", "").strip()
def is_admin(uid: int) -> bool: return uid in ADMIN_IDS

def main_menu():
    return ReplyKeyboardMarkup(
        [["☕ منوی محصولات", "👤 حساب من"],
         ["💸 کیف پول", "🎁 تخفیف"],
         ["📲 اینستاگرام", "▶️ یوتیوب"]],
        resize_keyboard=True
    )

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن محصول", callback_data="admin:add")],
        [InlineKeyboardButton("✏️ تغییر قیمت", callback_data="admin:edit")],
        [InlineKeyboardButton("🗑 حذف محصول", callback_data="admin:remove")],
        [InlineKeyboardButton("💸 تنظیم کش‌بک", callback_data="admin:cashback")],
        [InlineKeyboardButton("📋 لیست محصولات", callback_data="admin:list")],
        [InlineKeyboardButton("⬅️ خروج", callback_data="admin:exit")],
    ])

# -------- Commands --------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    users.setdefault(uid, {"wallet": 0, "name": None, "phone": None})
    await update.message.reply_text("به بایو کرپ بار خوش اومدی ☕️\nچطور می‌تونم کمکت کنم؟", reply_markup=main_menu())

async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"ID شما: `{u.id}`\nUsername: @{u.username}", parse_mode="Markdown")

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("⛔️ دسترسی مدیریت ندارید.")
    await update.message.reply_text("پنل مدیریت:", reply_markup=admin_kb())

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("دستورات: /start /whoami /admin\nاز دکمه‌ها هم می‌تونی استفاده کنی.")

# -------- Admin callbacks/text --------
async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return await q.edit_message_text("⛔️ دسترسی ندارید.")
    data = q.data.split(":")[1]

    if data == "list":
        if products:
            lines = [f"• {n} — {p:,} تومان" for n, p in products.items()]
            return await q.edit_message_text("📋 محصولات:\n" + "\n".join(lines), reply_markup=admin_kb())
        return await q.edit_message_text("لیست محصولات خالی است.", reply_markup=admin_kb())

    context.user_data["admin_mode"] = data
    tips = {
        "add": "➕ «نام - قیمت» (مثال: لاته - 120000)",
        "edit": "✏️ «نام - قیمت جدید»",
        "remove": "🗑 فقط «نام محصول»",
        "cashback": "💸 فقط عدد (مثال: 3)",
    }.get(data, "دستور نامعتبر.")
    await q.edit_message_text(tips, reply_markup=admin_kb())

async def admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    mode = context.user_data.get("admin_mode")
    if not mode: return
    text = (update.message.text or "").strip()
    global cashback_percent
    try:
        if mode == "add":
            name, price = [x.strip() for x in text.split(" - ", 1)]
            if not price.isdigit(): raise ValueError
            products[name] = int(price)
            await update.message.reply_text(f"✅ «{name}» اضافه شد.", reply_markup=admin_kb())
        elif mode == "edit":
            name, price = [x.strip() for x in text.split(" - ", 1)]
            if not price.isdigit() or name not in products: raise ValueError
            products[name] = int(price)
            await update.message.reply_text("✅ قیمت تغییر کرد.", reply_markup=admin_kb())
        elif mode == "remove":
            if text not in products: raise KeyError
            products.pop(text)
            await update.message.reply_text("🗑 حذف شد.", reply_markup=admin_kb())
        elif mode == "cashback":
            if not text.isdigit(): raise ValueError
            cashback_percent = int(text)
            await update.message.reply_text(f"✅ کش‌بک {cashback_percent}% شد.", reply_markup=admin_kb())
    except Exception:
        await update.message.reply_text("فرمت درست نیست. نمونه‌ها:\nنام - 120000\nیا فقط نام برای حذف\nیا فقط عدد برای کش‌بک")
    finally:
        context.user_data.pop("admin_mode", None)

# -------- Public --------
async def public_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    users.setdefault(uid, {"wallet": 0, "name": None, "phone": None})

    text = (update.message.text or "")
    key  = norm(text)
    log.info("INCOMING %s: %r -> %s", uid, text, key)

    if "منویمحصولات" in key:
        msg = "📋 لیست محصولات:\n" + "\n".join([f"• {n} – {p:,} تومان" for n, p in products.items()])
        msg += f"\n\n🎁 کش‌بک فعال: {cashback_percent}%"
        return await update.message.reply_text(msg)

    if "حسابمن" in key:
        u = users[uid]
        if not u.get("name") or not u.get("phone"):
            return await update.message.reply_text("نام - شماره را بفرست (مثال: علی - 0912...)")
        return await update.message.reply_text(f"نام: {u['name']}\nشماره: {u['phone']}\nموجودی: {u['wallet']:,} تومان")

    if " - " in text and (users[uid]["name"] is None or users[uid]["phone"] is None):
        try:
            name, phone = [p.strip() for p in text.split(" - ", 1)]
            users[uid]["name"], users[uid]["phone"] = name, phone
            return await update.message.reply_text("✅ اطلاعات ثبت شد.")
        except:  # noqa
            return await update.message.reply_text("فرمت نادرست. مثال: علی - 0912...")

    if "کیفپول" in key:
        bal = users[uid]["wallet"]
        return await update.message.reply_text(f"💰 موجودی: {bal:,} تومان\nبرای شارژ، مبلغ را عددی بفرست.")

    if "تخفیف" in key:
        return await update.message.reply_text(f"🎉 روی هر خرید {cashback_percent}% کش‌بک فعال است.")

    if "اینستاگرام" in key:
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("Instagram", url="https://www.instagram.com/bio.crepebar")]])
        return await update.message.reply_text("صفحه ما:", reply_markup=btn)

    if "یوتیوب" in key or "youtube" in key:
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("YouTube", url="https://www.youtube.com/")]])
        return await update.message.reply_text("کانال یوتیوب:", reply_markup=btn)

    if text.isdigit():
        amount = int(text)
        if amount > 0:
            users[uid]["wallet"] += amount
            return await update.message.reply_text(f"✅ {amount:,} تومان به کیف پول اضافه شد.")
        return await update.message.reply_text("مبلغ نامعتبر است.")

    return await update.message.reply_text("از دکمه‌ها استفاده کن یا /help را ببین.", reply_markup=main_menu())

# -------- Inline (اختیاری) --------
async def inline_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "menu":
        msg = "📋 لیست محصولات:\n" + "\n".join([f"• {n} – {p:,} تومان" for n, p in products.items()])
        msg += f"\n\n🎁 کش‌بک: {cashback_percent}%"
        await q.edit_message_text(msg)
    elif q.data == "wallet":
        uid = q.from_user.id
        bal = users.get(uid, {"wallet": 0})["wallet"]
        await q.edit_message_text(f"💰 موجودی: {bal:,} تومان")

# -------- Run (polling + health) --------
async def run():
    if not TOKEN: raise RuntimeError("TELEGRAM_TOKEN env var missing")

    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("help", cmd_help))

    # Admin + Public
    app.add_handler(CallbackQueryHandler(admin_buttons, pattern=r"^admin:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text))
    app.add_handler(CallbackQueryHandler(inline_menu, pattern=r"^(menu|wallet)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, public_text))

    # Health server (Render)
    async def health(_): return web.Response(text="ok")
    web_app = web.Application()
    web_app.add_routes([web.get("/", health), web.get("/health", health)])
    runner = web.AppRunner(web_app); await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)

    # ترتیب صحیح + ضد-Conflict
    await app.initialize()
    await site.start()
    await app.start()
    await app.bot.delete_webhook(drop_pending_updates=True)   # مهم
    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop(); await app.stop(); await app.shutdown()

if __name__ == "__main__":
    asyncio.run(run())
