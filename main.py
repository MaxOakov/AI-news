import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from app.telegram_bot import telegram_bot
from app.config import TELEGRAM_TOKEN
from app.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start - register chat in DB."""
    chat_id = str(update.effective_chat.id)
    chat_name = update.effective_chat.title or update.effective_user.first_name
    chat_type = update.effective_chat.type
    
    await telegram_bot.register_chat_db(chat_id, chat_name, chat_type)
    await update.message.reply_text(f"✅ Привіт! Я зареєстрований для чату: {chat_name}")


async def main():
    """Initialize bot with scheduler."""
    # Load chats from DB
    await telegram_bot.load_chats_from_db()
    print(f"📋 Активні чати: {telegram_bot.chats}")
    
    # Setup Telegram bot handlers
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    
    # Start scheduler in background task
    async def run_scheduler_background():
        """Run scheduler in background without blocking."""
        try:
            await start_scheduler()
        except asyncio.CancelledError:
            print("⏹ Планувальник зупинено.")
        except Exception as e:
            print(f"❌ Помилка планувальника: {e}")
    
    async with application:
        # Start scheduler as background task
        scheduler_task = asyncio.create_task(run_scheduler_background())
        
        # Run polling with close_loop=False to prevent event loop closure
        await application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            close_loop=False
        )
        
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