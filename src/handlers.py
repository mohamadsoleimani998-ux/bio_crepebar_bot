from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
import os
from dotenv import load_dotenv
from .db import (
    init_db, set_admins, get_or_create_user, get_wallet, list_products, add_product
)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

async def handle_update(update: dict):
    tg_update = types.Update.to_object(update)
    await dp.process_update(tg_update)

async def startup_warmup():
    await set_admins()

@dp.message_handler(commands=['start'])
async def cmd_start(message: Message):
    user = await get_or_create_user(
        tg_id=message.from_user.id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )
    await message.answer(f"سلام {user.first_name}، خوش اومدی!")

@dp.message_handler(commands=['wallet'])
async def cmd_wallet(message: Message):
    wallet = await get_wallet(message.from_user.id)
    await message.answer(f"موجودی کیف پول شما: {wallet.balance} تومان")

@dp.message_handler(commands=['products'])
async def cmd_products(message: Message):
    products = await list_products()
    if not products:
        await message.answer("هیچ محصولی ثبت نشده است.")
    else:
        text = "\n".join([f"{p.name} - {p.price} تومان" for p in products])
        await message.answer(text)
