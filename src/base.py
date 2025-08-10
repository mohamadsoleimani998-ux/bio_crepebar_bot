import os
import httpx

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}/"

async def send_message(chat_id: int, text: str):
    if not TOKEN:
        # اگر توکن نبود، بی‌سروصدا برگرد تا دپلوی کرش نکند
        return
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            BASE_URL + "sendMessage",
            json={"chat_id": chat_id, "text": text}
        )
