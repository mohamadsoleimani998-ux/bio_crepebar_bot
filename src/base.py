import os
import httpx

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}/"

async def send_message(chat_id, text):
    async with httpx.AsyncClient() as client:
        await client.post(BASE_URL + "sendMessage", json={
            "chat_id": chat_id,
            "text": text
        })
