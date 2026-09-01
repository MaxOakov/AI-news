from telegram import Bot
from app.config import TELEGRAM_TOKEN
from app.mongo import register_chat, get_all_active_chats
import asyncio


class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.bot = Bot(token=token)
        self.chats = {}
        self.max_retries = 3
    
    async def load_chats_from_db(self):
        """Load all active chats from MongoDB on startup."""
        try:
            active_chats = get_all_active_chats()
            for chat in active_chats:
                self.chats[chat["chat_id"]] = chat["chat_name"]
            print(f"✅ Завантажено {len(self.chats)} чатів з БД")
        except Exception as e:
            print(f"❌ Помилка при завантаженні чатів: {e}")
    
    async def register_chat_db(self, chat_id: str, chat_name: str, chat_type: str = "private"):
        """Register chat in DB and add to memory."""
        try:
            register_chat(str(chat_id), chat_name, chat_type)
            self.chats[str(chat_id)] = chat_name
            print(f"✅ Чат додано: {chat_name} ({chat_id})")
            return True
        except Exception as e:
            print(f"❌ Помилка: {e}")
            return False
    
    async def send_message(
        self, 
        chat_id: str, 
        text: str, 
        parse_mode: str = "HTML"
    ) -> bool:
        """Send message to specific chat."""
        retry_count = 0
        while retry_count < self.max_retries:
            try:
                await self.bot.send_message(
                    chat_id=chat_id, 
                    text=text, 
                    parse_mode=parse_mode
                )
                print(f"📨 Повідомлення надіслано в чат {chat_id}")
                return True
            except Exception as e:
                retry_count += 1
                print(f"⚠️ Помилка при відправці (спроба {retry_count}): {e}")
                if retry_count < self.max_retries:
                    await asyncio.sleep(2)
        return False
    
    async def send_to_all_chats(self, text: str, parse_mode: str = "HTML") -> dict:
        """Broadcast message to all active chats."""
        results = {}
        for chat_id in self.chats:
            results[chat_id] = await self.send_message(chat_id, text, parse_mode)
        return results


telegram_bot = TelegramBot(token=TELEGRAM_TOKEN)