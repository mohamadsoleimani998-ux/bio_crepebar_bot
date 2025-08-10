import os
import json
from fastapi import FastAPI, Request

from handlers import handle_update
from db import init_db  # 🆕 برای ساخت خودکار جدول‌ها

app = FastAPI()


@app.on_event("startup")
def _startup():
    # با استارت سرویس، جداول اگر نبودن ساخته می‌شن
    init_db()


@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}


@app.get("/")
async def root():
    return {"status": "bot is running"}
