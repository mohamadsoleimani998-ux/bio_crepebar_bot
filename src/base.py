# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import logging
from decimal import Decimal
from typing import Iterable, Set

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("crepebar")

def _env(name: str, default=None, required: bool = False):
    val = os.environ.get(name, default)
    if required and (val is None or str(val).strip() == ""):
        raise RuntimeError(f"{name} is not set")
    return val

def _parse_admin_ids(val: str | None) -> Set[int]:
    if not val:
        return set()
    parts: Iterable[str] = [p.strip() for p in val.replace("؛", ",").replace(" ", ",").split(",")]
    out: Set[int] = set()
    for p in parts:
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            log.warning("ADMIN_IDS contains non-numeric value: %r", p)
    return out

def fmt_money(n: int | float | Decimal) -> str:
    try:
        v = int(Decimal(n))
        return f"{v:,} تومان"
    except Exception:
        return f"{n} تومان"

def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS

# ---------- ENV ----------
DATABASE_URL: str = _env("DATABASE_URL", required=True)

BOT_TOKEN: str = _env("BOT_TOKEN", default=_env("TELEGRAM_TOKEN"), required=True)

PUBLIC_URL: str = _env("PUBLIC_URL", default=_env("WEBHOOK_BASE", default="")).rstrip("/")

WEBHOOK_SECRET: str = _env("WEBHOOK_SECRET", default="T3legramWebhookSecret_2025")
WEBHOOK_PATH: str = _env("WEBHOOK_PATH", default="/telegram-webhook")
WEBHOOK_URL: str | None = _env("WEBHOOK_URL", default=None) or (f"{PUBLIC_URL}{WEBHOOK_PATH}" if PUBLIC_URL else None)

ADMIN_IDS = _parse_admin_ids(_env("ADMIN_IDS", default=""))

try:
    CASHBACK_PERCENT: int = int(str(_env("CASHBACK_PERCENT", default="3")).strip())
except Exception:
    CASHBACK_PERCENT = 3

# کارت به کارت (اختیاری – برای پیام راهنما)
CARD_PAN  = _env("CARD_PAN",  default="****-****-****-****")
CARD_NAME = _env("CARD_NAME", default="دارنده کارت")
CARD_NOTE = _env("CARD_NOTE", default="پس از واریز، رسید را همین‌جا ارسال کنید.")

CURRENCY = "تومان"
PAGE_SIZE = 6

# دسته‌های منو (slug, title)
CATEGORIES: list[tuple[str, str]] = [
    ("espresso", "اسپرسو بار گرم و سرد"),
    ("tea", "چای و دمنوش"),
    ("mixhot", "ترکیبی گرم"),
    ("mocktail", "موکتل ها"),
    ("sky", "اسمونی ها"),
    ("cold", "خنک"),
    ("dami", "دمی"),
    ("crepe", "کرپ"),
    ("pancake", "پنکیک"),
    ("diet", "رژیمی ها"),
    ("matcha", "ماچا بار"),
]
