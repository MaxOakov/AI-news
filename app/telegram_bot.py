from telegram import Bot
from app.config import TELEGRAM_TOKEN
from app.mongo import register_chat, get_all_active_chats
import asyncio


class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.bot = Bot(token=token) if token else None
        self.chats = {}
        self.max_retries = 3
        self._chats_lock = asyncio.Lock()

    async def load_chats_from_db(self):
        """Load all active chats from MongoDB on startup."""
        try:
            active_chats = get_all_active_chats()
            async with self._chats_lock:
                self.chats.clear()
                for chat in active_chats:
                    chat_id = str(chat["chat_id"])
                    self.chats[chat_id] = {
                        "chat_name": chat.get("chat_name") or "Unknown chat",
                        "message_thread_id": chat.get("message_thread_id")
                    }
            print(f"✅ Завантажено {len(self.chats)} чатів з БД")
        except Exception as e:
            print(f"❌ Помилка при завантаженні чатів: {e}")

    async def register_chat_db(self, chat_id: str, chat_name: str, chat_type: str = "private", message_thread_id: int | None = None):
        """Register chat in DB and add to memory."""
        try:
            register_chat(str(chat_id), chat_name, chat_type, message_thread_id)
            async with self._chats_lock:
                self.chats[str(chat_id)] = {
                    "chat_name": chat_name,
                    "message_thread_id": message_thread_id
                }
            print(f"✅ Чат додано: {chat_name} ({chat_id})")
            return True
        except Exception as e:
            print(f"❌ Помилка: {e}")
            return False

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        message_thread_id: int | None = None,
    ) -> bool:
        """Send a message to a specific chat or forum topic."""
        if self.bot is None:
            print("❌ TELEGRAM_TOKEN is not configured. Message not sent.")
            return False

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if message_thread_id not in (None, ""):
            try:
                payload["message_thread_id"] = int(message_thread_id)
            except (TypeError, ValueError):
                payload.pop("message_thread_id", None)

        retry_count = 0
        while retry_count < self.max_retries:
            try:
                await self.bot.send_message(**payload)
                print(f"📨 Повідомлення надіслано в чат {chat_id} (topic: {message_thread_id})")
                return True
            except Exception as e:
                retry_count += 1
                print(f"⚠️ Помилка при відправці (спроба {retry_count}): {e}")
                if retry_count < self.max_retries:
                    await asyncio.sleep(2)
        return False

    async def send_to_all_chats(self, text: str, parse_mode: str = "HTML") -> dict:
        """Broadcast message to all active chats, using topic id when available."""
        async with self._chats_lock:
            chat_items = list(self.chats.items())

        results = {}
        for chat_id, chat_data in chat_items:
            message_thread_id = chat_data.get("message_thread_id") if isinstance(chat_data, dict) else None
            if message_thread_id in (None, ""):
                message_thread_id = None
            results[chat_id] = await self.send_message(
                chat_id,
                text,
                parse_mode,
                message_thread_id=message_thread_id,
            )
        return results


telegram_bot = TelegramBot(token=TELEGRAM_TOKEN)