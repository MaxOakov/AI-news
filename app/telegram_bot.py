from telegram import Bot
from app.config import TELEGRAM_TOKEN,TELEGRAM_CHAT_ID
import asyncio



bot = Bot(token=TELEGRAM_TOKEN)

async def send_telegram(news: str):
    retry_count = 0
    max_retries = 3
    while retry_count < max_retries:
        try:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=news, parse_mode="HTML")
            print("📨 Повідомлення успішно надіслано в Telegram.")
            return
        except Exception as e:
            retry_count += 1
            print(f"⚠️ Помилка при відправці Telegram (спроба {retry_count}): {e}")
            await asyncio.sleep(2)  # Затримка перед повторною спробою