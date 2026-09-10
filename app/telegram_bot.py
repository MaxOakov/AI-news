from telegram import Bot
from app.db.chat_repository import ChatRepository
from app.models import Chat
from app.retry import retry_async
import asyncio


@retry_async(
    max_retries=3,
    delay=2,
    on_retry=lambda exc, attempt, total, bot, payload: print(
        f"⚠️ Помилка при відправці (спроба {attempt}/{total}): {exc}"
    ),
)
async def _send_once(bot: Bot, payload: dict):
    await bot.send_message(**payload)


class TelegramBot:
    def __init__(self, token: str, chat_repository: ChatRepository):
        self.token = token
        self.bot = Bot(token=token) if token else None
        self.chats: dict[str, Chat] = {}
        self._chats_lock = asyncio.Lock()
        self._chat_repository = chat_repository

    async def load_chats_from_db(self):
        """Load all active chats from MongoDB on startup."""
        try:
            active_chats = self._chat_repository.get_all_active()
            async with self._chats_lock:
                self.chats.clear()
                for chat in active_chats:
                    self.chats[chat.chat_id] = chat
            print(f"✅ Завантажено {len(self.chats)} чатів з БД")
        except Exception as e:
            print(f"❌ Помилка при завантаженні чатів: {e}")

    async def register_chat_db(self, chat_id: str, chat_name: str, chat_type: str = "private", message_thread_id: int | None = None):
        """Register chat in DB and add to memory."""
        try:
            chat = Chat(
                chat_id=str(chat_id),
                chat_name=chat_name,
                chat_type=chat_type,
                message_thread_id=message_thread_id,
            )

            if chat.message_thread_id is None:
                # register() only writes message_thread_id to MongoDB when
                # it's set, so a plain /start after /settopic doesn't
                # clobber the stored topic id there. Mirror that here: don't
                # let a None from this call erase a topic id we already
                # know about, whether it's cached in-memory or (e.g. after
                # /stop evicted this chat from the cache) still sitting in
                # the database.
                async with self._chats_lock:
                    existing = self.chats.get(chat.chat_id)
                if existing is not None:
                    chat.message_thread_id = existing.message_thread_id
                else:
                    stored = self._chat_repository.get(chat.chat_id)
                    if stored is not None:
                        chat.message_thread_id = stored.message_thread_id

            self._chat_repository.register(chat)
            async with self._chats_lock:
                self.chats[chat.chat_id] = chat
            print(f"✅ Чат додано: {chat_name} ({chat_id})")
            return True
        except Exception as e:
            print(f"❌ Помилка: {e}")
            return False

    async def deactivate_chat_db(self, chat_id: str) -> bool:
        """Deactivate a chat in DB and drop it from the in-memory cache.

        Unlike register_chat_db, this doesn't touch a chat's stored RSS
        links or custom prompt, so a later /start reactivates it with
        everything intact.
        """
        try:
            self._chat_repository.deactivate(str(chat_id))
            async with self._chats_lock:
                self.chats.pop(str(chat_id), None)
            print(f"⏹ Чат деактивовано: {chat_id}")
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

        try:
            await _send_once(self.bot, payload)
        except Exception:
            return False

        print(f"📨 Повідомлення надіслано в чат {chat_id} (topic: {message_thread_id})")
        return True

    async def send_to_all_chats(self, text: str, parse_mode: str = "HTML") -> dict:
        """Broadcast message to all active chats, using topic id when available."""
        async with self._chats_lock:
            chat_items = list(self.chats.items())

        results = {}
        for chat_id, chat in chat_items:
            results[chat_id] = await self.send_message(
                chat_id,
                text,
                parse_mode,
                message_thread_id=chat.message_thread_id,
            )
        return results