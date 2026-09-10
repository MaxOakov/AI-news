import asyncio

from app.db.article_repository import ArticleRepository
from app.services.rss_service import RssFeedService
from app.services.news_generator import NewsGenerator
from app.telegram_bot import TelegramBot


class NewsPipeline:
    """Orchestrates one full run: fetch each chat's RSS feeds, pick the
    newest unseen article, rewrite it via Gemini, and send it to the chat.

    Depends on the RSS, generation, persistence and Telegram layers through
    constructor injection rather than importing their singletons directly,
    so a run can be composed with different services (e.g. in a test).

    The RSS/persistence layers are synchronous (pymongo, feedparser), so
    their calls are offloaded via asyncio.to_thread rather than blocking
    the event loop; Gemini generation and Telegram sending are natively
    async. When processing every chat (chat_id=None), chats run
    concurrently, bounded by max_concurrent_chats.
    """

    def __init__(
        self,
        rss_feed_service: RssFeedService,
        news_generator: NewsGenerator,
        article_repository: ArticleRepository,
        telegram_bot: TelegramBot,
        max_concurrent_chats: int = 5,
    ):
        self._rss_feed_service = rss_feed_service
        self._news_generator = news_generator
        self._articles = article_repository
        self._telegram_bot = telegram_bot
        self._semaphore = asyncio.Semaphore(max_concurrent_chats)

    async def run(self, chat_id: str | None = None):
        """Run the job.

        If `chat_id` is given, only that chat is processed (used by the
        manual /runjob and /news commands so they don't affect every other
        chat). Otherwise every registered chat is processed concurrently
        (used by the hourly schedule).
        """
        if chat_id is not None:
            chat_id = str(chat_id)
            chat = self._telegram_bot.chats.get(chat_id)
            if chat is None:
                print(f"⚠️ Чат {chat_id} не зареєстрований. Спочатку викличте /start.")
                return
            await self._process_chat(chat_id, chat)
            return

        chats = list(self._telegram_bot.chats.items())
        results = await asyncio.gather(
            *(self._process_chat_bounded(cid, c) for cid, c in chats),
            return_exceptions=True,
        )
        for (cid, _), result in zip(chats, results):
            if isinstance(result, Exception):
                print(f"❌ Неочікувана помилка при обробці чату {cid}: {type(result).__name__}: {result}")

    async def _process_chat_bounded(self, chat_id, chat):
        """Run _process_chat for one chat, capped by the shared semaphore so
        a large number of chats can't overwhelm the thread pool or Telegram's
        per-bot rate limits when they're all processed at once."""
        async with self._semaphore:
            await self._process_chat(chat_id, chat)

    async def _process_chat(self, chat_id, chat):
        """Fetch feeds for one chat, pick an article, rewrite it, and send it."""
        rss_feeds = await asyncio.to_thread(self._rss_feed_service.get_feeds_for_chat, chat_id)
        if not rss_feeds:
            print(f"ℹ️ У чату {chat_id} немає RSS-лінків. Пропускаємо.")
            return

        await asyncio.to_thread(self._rss_feed_service.fetch_new_articles, chat_id, rss_feeds)
        selected_article = await asyncio.to_thread(self._articles.get_next_unsent, chat_id)
        if not selected_article:
            print(f"❌ Немає нових статей для відправки в чат {chat_id}")
            return

        print(f"✍️ Вибрана стаття для чату {chat_id}: '{selected_article.title}'")
        news_text = await self._news_generator.generate(selected_article, chat_id=chat_id)
        sent = await self._telegram_bot.send_message(
            chat_id,
            news_text,
            message_thread_id=chat.message_thread_id,
        )

        if sent:
            await asyncio.to_thread(self._articles.mark_as_sent, selected_article.id)
            print(f"📊 Відправлено в чат {chat_id}")
        else:
            print(f"❌ Не вдалося відправити статтю в чат {chat_id}")
