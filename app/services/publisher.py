import asyncio
import html
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.article_repository import ArticleRepository
from app.models import Article, Chat
from app.services.news_generator import NewsGenerator
from app.telegram_bot import TelegramBot

REVIEW_CALLBACK_PREFIX = "review:"

# Review actions, as they appear in callback_data ("review:<action>:<article id>").
# Kept short: Telegram caps callback_data at 64 bytes.
ACTION_PUBLISH = "pub"
ACTION_REGENERATE = "regen"
ACTION_SKIP = "skip"

# callback_data of the button that replaces a handled draft's keyboard.
REVIEW_DONE_CALLBACK = f"{REVIEW_CALLBACK_PREFIX}done"


@dataclass
class ReviewResult:
    """Outcome of a reviewer pressing a draft's button.

    `done`: the draft is dealt with, so its buttons should be replaced by
    `message`. Otherwise `message` explains what went wrong, and the
    buttons stay so the reviewer can try again.
    """

    message: str
    done: bool


def review_keyboard(article_id) -> InlineKeyboardMarkup:
    def button(label, action):
        return InlineKeyboardButton(label, callback_data=f"{REVIEW_CALLBACK_PREFIX}{action}:{article_id}")

    return InlineKeyboardMarkup([
        [button("✅ Опублікувати", ACTION_PUBLISH)],
        [button("🔄 Перегенерувати", ACTION_REGENERATE), button("❌ Пропустити", ACTION_SKIP)],
    ])


def review_done_keyboard(message: str) -> InlineKeyboardMarkup:
    """A single inert button showing how a draft was handled, so the
    reviewer can tell handled drafts apart when scrolling back."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(message, callback_data=REVIEW_DONE_CALLBACK)]])


class ArticlePublisher:
    """Delivers a generated post: straight to its chat, or, if the chat has
    moderation on, as a draft to the chat's reviewer, who then publishes,
    regenerates or skips it with the draft's inline buttons.

    Every post goes out with a large link preview above the text: the feed
    entry's image if it has one, else the article page.
    """

    def __init__(self, article_repository: ArticleRepository, news_generator: NewsGenerator, telegram_bot: TelegramBot):
        self._articles = article_repository
        self._news_generator = news_generator
        self._telegram_bot = telegram_bot

    async def publish(self, chat_id: str, chat: Chat, article: Article, text: str) -> bool:
        """Post `text` to the chat, or send it to the chat's reviewer as a
        draft. A failed send counts toward skipping the article."""
        if chat.reviewer_chat_id:
            sent = await self._send_draft(chat.reviewer_chat_id, chat, article, text)
        else:
            sent = await self._send_to_chat(chat_id, chat, article, text)

        if not sent:
            print(f"❌ Не вдалося відправити статтю в чат {chat_id}")
            await asyncio.to_thread(self._articles.record_failure, article)
        return sent

    async def _send_to_chat(self, chat_id: str, chat: Chat, article: Article, text: str) -> bool:
        sent = await self._telegram_bot.send_message(
            chat_id,
            text,
            message_thread_id=chat.message_thread_id,
            link_preview_url=article.preview_url,
        )
        if sent:
            await asyncio.to_thread(self._articles.mark_as_sent, article.id)
            print(f"📊 Відправлено в чат {chat_id}")
        return sent

    async def _send_draft(self, reviewer_chat_id: str, chat: Chat, article: Article, text: str) -> bool:
        header = f"📝 Чернетка для «{html.escape(chat.chat_name)}»:\n\n"
        sent = await self._telegram_bot.send_message(
            reviewer_chat_id,
            header + text,
            link_preview_url=article.preview_url,
            reply_markup=review_keyboard(article.id),
        )
        if sent:
            await asyncio.to_thread(self._articles.mark_pending_review, article.id, reviewer_chat_id, text)
            print(f"📝 Чернетку для чату {chat.chat_id} надіслано модератору {reviewer_chat_id}")
        return sent

    async def handle_review(self, action: str, article_id: str, reviewer_chat_id: str) -> ReviewResult:
        """Apply a reviewer's button press to the draft of `article_id`.

        Only the reviewer the draft was sent to may act on it, and each
        draft can be handled once: pressing a button again after it was
        published or skipped just reports that.
        """
        article = await asyncio.to_thread(self._articles.get_by_id, article_id)
        if article is None or article.review_chat_id != str(reviewer_chat_id):
            return ReviewResult("⚠️ Чернетку не знайдено", done=True)
        if article.is_sent:
            return ReviewResult("✅ Вже опубліковано", done=True)
        if article.skipped:
            return ReviewResult("❌ Вже пропущено", done=True)

        if action == ACTION_SKIP:
            await asyncio.to_thread(self._articles.mark_skipped, article.id)
            return ReviewResult("❌ Пропущено", done=True)

        chat = self._telegram_bot.chats.get(str(article.chat_id))
        if chat is None:
            return ReviewResult("⚠️ Чат відписаний від новин. Увімкніть його знову через /start.", done=False)

        if action == ACTION_PUBLISH:
            if await self._send_to_chat(article.chat_id, chat, article, article.draft_text or ""):
                return ReviewResult("✅ Опубліковано", done=True)
            return ReviewResult("❌ Не вдалося опублікувати. Спробуйте ще раз.", done=False)

        if action == ACTION_REGENERATE:
            text = await self._news_generator.generate(article, chat_id=article.chat_id)
            if text is None:
                return ReviewResult("⚠️ Gemini не повернув текст. Спробуйте ще раз.", done=False)
            # A fresh draft message (rather than editing this one) goes
            # through send_message's HTML fallback like any other post.
            if await self._send_draft(article.review_chat_id, chat, article, text):
                return ReviewResult("🔄 Перегенеровано — нова чернетка нижче", done=True)
            return ReviewResult("❌ Не вдалося надіслати нову чернетку. Спробуйте ще раз.", done=False)

        return ReviewResult("⚠️ Невідома дія", done=False)
