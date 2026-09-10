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
    """

    def __init__(
        self,
        rss_feed_service: RssFeedService,
        news_generator: NewsGenerator,
        article_repository: ArticleRepository,
        telegram_bot: TelegramBot,
    ):
        self._rss_feed_service = rss_feed_service
        self._news_generator = news_generator
        self._articles = article_repository
        self._telegram_bot = telegram_bot

    async def run(self, chat_id: str | None = None):
        """Run the job.

        If `chat_id` is given, only that chat is processed (used by the
        manual /runjob and /news commands so they don't affect every other
        chat). Otherwise every registered chat is processed (used by the
        hourly schedule).
        """
        if chat_id is not None:
            chat_id = str(chat_id)
            chat = self._telegram_bot.chats.get(chat_id)
            if chat is None:
                print(f"⚠️ Чат {chat_id} не зареєстрований. Спочатку викличте /start.")
                return
            await self._process_chat(chat_id, chat)
            return

        for chat_id, chat in list(self._telegram_bot.chats.items()):
            await self._process_chat(chat_id, chat)

    async def _process_chat(self, chat_id, chat):
        """Fetch feeds for one chat, pick an article, rewrite it, and send it."""
        rss_feeds = self._rss_feed_service.get_feeds_for_chat(chat_id)
        if not rss_feeds:
            print(f"ℹ️ У чату {chat_id} немає RSS-лінків. Пропускаємо.")
            return

        self._rss_feed_service.fetch_new_articles(chat_id, rss_feeds)
        selected_article = self._articles.get_next_unsent(chat_id)
        if not selected_article:
            print(f"❌ Немає нових статей для відправки в чат {chat_id}")
            return

        print(f"✍️ Вибрана стаття для чату {chat_id}: '{selected_article.title}'")
        news_text = self._news_generator.generate(selected_article, chat_id=chat_id)
        sent = await self._telegram_bot.send_message(
            chat_id,
            news_text,
            message_thread_id=chat.message_thread_id,
        )

        if sent:
            self._articles.mark_as_sent(selected_article.id)
            print(f"📊 Відправлено в чат {chat_id}")
        else:
            print(f"❌ Не вдалося відправити статтю в чат {chat_id}")
