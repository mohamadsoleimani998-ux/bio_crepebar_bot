import os
import httpx
from fastapi import FastAPI, Request
from .handlers import handle_update

TOKEN = os.getenv("BOT_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

app = FastAPI()

@app.on_event("startup")
async def on_startup():
    # در صورت تنظیم PUBLIC_URL، وبهوک را روی /webhook ست می‌کنیم
    if TOKEN and PUBLIC_URL:
        url = f"{PUBLIC_URL}/webhook"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://api.telegram.org/bot{TOKEN}/setWebhook",
                    params={"url": url}
                )
                print("setWebhook:", r.text)
        except Exception as e:
            # اگر ست نشد هم سرویس بالا می‌آید
            print("setWebhook error:", e)

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        update = {}
    await handle_update(update)
    return {"ok": True}

# سازگاری با مسیر قدیمی اگر قبلاً وبهوک روی /<TOKEN> بوده
if TOKEN:
    @app.post(f"/{TOKEN}")
    async def webhook_token(request: Request):
        try:
            update = await request.json()
        except Exception:
            update = {}
        await handle_update(update)
        return {"ok": True}

@app.get("/")
async def root():
    return {"status": "ok"}
