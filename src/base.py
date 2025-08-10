import os
import httpx

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

async def send_message(chat_id: int, text: str):
    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE_URL}/sendMessage", json={"chat_id": chat_id, "text": text})

async def send_photo(chat_id: int, photo_file_id: str, caption: str | None = None):
    async with httpx.AsyncClient() as client:
        payload = {"chat_id": chat_id, "photo": photo_file_id}
        if caption:
            payload["caption"] = caption
        await client.post(f"{BASE_URL}/sendPhoto", json=payload)
