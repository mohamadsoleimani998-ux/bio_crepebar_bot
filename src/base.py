import os
import requests
from typing import Iterable, Tuple

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

def _safe(params: dict) -> dict:
    return {k: v for k, v in params.items() if v is not None}

def _log(msg: str):
    print("[base]", msg)

async def send_message(chat_id: int, text: str):
    # اگر توکن نبود، فقط لاگ تا سرویس نخوابه
    if not API:
        _log(f"send_message skipped (no BOT_TOKEN). chat_id={chat_id}, text={text!r}")
        return
    try:
        requests.post(f"{API}/sendMessage", json=_safe({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }), timeout=10)
    except Exception as e:
        _log(f"send_message error: {e}")

async def send_menu(chat_id: int):
    txt = (
        "سلام! به ربات خوش آمدید.\n"
        "دستورات: /wallet ، /products\n"
        "اگر ادمین هستید، برای افزودن محصول بعداً گزینه ادمین اضافه می‌کنیم."
    )
    await send_message(chat_id, txt)

def set_my_commands(pairs: Iterable[Tuple[str, str]]):
    if not API:
        _log("set_my_commands skipped (no BOT_TOKEN).")
        return
    try:
        commands = [{"command": c, "description": d} for c, d in pairs]
        requests.post(f"{API}/setMyCommands", json={"commands": commands}, timeout=10)
    except Exception as e:
        _log(f"set_my_commands error: {e}")
