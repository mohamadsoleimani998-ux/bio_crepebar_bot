# src/bot.py
from __future__ import annotations

import json
from fastapi import FastAPI, Request

# چون این فایل داخل بسته‌ی src اجرا می‌شود، import نسبی درست است
from .handlers import handle_update, startup_warmup
from .db import init_db

app = FastAPI()


@app.on_event("startup")
async def on_startup():
    """
    در استارتاپ، ساخت/به‌روزرسانی امن جداول و یک warmup سبک
    برای مطمئن شدن از اتصال DB و سلامت هندلرها.
    """
    try:
        init_db()
        print("DB init OK")
    except Exception as e:
        # خطا در init_db باعث کرش نشود
        print("init_db error:", e)

    try:
        # اگر در handlers تعریف شده، warmup اجرا می‌شود
        await startup_warmup()
        print("startup warmup OK")
    except Exception as e:
        print("startup_warmup error:", e)


@app.post("/webhook")
async def webhook(request: Request):
    """
    همان endpoint قبلی؛ فقط با لاگ بهتر و محافظت در برابر خطا تا سرویس لایو بماند.
    """
    try:
        update = await request.json()
    except Exception:
        # fallback اگر json() خطا داد
        body = await request.body()
        update = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)

    try:
        await handle_update(update)
    except Exception as e:
        # هیچوقت 500 نده که Render لایف‌نس رو fail کنه
        print("handle_update error:", e)

    return {"ok": True}


@app.get("/")
async def root():
    return {"status": "bot is running"}
