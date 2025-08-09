# base.py
import os
import json
import asyncio
import threading
from flask import Flask, request, abort, Response

from telegram import Update
from telegram.ext import Application

# ───────────────────
# تنظیمات از متغیرهای محیطی
# ───────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_BASE = os.environ.get("WEBHOOK_BASE", "").rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
PORT = int(os.environ.get("PORT", "10000"))  # Render معمولاً این پورت رو Bind می‌کنه

# URL نهایی وبهوک (بدون اسلش اضافه در انتها)
WEBHOOK_URL = f"{WEBHOOK_BASE}/{BOT_TOKEN}/{WEBHOOK_SECRET}"

# ───────────────────
# حلقه‌ی رویداد جداگانه برای PTB
# ───────────────────
_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, name="ptb-loop", daemon=True)
_loop_thread.start()

# اپلیکیشن تلگرام (Global و پایدار)
application = (
    Application.builder()
    .token(BOT_TOKEN)
    .concurrent_updates(True)   # برای اطمینان از پردازش همزمان
    .build()
)

# اینجا فقط ثبت هندلرها انجام می‌شود (کد در handlers.py است)
def _register_handlers() -> None:
    from handlers import register_handlers  # import داخل تابع برای جلوگیری از چرخه
    register_handlers(application)

# استارت و ست‌کردن وبهوک داخل حلقه‌ی اختصاصی
async def _ptb_startup():
    _register_handlers()
    await application.initialize()
    await application.start()
    # ست کردن وبهوک با هدر Secret (مسیر هم برای سازگاری نگه داشته شده)
    await application.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
        drop_pending_updates=True,
    )

# یک‌بار در بوت برنامه، PTB را بالا می‌آوریم
asyncio.run_coroutine_threadsafe(_ptb_startup(), _loop)

# ───────────────────
# Flask app و مسیرها
# ───────────────────
app = Flask(__name__)

@app.get("/")
def health():
    return "OK", 200

# مسیر وبهوک دقیقا مطابق چیزی که الان لایو بود:
#   /<BOT_TOKEN>/<WEBHOOK_SECRET>
@app.post(f"/{BOT_TOKEN}/{WEBHOOK_SECRET}")
def telegram_webhook():
    # اعتبارسنجی هدر Secret (برای سازگاری اگر Secret خالی بود، چک نکن)
    if WEBHOOK_SECRET:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header_secret != WEBHOOK_SECRET:
            abort(403)

    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        abort(400)

    # ساخت Update و ارسال برای پردازش در حلقه‌ی PTB
    try:
        update = Update.de_json(data, application.bot)
        fut = asyncio.run_coroutine_threadsafe(
            application.process_update(update), _loop
        )
        # منتظر شدن کوتاه برای گرفتن Exception احتمالی (بلوک نشه)
        fut.result(timeout=0.01)
    except Exception:
        # لاگ 200 برگرده تا تلگرام ریترای بی‌مورد نکنه
        return Response(status=200)

    return Response(status=200)
