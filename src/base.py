import os
import httpx

TOKEN = os.getenv("BOT_TOKEN")
API = f"https://api.telegram.org/bot{TOKEN}"

async def send_message(chat_id: int, text: str):
    if not TOKEN:
        print("BOT_TOKEN is missing")
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{API}/sendMessage", json={"chat_id": chat_id, "text": text})
