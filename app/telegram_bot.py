from telegram import Bot, LinkPreviewOptions
from telegram.error import BadRequest
from app.db.chat_repository import ChatRepository
from app.models import Chat
from app.retry import retry_async
import asyncio
import html
import re

_LINK_RE = re.compile(r"""<a\s[^>]*href=["']([^"']*)["'][^>]*>(.*?)</a>""", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_plain_text(text: str) -> str:
    """Strip HTML tags for a plain-text resend, keeping each link's URL
    (`<a href='URL'>label</a>` becomes `label (URL)`) so it isn't lost."""
    text = _LINK_RE.sub(lambda m: f"{m.group(2)} ({m.group(1)})", text)
    return html.unescape(_TAG_RE.sub("", text))


def _is_html_parse_error(exc: Exception) -> bool:
    """Telegram rejected the message's HTML markup (e.g. a tag Gemini
    produced that Telegram doesn't support, or one left unclosed)."""
    return isinstance(exc, BadRequest) and "parse entities" in str(exc).lower()


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
            active_chats = await asyncio.to_thread(self._chat_repository.get_all_active)
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

            # register() only writes message_thread_id to MongoDB when it's
            # set, and never writes reviewer_chat_id, so a plain /start after
            # /settopic or /moderation on doesn't clobber either one there.
            # Mirror that here: carry both over from what we already know
            # about this chat, whether it's cached in-memory or (e.g. after
            # /stop evicted it from the cache) still sitting in the database.
            async with self._chats_lock:
                existing = self.chats.get(chat.chat_id)
            if existing is None:
                existing = await asyncio.to_thread(self._chat_repository.get, chat.chat_id)
            if existing is not None:
                if chat.message_thread_id is None:
                    chat.message_thread_id = existing.message_thread_id
                chat.reviewer_chat_id = existing.reviewer_chat_id

            await asyncio.to_thread(self._chat_repository.register, chat)
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
            await asyncio.to_thread(self._chat_repository.deactivate, str(chat_id))
            async with self._chats_lock:
                self.chats.pop(str(chat_id), None)
            print(f"⏹ Чат деактивовано: {chat_id}")
            return True
        except Exception as e:
            print(f"❌ Помилка: {e}")
            return False

    async def set_reviewer(self, chat_id: str, reviewer_chat_id: str | None) -> bool:
        """Turn moderation on for a chat (drafts go to `reviewer_chat_id`)
        or off (None), in the DB and the in-memory cache."""
        chat_id = str(chat_id)
        reviewer_chat_id = str(reviewer_chat_id) if reviewer_chat_id is not None else None
        try:
            await asyncio.to_thread(self._chat_repository.set_reviewer, chat_id, reviewer_chat_id)
            async with self._chats_lock:
                chat = self.chats.get(chat_id)
                if chat is not None:
                    chat.reviewer_chat_id = reviewer_chat_id
            return True
        except Exception as e:
            print(f"❌ Не вдалося зберегти модератора для чату {chat_id}: {e}")
            return False

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        message_thread_id: int | None = None,
        link_preview_url: str | None = None,
        reply_markup=None,
    ) -> bool:
        """Send a message to a specific chat or forum topic.

        `link_preview_url` shows that URL (an image, or a page whose og:image
        Telegram picks up) as a large preview above the text, whether or not
        it appears in the text itself.
        """
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
        if link_preview_url:
            payload["link_preview_options"] = LinkPreviewOptions(
                url=link_preview_url, prefer_large_media=True, show_above_text=True
            )
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        try:
            await _send_once(self.bot, payload)
        except Exception as exc:
            if not (payload["parse_mode"] and _is_html_parse_error(exc)):
                return False
            # Resending the same markup would fail the same way, so retry
            # once as plain text instead of leaving the article unsent.
            print(f"⚠️ Telegram не прийняв HTML, надсилаємо як звичайний текст: {exc}")
            payload["text"] = _html_to_plain_text(text)
            payload["parse_mode"] = None
            try:
                await _send_once(self.bot, payload)
            except Exception:
                return False

        print(f"📨 Повідомлення надіслано в чат {chat_id} (topic: {message_thread_id})")
        return True