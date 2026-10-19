import logging
import asyncio
from datetime import timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app import config
from app.config import (
    TELEGRAM_TOKEN, MONGODB_URL, GEMINI_MODEL, GEMINI_MODEL_OPTIONS, ENV_PATH, MAX_ARTICLE_AGE_HOURS,
)
from app.db.database import Database
from app.db.article_repository import ArticleRepository
from app.db.chat_repository import ChatRepository
from app.db.rss_link_repository import RssLinkRepository
from app.db.prompt_repository import PromptRepository
from app.db.instagram_post_repository import InstagramPostRepository
from app.services.rss_service import RssFeedService
from app.services.news_generator import NewsGenerator
from app.services.model_settings import GeminiModelSettings
from app.services.publisher import ArticlePublisher, REVIEW_CALLBACK_PREFIX
from app.services.image_host import R2ImageHost, make_r2_client
from app.services.instagram_client import InstagramClient
from app.services.page_image import PageImageFetcher
from app.instagram_forwarder import InstagramForwarder
from app.telegram_bot import TelegramBot
from app.news_pipeline import NewsPipeline
from app.scheduler import SchedulerService
from app.bot_commands import BotCommands, SET_MODEL_CALLBACK_PREFIX

logging.basicConfig(level=logging.INFO)

# Без цих налаштувань перенесення постів в Instagram вимкнене.
_INSTAGRAM_REQUIRED_SETTINGS = (
    "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID", "INSTAGRAM_SOURCE_CHAT_ID",
    "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL",
)


def build_instagram_forwarder(database, telegram_bot):
    """The Telegram → Instagram forwarder, or None if it isn't configured."""
    missing = [name for name in _INSTAGRAM_REQUIRED_SETTINGS if not getattr(config, name)]
    if missing:
        print(f"ℹ️ Перенесення в Instagram вимкнене, не задано: {', '.join(missing)}")
        return None

    image_host = R2ImageHost(
        make_r2_client(config.R2_ACCOUNT_ID, config.R2_ACCESS_KEY_ID, config.R2_SECRET_ACCESS_KEY),
        config.R2_BUCKET,
        config.R2_PUBLIC_BASE_URL,
    )
    instagram_client = InstagramClient(
        config.INSTAGRAM_USER_ID, config.INSTAGRAM_ACCESS_TOKEN, config.INSTAGRAM_API_BASE_URL
    )
    return InstagramForwarder(
        source_chat_id=config.INSTAGRAM_SOURCE_CHAT_ID,
        source_thread_id=config.INSTAGRAM_SOURCE_THREAD_ID,
        trigger_hashtag=config.INSTAGRAM_TRIGGER_HASHTAG,
        extra_hashtags=config.INSTAGRAM_EXTRA_HASHTAGS,
        post_repository=InstagramPostRepository(database),
        image_host=image_host,
        instagram_client=instagram_client,
        page_image_fetcher=PageImageFetcher(),
        telegram_bot=telegram_bot,
        notify_chat_id=config.INSTAGRAM_NOTIFY_CHAT_ID,
    )


def build_app():
    """Composition root: construct the full object graph explicitly.

    Every class in the app takes its dependencies through its constructor
    (a Database, a repository, a service, ...) instead of reaching into
    module-level singletons. This is the one place that wires them all
    together, in dependency order.
    """
    database = Database(MONGODB_URL)
    article_repository = ArticleRepository(database, max_article_age=timedelta(hours=MAX_ARTICLE_AGE_HOURS))
    chat_repository = ChatRepository(database)
    rss_link_repository = RssLinkRepository(database)
    prompt_repository = PromptRepository(database)

    rss_feed_service = RssFeedService(article_repository, rss_link_repository)
    news_generator = NewsGenerator(GEMINI_MODEL, prompt_repository)
    model_settings = GeminiModelSettings(news_generator, GEMINI_MODEL_OPTIONS, ENV_PATH)

    telegram_bot = TelegramBot(token=TELEGRAM_TOKEN, chat_repository=chat_repository)

    instagram_forwarder = build_instagram_forwarder(database, telegram_bot)
    publisher = ArticlePublisher(article_repository, news_generator, telegram_bot, instagram_forwarder)

    news_pipeline = NewsPipeline(rss_feed_service, news_generator, article_repository, telegram_bot, publisher)
    scheduler_service = SchedulerService(news_pipeline)

    bot_commands = BotCommands(
        telegram_bot, scheduler_service, rss_link_repository, prompt_repository, model_settings, publisher
    )

    return telegram_bot, scheduler_service, bot_commands, article_repository, instagram_forwarder


