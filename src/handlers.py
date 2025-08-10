import os
import httpx

# ایمپورت‌های داخلی پروژه (نسبی تا خطای ModuleNotFound پیش نیاد)
from .base import send_message
from .db import get_or_create_user, list_products, add_product

# برای ارسال عکس بدون دست‌زدن به base.py
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# ادمین‌ها از env (لیست آیدی‌ها با کاما)
_ADMIN_IDS = {i.strip() for i in os.getenv("ADMIN_IDS", "").split(",") if i.strip()}
# نگهداری وضعیت کوتاه‌مدت افزودن محصول برای ادمین‌ها (در حافظه)
_ADMIN_STATE = {}  # tg_id -> "await_photo"


async def _send_photo(chat_id: int, file_id: str, caption: str | None = None):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            await client.post(
                API_URL + "sendPhoto",
                json={"chat_id": chat_id, "photo": file_id, "caption": caption},
            )
    except Exception as e:
        print("sendPhoto error:", e)


def _is_admin(tg_id: int) -> bool:
    return str(tg_id) in _ADMIN_IDS


def _fmt_toman(cents: int) -> str:
    # ما داخل DB برحسب «سنت» ذخیره می‌کنیم؛ برای نمایش تومان تقسیم بر 100
    return f"{cents // 100:,} تومان"


async def handle_update(update: dict):
    """
    فقط روی همون رفتارهای قبلی سوار شده‌ایم:
    - /start : خوش‌آمد + نمایش دستورات
    - /wallet : ساخت/بازیابی کاربر و نمایش موجودی (نیاز به ستون wallet_cents که init_db تضمین می‌کند)
    - /products : لیست محصولات (عکس‌دار یا بدون عکس)
    - /addproduct : فقط ادمین → ارسال عکس با کپشن «عنوان | قیمت_به_تومان»
    هیچ چیز دیگری تغییر نکرده و ربات لایو می‌ماند.
    """
    try:
        if "message" not in update:
            return  # فقط پیام‌های متنی/عکس را مدیریت می‌کنیم

        msg = update["message"]
        chat_id = msg["chat"]["id"]
        tg_id = msg.get("from", {}).get("id")

        text = msg.get("text")
        photo = msg.get("photo")  # لیست سایزها
        caption = msg.get("caption", "")

        # اطمینان از ساخت کاربر و ستون‌ها (اگر نبود بسازد)
        try:
            user = get_or_create_user(tg_id)
        except Exception as e:
            print("get_or_create_user err:", e)
            await send_message(chat_id, "خطا در بازیابی/ایجاد کاربر.")
            return

        # --- دستورات متنی
        if text:
            if text.startswith("/start"):
                await send_message(
                    chat_id,
                    "سلام! به ربات خوش آمدید.\n"
                    "دستورات:\n"
                    "• /products — لیست محصولات\n"
                    "• /wallet — موجودی کیف پول",
                )
                return

            if text.startswith("/wallet"):
                try:
                    user = get_or_create_user(tg_id)
                    bal = user.get("wallet_cents", 0)
                    await send_message(chat_id, f"موجودی کیف پول: {_fmt_toman(bal)}")
                except Exception as e:
                    print("wallet err:", e)
                    await send_message(chat_id, "خطا در بازیابی کیف پول.")
                return

            if text.startswith("/products"):
                try:
                    items = list_products()
                    if not items:
                        await send_message(chat_id, "فعلاً محصولی ثبت نشده است.")
                        return
                    # برای جلوگیری از اسپم، هر محصول را جدا می‌فرستیم
                    for p in items:
                        cap = f"{p['title']} — {_fmt_toman(p['price_cents'])}"
                        file_id = p.get("photo_file_id")
                        if file_id:
                            await _send_photo(chat_id, file_id, cap)
                        else:
                            await send_message(chat_id, cap)
                except Exception as e:
                    print("products err:", e)
                    await send_message(chat_id, "خطا در دریافت لیست محصولات.")
                return

            if text.startswith("/addproduct"):
                if not _is_admin(tg_id):
                    await send_message(chat_id, "شما دسترسی ادمین ندارید.")
                    return
                _ADMIN_STATE[tg_id] = "await_photo"
                await send_message(
                    chat_id,
                    "عکس محصول را ارسال کنید و در کپشن به شکل «عنوان | قیمت_به_تومان» بنویسید.",
                )
                return

        # --- افزودن محصول با عکس (فقط برای ادمین و وقتی دستور فعال شده باشد)
        if photo and _ADMIN_STATE.get(tg_id) == "await_photo" and _is_admin(tg_id):
            if "|" not in caption:
                await send_message(chat_id, "قالب کپشن صحیح نیست. «عنوان | قیمت»")
                return
            title, price_txt = [s.strip() for s in caption.split("|", 1)]
            try:
                price_cents = int(price_txt.replace(",", "")) * 100
            except ValueError:
                await send_message(chat_id, "قیمت نامعتبر است.")
                return

            # بزرگ‌ترین سایز عکس را برداریم
            file_id = photo[-1]["file_id"]
            try:
                add_product(title, price_cents, file_id)
                await send_message(chat_id, "محصول با موفقیت ذخیره شد ✅")
            except Exception as e:
                print("add_product err:", e)
                await send_message(chat_id, "خطا در ذخیره‌سازی محصول.")
            finally:
                _ADMIN_STATE.pop(tg_id, None)
            return

        # اگر هیچ‌کدام نبود، ساکت باش تا لایوی ربات حفظ شود
        return

    except Exception as e:
        # هر خطای غیرمنتظره‌ای لاگ شود ولی مانع پاسخ 200 نشود
        print("handle_update fatal:", e)
        return
