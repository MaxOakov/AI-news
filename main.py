import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler

from app.config import TELEGRAM_TOKEN, MONGODB_URL, GEMINI_MODEL
from app.db.database import Database
from app.db.article_repository import ArticleRepository
from app.db.chat_repository import ChatRepository
from app.db.rss_link_repository import RssLinkRepository
from app.db.prompt_repository import PromptRepository
from app.services.rss_service import RssFeedService
from app.services.news_generator import NewsGenerator
from app.telegram_bot import TelegramBot
from app.news_pipeline import NewsPipeline
from app.scheduler import SchedulerService
from app.bot_commands import BotCommands

logging.basicConfig(level=logging.INFO)


def build_app():
    """Composition root: construct the full object graph explicitly.

    Every class in the app takes its dependencies through its constructor
    (a Database, a repository, a service, ...) instead of reaching into
    module-level singletons. This is the one place that wires them all
    together, in dependency order.
    """
    database = Database(MONGODB_URL)
    article_repository = ArticleRepository(database)
    chat_repository = ChatRepository(database)
    rss_link_repository = RssLinkRepository(database)
    prompt_repository = PromptRepository(database)

    rss_feed_service = RssFeedService(article_repository, rss_link_repository)
    news_generator = NewsGenerator(GEMINI_MODEL, prompt_repository)

    telegram_bot = TelegramBot(token=TELEGRAM_TOKEN, chat_repository=chat_repository)

    news_pipeline = NewsPipeline(rss_feed_service, news_generator, article_repository, telegram_bot)
    scheduler_service = SchedulerService(news_pipeline)

    bot_commands = BotCommands(telegram_bot, scheduler_service, rss_link_repository, prompt_repository)

    return telegram_bot, scheduler_service, bot_commands


async def main():
    """Initialize bot with scheduler."""
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not configured.")

    telegram_bot, scheduler_service, bot_commands = build_app()

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
