# src/bot.py
import os
from fastapi import FastAPI, Request
from typing import Any, Dict

# وارد کردن نسبی از داخل پکیج src
from .handlers import handle_update
from .db import ensure_schema

app = FastAPI()


@app.on_event("startup")
async def on_startup() -> None:
    """
    هنگام بالا آمدن سرویس:
    - اسکیمای دیتابیس را (اگر لازم بود) می‌سازد/به‌روز می‌کند.
    """
    try:
        await ensure_schema()
    except Exception as e:
        # لاگ ساده؛ Render لاگ‌ها را نشان می‌دهد
        print(f"[startup] ensure_schema error: {e}")


@app.post("/{token}")
async def webhook_with_token(token: str, request: Request) -> Dict[str, Any]:
    """
    وبهوک با مسیر شامل توکن.
    اگر توکن با BOT_TOKEN یکی نبود، درخواست نادیده گرفته می‌شود.
    """
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token or token != bot_token:
        return {"ok": True}  # بی‌صدا نادیده بگیر

    update = await request.json()
    try:
        await handle_update(update)
    except Exception as e:
        print(f"[webhook_with_token] handle_update error: {e}")
    return {"ok": True}


@app.post("/webhook")
async def webhook_plain(request: Request) -> Dict[str, Any]:
    """
    وبهوک ساده برای زمانی که آدرس `/webhook` ست شده.
    """
    update = await request.json()
    try:
        await handle_update(update)
    except Exception as e:
        print(f"[webhook_plain] handle_update error: {e}")
    return {"ok": True}


@app.get("/")
async def root() -> Dict[str, Any]:
    return {"status": "bot is running"}
