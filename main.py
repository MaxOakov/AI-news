import logging
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.config import (
    TELEGRAM_TOKEN, MONGODB_URL, GEMINI_MODEL, GEMINI_MODEL_OPTIONS, MAX_ARTICLE_AGE_HOURS,
    SECRETS_ENCRYPTION_KEY, INSTAGRAM_GRAPH_API_VERSION,
)
from app.db.database import Database
from app.db.article_repository import ArticleRepository
from app.db.chat_repository import ChatRepository
from app.db.rss_link_repository import RssLinkRepository
from app.db.prompt_repository import PromptRepository
from app.db.chat_model_repository import ChatModelRepository
from app.db.instagram_post_repository import InstagramPostRepository
from app.db.instagram_settings_repository import InstagramSettingsRepository
from app.services.rss_service import RssFeedService
from app.services.news_generator import NewsGenerator
from app.services.model_settings import GeminiModelSettings
from app.services.publisher import ArticlePublisher, REVIEW_CALLBACK_PREFIX
from app.services.secret_box import SecretBox
from app.services.instagram_settings import InstagramSettingsService
from app.services.instagram_connector import InstagramConnector
from app.services.page_image import PageImageFetcher
from app.instagram_forwarder import InstagramForwarder
from app.telegram_bot import TelegramBot
from app.news_pipeline import NewsPipeline
from app.scheduler import SchedulerService
from app.bot_commands import BotCommands, SET_MODEL_CALLBACK_PREFIX
from app.setup_commands import SetupCommands, SETUP_DEEP_LINK_PREFIX

logging.basicConfig(level=logging.INFO)
# httpx logs every request's full URL at INFO: Telegram's carry the bot token
# (api.telegram.org/bot<token>/...), Graph API ones an access_token parameter.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@dataclass
class App:
    telegram_bot: TelegramBot
    scheduler_service: SchedulerService
    bot_commands: BotCommands
    setup_commands: SetupCommands
    article_repository: ArticleRepository
    instagram_settings: InstagramSettingsService
    instagram_forwarder: InstagramForwarder


def build_secret_box(key: str | None) -> SecretBox | None:
    """The box Instagram/R2 secrets are encrypted with, or None (Instagram
    then can't be set up, but the rest of the bot works as usual)."""
    try:
        secret_box = SecretBox.from_env(key)
    except ValueError:
        print("❌ SECRETS_ENCRYPTION_KEY некоректний — Instagram недоступний, доки його не виправлено.")
        return None
    if secret_box is None:
        print("ℹ️ SECRETS_ENCRYPTION_KEY не задано — Instagram у чатах налаштувати не вийде.")
    return secret_box


def build_app() -> App:
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
    model_settings = GeminiModelSettings(ChatModelRepository(database), GEMINI_MODEL_OPTIONS, GEMINI_MODEL)
    news_generator = NewsGenerator(model_settings, prompt_repository)

    telegram_bot = TelegramBot(token=TELEGRAM_TOKEN, chat_repository=chat_repository)

    instagram_settings = InstagramSettingsService(
        InstagramSettingsRepository(database, build_secret_box(SECRETS_ENCRYPTION_KEY))
    )
    instagram_connector = InstagramConnector(INSTAGRAM_GRAPH_API_VERSION)
    instagram_forwarder = InstagramForwarder(
        instagram_settings, InstagramPostRepository(database), instagram_connector, PageImageFetcher(), telegram_bot
    )
    publisher = ArticlePublisher(article_repository, news_generator, telegram_bot, instagram_forwarder)

    news_pipeline = NewsPipeline(rss_feed_service, news_generator, article_repository, telegram_bot, publisher)
    scheduler_service = SchedulerService(news_pipeline)

    setup_commands = SetupCommands(telegram_bot, rss_link_repository, instagram_settings, instagram_connector)
    bot_commands = BotCommands(
        telegram_bot, scheduler_service, rss_link_repository, prompt_repository, model_settings, publisher,
        setup_commands,
    )

    return App(
        telegram_bot=telegram_bot,
        scheduler_service=scheduler_service,
        bot_commands=bot_commands,
        setup_commands=setup_commands,
        article_repository=article_repository,
        instagram_settings=instagram_settings,
        instagram_forwarder=instagram_forwarder,
    )


async def main():
    """Initialize bot with scheduler."""
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not configured.")

    app = build_app()
    telegram_bot, scheduler_service, bot_commands = app.telegram_bot, app.scheduler_service, app.bot_commands
    setup_commands = app.setup_commands

    # Created once at startup. A failure here shouldn't stop the bot: every
    # query still works without the indexes, just more slowly.
    for ensure_indexes in (
        app.article_repository.ensure_indexes,
        app.instagram_forwarder.ensure_indexes,
        app.instagram_settings.ensure_indexes,
    ):
        try:
            await asyncio.to_thread(ensure_indexes)
        except Exception as e:
            print(f"⚠️ Не вдалося створити індекси: {e}")

    # Load chats from DB
    await telegram_bot.load_chats_from_db()
    print(f"📋 Активні чати: {telegram_bot.chats}")
    try:
        await app.instagram_settings.load()
    except Exception as e:
        print(f"⚠️ Не вдалося завантажити налаштування Instagram: {e}")

    # Setup Telegram bot handlers
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    # Before the plain /start: the deep link from a group's /setup button
    # opens setup in the private chat instead of subscribing it to news.
    application.add_handler(CommandHandler(
        'start', setup_commands.start_from_link,
        filters=filters.ChatType.PRIVATE & filters.Regex(f"^/start {SETUP_DEEP_LINK_PREFIX}"),
    ))
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
    application.add_handler(CommandHandler('setup', setup_commands.setup))
    application.add_handler(CommandHandler('ig_account', setup_commands.ig_account))
    application.add_handler(CommandHandler('ig_r2', setup_commands.ig_r2))
    application.add_handler(CommandHandler('ig_track', setup_commands.ig_track))
    application.add_handler(CommandHandler('ig_tags', setup_commands.ig_tags))
    application.add_handler(CommandHandler('ig_topic', setup_commands.ig_topic))
    application.add_handler(CommandHandler('ig_reset', setup_commands.ig_reset))
    # Окрема група: повідомлення чатів перевіряються незалежно від команд;
    # forwarder сам відкидає чати, де Instagram не налаштовано.
    application.add_handler(MessageHandler(
        (filters.ChatType.GROUPS | filters.ChatType.CHANNEL) & ~filters.UpdateType.EDITED,
        app.instagram_forwarder.handle,
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
