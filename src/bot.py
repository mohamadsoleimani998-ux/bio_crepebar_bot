import os
import json
import asyncio
from fastapi import FastAPI, Request, Response

from telegram import Update
from telegram.ext import Application

# اطمینان از مقداردهی env
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env is missing")

# ساخت اپ تلگرام
application = Application.builder().token(BOT_TOKEN).build()

# هندلرها
from src.handlers import setup as setup_handlers
setup_handlers(application)

# FastAPI
app = FastAPI()

@app.on_event("startup")
async def on_startup():
    # ست کردن وبهوک روی Render public URL
    if PUBLIC_URL:
        await application.bot.set_webhook(url=f"{PUBLIC_URL.rstrip('/')}/webhook")
    # اجرای worker تلگرام
    asyncio.create_task(application.initialize())
    asyncio.create_task(application.start())

@app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return Response(status_code=200)

# برای تست سلامت
@app.get("/")
async def root():
    return {"ok": True}
