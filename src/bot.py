from fastapi import FastAPI, Request
from src.handlers import handle_update

app = FastAPI()

@app.post("/{token}")
async def webhook(request: Request, token: str):
    update = await request.json()
    await handle_update(update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "bot is running"}
