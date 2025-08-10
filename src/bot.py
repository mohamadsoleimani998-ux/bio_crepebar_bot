# src/bot.py
import os
import json
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from handlers import handle_update
from db import ensure_schema, ensure_user

app = FastAPI()

# هنگام بالا آمدن سرویس، اسکیما را می‌سازیم (ایمن و بدون قطع سرویس)
@app.on_event("startup")
async def _startup():
    await run_in_threadpool(ensure_schema)

@app.post(f"/{{os.getenv('BOT_TOKEN')}}")
async def webhook(request: Request):
    update = await request.json()

    # قبل از پاسخ، کاربر را در DB ایمن می‌کنیم (بدون بلاک کردن loop)
    try:
        if "message" in update and "from" in update["message"]:
            f = update["message"]["from"]
            await run_in_threadpool(
                ensure_user,
                int(f["id"]),
                f.get("username"),
                f.get("first_name")
            )
    except Exception:
        # اگر DB در دسترس نبود، اجازه نمی‌دهیم پاسخ‌دهی تلگرام قطع شود.
        pass

    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}
