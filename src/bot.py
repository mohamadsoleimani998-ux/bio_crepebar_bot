import os
from fastapi import FastAPI, Request
from handlers import handle_update

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# مسیر وبهوک دقیقا مطابق چیزی که در تلگرام ست شده
if WEBHOOK_SECRET:
    WEBHOOK_PATH = f"/{BOT_TOKEN}/{WEBHOOK_SECRET}"
else:
    WEBHOOK_PATH = f"/{BOT_TOKEN}"

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running", "webhook_path": WEBHOOK_PATH}