async def main():
    """Initialize bot with scheduler."""
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not configured.")

    telegram_bot, scheduler_service, bot_commands, article_repository, instagram_forwarder = build_app()

    # Created once at startup. A failure here shouldn't stop the bot: every
    # query still works without the indexes, just more slowly.
    try:
        await asyncio.to_thread(article_repository.ensure_indexes)
    except Exception as e:
        print(f"⚠️ Не вдалося створити індекси: {e}")
    if instagram_forwarder is not None:
        try:
            await asyncio.to_thread(instagram_forwarder.ensure_indexes)
        except Exception as e:
            print(f"⚠️ Не вдалося створити індекси для Instagram: {e}")

    # Load chats from DB
    await telegram_bot.load_chats_from_db()
    print(f"📋 Активні чати: {telegram_bot.chats}")

    # Setup Telegram bot handlers
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', bot_commands.start))
    application.add_handler(CommandHandler('runjob', bot_commands.run_job_now))
    application.add_handler(CommandHandler('news', bot_commands.run_job_now))
    application.add_handler(CommandHandler('settopic', bot_commands.set_topic_id))
    application.add_handler(CommandHandler('addrss', bot_commands.add_rss_link))
    application.add_handler(CommandHandler('removerss', bot_commands.remove_rss_link))
    application.add_handler(CommandHandler('listfeeds', bot_commands.list_rss_links))
    application.add_handler(CommandHandler('setprompt', bot_commands.set_prompt))
    application.add_handler(CommandHandler('resetprompt', bot_commands.reset_prompt))
    application.add_handler(CommandHandler('prompt', bot_commands.show_prompt))
    application.add_handler(CommandHandler('stop', bot_commands.stop))
    application.add_handler(CommandHandler('help', bot_commands.show_help))
    application.add_handler(CommandHandler('gemini_version', bot_commands.gemini_version))
    application.add_handler(CallbackQueryHandler(
        bot_commands.set_model_callback, pattern=f"^{SET_MODEL_CALLBACK_PREFIX}"
    ))
    application.add_handler(CommandHandler('moderation', bot_commands.moderation))
    application.add_handler(CallbackQueryHandler(
        bot_commands.review_callback, pattern=f"^{REVIEW_CALLBACK_PREFIX}"
    ))
    if instagram_forwarder is not None:
        # Окрема група: повідомлення гілки перевіряються незалежно від команд.
        application.add_handler(MessageHandler(
            filters.Chat(chat_id=int(config.INSTAGRAM_SOURCE_CHAT_ID)) & ~filters.UpdateType.EDITED,
            instagram_forwarder.handle,
        ), group=1)

    async def run_scheduler_background():
        """Run scheduler in background without blocking."""
        try:
            await scheduler_service.start()
        except asyncio.CancelledError:
            print("⏹ Планувальник зупинено.")
        except Exception as e:
            print(f"❌ Помилка планувальника: {e}")

    scheduler_task = None
    try:
        async with application:
            scheduler_task = asyncio.create_task(run_scheduler_background())
            await application.start()
            await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            try:
                await asyncio.Event().wait()
            finally:
                # Must stop updater/application before the `async with` block
                # exits and calls shutdown(), otherwise PTB raises
                # "This Application is still running!".
                if application.updater.running:
                    await application.updater.stop()
                if application.running:
                    await application.stop()
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    # Simple approach: just run asyncio directly
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹ Зупинено користувачем.")
