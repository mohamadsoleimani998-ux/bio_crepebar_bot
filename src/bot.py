import os
import json
import httpx
from fastapi import FastAPI, Request
from handlers import handle_update

app = FastAPI()

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# آدرس پابلیک سرویس (اولویت با PUBLIC_URL، بعد RENDER_EXTERNAL_URL)
PUBLIC_URL = os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")


@app.on_event("startup")
async def setup_webhook():
    """در شروع اجرا، وبهوک را روی مسیر امن ست می‌کند."""
    if not (TOKEN and WEBHOOK_SECRET and PUBLIC_URL):
        # اگر چیزی کم بود، فقط لاگ داخلی؛ برنامه همچنان بالا می‌آید.
        return
    url = f"{PUBLIC_URL.rstrip('/')}/{WEBHOOK_SECRET}"
    set_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(set_url, json={"url": url})
        except Exception:
            # از کار نیفتد اگر ست وبهوک خطا داد
            pass


@app.post(f"/{WEBHOOK_SECRET}")
async def webhook(request: Request):
    update = await request.json()
    # پردازش پیام
    await handle_update(update)
    return {"ok": True}


@app.get("/")
async def root():
    return {"status": "bot is running"}
