from telegram import Bot
from app.config import TELEGRAM_TOKEN,TELEGRAM_CHAT_ID
import asyncio



bot = Bot(token=TELEGRAM_TOKEN)

async def send_telegram(news: str):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=news, parse_mode="HTML")
    except Exception as e:
        print(f"⚠️ Помилка при відправці Telegram: {e}")