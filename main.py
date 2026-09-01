import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from app.telegram_bot import telegram_bot
from app.config import TELEGRAM_TOKEN
from app.scheduler import start_scheduler, trigger_job_now
from app.mongo import save_rss_link, get_chat_rss_links, save_chat_prompt, reset_chat_prompt, get_chat_prompt, get_prompt_for_chat

logging.basicConfig(level=logging.INFO)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start - register chat in DB."""
    if update.effective_chat is None:
        return

    chat_id = str(update.effective_chat.id)
    chat_name = update.effective_chat.title or (update.effective_user.first_name if update.effective_user else "Unknown user")
    chat_type = update.effective_chat.type
    message_thread_id = update.message.message_thread_id if update.message is not None else None

    await telegram_bot.register_chat_db(chat_id, chat_name, chat_type, message_thread_id)
    if update.message is not None:
        await update.message.reply_text(f"✅ Привіт! Я зареєстрований для чату: {chat_name}")


async def run_job_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Instantly trigger the news job from a Telegram command."""
    if update.effective_chat is None:
        return

    started = await trigger_job_now()
    if started:
        text = "✅ Новий запуск новин розпочато вручну."
    else:
        text = "⏸ Попередній запуск новин ще виконується або задача не доступна зараз."

    if update.message is not None:
        await update.message.reply_text(text)


async def set_topic_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or update the current forum topic id for this chat."""
    if update.effective_chat is None or update.message is None:
        return

    chat_id = str(update.effective_chat.id)
    chat_name = update.effective_chat.title or (update.effective_user.first_name if update.effective_user else "Unknown user")
    chat_type = update.effective_chat.type
    message_thread_id = update.message.message_thread_id

    if message_thread_id is None:
        await update.message.reply_text("⚠️ Ця команда працює лише в темі/форумах. Відправте її в темі, а не в основному чаті.")
        return

    success = await telegram_bot.register_chat_db(chat_id, chat_name, chat_type, message_thread_id)
    if success:
        await update.message.reply_text(f"✅ Для чату встановлено topic_id={message_thread_id}")
    else:
        await update.message.reply_text("❌ Не вдалося зберегти topic_id.")


async def add_rss_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add one or more comma-separated RSS URLs for the current chat."""
    if update.effective_chat is None or update.message is None:
        return

    if not context.args:
        await update.message.reply_text(
            "Використання: /addrss https://example.com/rss, https://example.org/feed"
        )
        return

    rss_urls = []
    for value in " ".join(context.args).split(","):
        rss_url = value.strip()
        if rss_url and rss_url not in rss_urls:
            rss_urls.append(rss_url)

    invalid_urls = [
        rss_url for rss_url in rss_urls
        if not rss_url.startswith(("http://", "https://"))
    ]
    if invalid_urls:
        await update.message.reply_text(
            "❌ Некоректні RSS URL (мають починатися з http:// або https://):\n"
            + "\n".join(invalid_urls)
        )
        return

    chat_id = str(update.effective_chat.id)
    for rss_url in rss_urls:
        save_rss_link(chat_id, rss_url)

    await update.message.reply_text(
        f"✅ Збережено RSS-лінків для цього чату: {len(rss_urls)}\n"
        + "\n".join(rss_urls)
    )


async def list_rss_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all active RSS links stored for the current chat."""
    if update.effective_chat is None or update.message is None:
        return

    chat_id = str(update.effective_chat.id)
    links = get_chat_rss_links(chat_id)
    if not links:
        await update.message.reply_text("📭 Для цього чату не збережено жодного RSS-лінка.")
        return

    formatted = "\n".join(f"- {item['url']}" for item in links)
    await update.message.reply_text(f"📚 RSS для цього чату:\n{formatted}")


async def set_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set a custom prompt for the current chat."""
    if update.effective_chat is None or update.message is None:
        return

    if not context.args:
        await update.message.reply_text("Використання: /setprompt <текст промпту>")
        return

    custom_prompt = " ".join(context.args)
    chat_id = str(update.effective_chat.id)
    save_chat_prompt(chat_id, custom_prompt)
    await update.message.reply_text("✅ Користувацький prompt для цього чату збережено. Тепер він буде використовуватися замість prompt.txt.")


async def reset_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset the custom prompt for the current chat and use the default one again."""
    if update.effective_chat is None or update.message is None:
        return

    chat_id = str(update.effective_chat.id)
    reset_chat_prompt(chat_id)
    await update.message.reply_text("✅ Користувацький prompt скинуто. Знову використовується prompt.txt.")


async def show_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the active prompt for the current chat."""
    if update.effective_chat is None or update.message is None:
        return

    chat_id = str(update.effective_chat.id)
    active_prompt = get_prompt_for_chat(chat_id)
    preview = active_prompt[:800] + ("..." if len(active_prompt) > 800 else "")
    await update.message.reply_text(f"📝 Активний prompt для цього чату:\n\n{preview}")


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the available bot commands and their descriptions."""
    if update.message is None:
        return

    help_text = (
        "📖 Доступні команди:\n\n"
        "/start — зареєструвати цей чат у боті\n"
        "/help — показати список команд\n"
        "/runjob — негайно запустити обробку новин\n"
        "/news — те саме, що /runjob\n"
        "/settopic — встановити поточну тему форуму для надсилання новин\n"
        "/addrss <url1>, <url2> — додати один або кілька RSS-лінків для цього чату\n"
        "/listfeeds — показати RSS-лінки цього чату\n"
        "/setprompt <текст> — зберегти власний prompt для цього чату\n"
        "/resetprompt — повернути використання стандартного prompt.txt\n"
        "/prompt — показати активний prompt цього чату"
    )
    await update.message.reply_text(help_text)


async def main():
    """Initialize bot with scheduler."""
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not configured.")

    # Load chats from DB
    await telegram_bot.load_chats_from_db()
    print(f"📋 Активні чати: {telegram_bot.chats}")

    # Setup Telegram bot handlers
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('runjob', run_job_now))
    application.add_handler(CommandHandler('news', run_job_now))
    application.add_handler(CommandHandler('settopic', set_topic_id))
    application.add_handler(CommandHandler('addrss', add_rss_link))
    application.add_handler(CommandHandler('listfeeds', list_rss_links))
    application.add_handler(CommandHandler('setprompt', set_prompt))
    application.add_handler(CommandHandler('resetprompt', reset_prompt))
    application.add_handler(CommandHandler('prompt', show_prompt))
    application.add_handler(CommandHandler('help', show_help))

    async def run_scheduler_background():
        """Run scheduler in background without blocking."""
        try:
            await start_scheduler()
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
            await asyncio.Event().wait()
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