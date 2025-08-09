import os
import httpx

TOKEN = os.getenv("BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"

async def send_message(chat_id: int, text: str):
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            f"{API}/sendMessage",
            json={"chat_id": chat_id, "text": text}
        )
