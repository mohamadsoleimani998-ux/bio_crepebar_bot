from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
from dotenv import load_dotenv
from .handlers import handle_update, startup_warmup
from .db import init_db

load_dotenv()

app = FastAPI()

@app.on_event("startup")
async def startup():
    await init_db()
    await startup_warmup()

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
        await handle_update(update)
        return JSONResponse(content={"ok": True})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/")
async def root():
    return {"status": "ok"}
