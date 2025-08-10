import os
import httpx

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# یک کلاینت کم‌مصرف برای درخواست‌ها
_client = httpx.AsyncClient(timeout=15)

def _reply_kb(button_rows):
    # ساختار reply_keyboard برای تلگرام
    return {"keyboard": button_rows, "resize_keyboard": True, "one_time_keyboard": False}

def main_menu_kb(is_admin: bool):
    rows = [
        [{"text": "🍽 منو"}, {"text": "🛒 ثبت سفارش"}],
        [{"text": "💼 کیف پول"}],
    ]
    if is_admin:
        rows.append([{"text": "➕ افزودن محصول"}])
    return _reply_kb(rows)

def inline_products_kb(products):
    # برای ثبت سفارش با دکمه‌های اینلاین
    # هر دکمه دیتا به صورت "order:<id>" می‌فرستد
    kb = []
    row = []
    for i, p in enumerate(products, start=1):
        row.append({
            "text": f"{p['title']} - {p['price_t']} تومان",
            "callback_data": f"order:{p['id']}"
        })
        if i % 2 == 0:
            kb.append(row); row = []
    if row:
        kb.append(row)
    return {"inline_keyboard": kb}

async def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    await _client.post(f"{API_BASE}/sendMessage", json=payload)

async def answer_callback_query(cb_id: str, text: str = ""):
    await _client.post(f"{API_BASE}/answerCallbackQuery", json={
        "callback_query_id": cb_id,
        "text": text
    })
