from telegram import Bot
from app.config import TELEGRAM_TOKEN,TELEGRAM_CHAT_ID
import asyncio



bot = Bot(token=TELEGRAM_TOKEN)

async def send_all(news):
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=news, parse_mode="HTML")
    await asyncio.sleep(1)  # замість time.sleep — щоб не блокувати loop