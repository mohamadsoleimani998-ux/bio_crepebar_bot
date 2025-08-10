import os
from fastapi import FastAPI, Request

# ایمپورت نسبی تا با ساختار پکیج src سازگار باشه
from .handlers import handle_update
from .db import init_db  # این فقط یک بار در استارتاپ اجرا می‌شود

app = FastAPI()


@app.on_event("startup")
async def _startup():
    # اگر جدول/ستون‌ها نبودند، بساز (ایمن برای چندبار اجرا)
    try:
        init_db()
    except Exception as e:
        print("DB init error:", e)


# روت سلامت برای Render (۲۰۰ OK) — نیاز داشتیم که 404 نشه
@app.get("/")
async def root():
    return {"ok": True, "status": "running"}


# وبهوک عمومی (اگر بعداً URL را /webhook ست کردی)
@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}


# وبهوک مبتنی بر توکن (اگر قبلاً با /{BOT_TOKEN} ست کردی)
_bot_token = os.getenv("BOT_TOKEN", "")
if _bot_token:
    @app.post(f"/{_bot_token}")
    async def webhook_with_token(request: Request):
        update = await request.json()
        await handle_update(update)
        return {"ok": True}
