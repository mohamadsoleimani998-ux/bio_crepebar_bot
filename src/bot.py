# src/bot.py
import os
from fastapi import FastAPI, Request

# حتماً ایمپورت نسبی باشد چون ما داخل پکیج src هستیم
from .handlers import handle_update
from .db import init_db  # برای ساخت جداول/ستون‌ها در استارتاپ

app = FastAPI()


@app.on_event("startup")
def _startup() -> None:
    """
    در شروع سرویس، اگر جدول‌ها/ستون‌ها وجود نداشته باشند ساخته می‌شوند.
    اگر خطا هم رخ بده، سرویس همچنان لایو می‌ماند و فقط در لاگ می‌بینیم.
    """
    try:
        init_db()
        print("DB init OK")
    except Exception as e:
        print("init_db error:", e)


@app.post("/webhook")
async def webhook(request: Request):
    """
    این همان مسیری‌ست که تلگرام به آن POST می‌زند.
    """
    update = await request.json()
    await handle_update(update)
    return {"ok": True}


@app.get("/")
async def root():
    return {"status": "bot is running"}
