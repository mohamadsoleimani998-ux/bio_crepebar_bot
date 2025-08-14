# src/base.py
import os
import logging

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("crepebar")

# ---------- Env & constants ----------
# لیست ادمین‌ها: با کاما جدا کنید
_admin_env = os.environ.get("ADMIN_IDS", "").strip()
ADMIN_IDS = set()
for x in _admin_env.replace("؛", ",").replace(" ", "").split(","):
    if x.isdigit():
        ADMIN_IDS.add(int(x))

# واحد پول (نمایشی)
CURRENCY = "تومان"

# اطلاعات کارت برای شارژ کارت‌به‌کارت (اختیاری)
CARD_PAN   = os.environ.get("CARD_PAN", "6037-xxxx-xxxx-xxxx")
CARD_NAME  = os.environ.get("CARD_NAME", "به نام فروشگاه")
CARD_NOTE  = os.environ.get("CARD_NOTE", "لطفاً پس از واریز، رسید را ارسال کنید.")

# ---------- Helpers ----------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def fmt_money(n) -> str:
    try:
        f = float(n or 0)
    except Exception:
        f = 0.0
    s = f"{int(round(f)):,}".replace(",", "٬")
    return f"{s} {CURRENCY}"

def chunk_buttons(items, row=2):
    for i in range(0, len(items), row):
        yield items[i:i+row]
