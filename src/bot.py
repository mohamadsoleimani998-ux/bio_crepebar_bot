import os
from fastapi import FastAPI, Request
import httpx
from handlers import handle_update

app = FastAPI()

TOKEN = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "webhook").strip()

# مسیر اصلی وبهوک (جدید و ساده)
@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

# برای سازگاری با مسیر قدیمی (توکن/سکرت) که قبلاً تلگرام بهش می‌زد
@app.post(f"/{TOKEN}/{WEBHOOK_SECRET}")
async def webhook_legacy(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}

@app.on_event("startup")
async def set_webhook():
    """
    در استارت‌اپ، وبهوک تلگرام را روی مسیر ساده /webhook ست می‌کنیم
    تا mismatch از بین بره. اگر PUBLIC_URL خالی بود، کاری نمی‌کنیم.
    """
    if not (TOKEN and PUBLIC_URL):
        return

    url = f"{PUBLIC_URL}/webhook"
    async with httpx.AsyncClient(timeout=10) as client:
        # ابتدا وبهوک قبلی را پاک می‌کنیم تا 404 های قدیمی باقی نمانند
        await client.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")
        # سپس وبهوک جدید را ست می‌کنیم
        await client.post(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            json={"url": url},
        )
