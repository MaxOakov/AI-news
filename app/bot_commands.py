import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from app.db.prompt_repository import InvalidPromptError, PromptRepository
from app.db.rss_link_repository import RssLinkRepository
from app.scheduler import SchedulerService
from app.telegram_bot import TelegramBot

_ADMIN_STATUSES = {"creator", "administrator"}


class BotCommands:
    """Telegram command handlers.

    Bound to the specific TelegramBot, SchedulerService and repositories
    this application instance was composed with (see main.py's composition
    root), rather than reaching into module-level singletons.

    Commands that change shared chat configuration (topic id, RSS feeds,
    custom prompt, subscription state) are restricted to chat admins in
    group/supergroup chats via `_require_admin`; read-only commands and
    /start are open to anyone.
    """

    def __init__(
        self,
        telegram_bot: TelegramBot,
        scheduler_service: SchedulerService,
        rss_link_repository: RssLinkRepository,
        prompt_repository: PromptRepository,
    ):
        self._telegram_bot = telegram_bot
        self._scheduler_service = scheduler_service
        self._rss_links = rss_link_repository
        self._prompts = prompt_repository

    async def _require_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Return True if the sender may run a state-changing command here.

        Always True in private chats (the sender is the only member).
        In groups/supergroups, only the chat's creator/administrators (or
        an anonymous-admin post, which Telegram sends with no
        effective_user but a message.sender_chat matching the chat itself)
        may proceed; anyone else gets a warning reply and False.
        """
        chat = update.effective_chat
        if chat is None:
            return False
        if chat.type == "private":
            return True

        message = update.message
        sender_chat = getattr(message, "sender_chat", None) if message is not None else None
        if sender_chat is not None and sender_chat.id == chat.id:
            return True  # anonymous admin post

        user = update.effective_user
        if user is not None:
            try:
                member = await context.bot.get_chat_member(chat.id, user.id)
                if member.status in _ADMIN_STATUSES:
                    return True
            except Exception as e:
                print(f"⚠️ Не вдалося перевірити права адміністратора: {e}")

        if message is not None:
            await message.reply_text("⛔ Ця команда доступна лише адміністраторам чату.")
        return False

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start - register chat in DB."""
        if update.effective_chat is None:
            return

        chat_id = str(update.effective_chat.id)
        chat_name = update.effective_chat.title or (update.effective_user.first_name if update.effective_user else "Unknown user")
        chat_type = update.effective_chat.type
        message_thread_id = update.message.message_thread_id if update.message is not None else None

        await self._telegram_bot.register_chat_db(chat_id, chat_name, chat_type, message_thread_id)
        if update.message is not None:
            await update.message.reply_text(f"✅ Привіт! Я зареєстрований для чату: {chat_name}")

    async def run_job_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Instantly trigger the news job for this chat only."""
        if update.effective_chat is None:
            return

        chat_id = str(update.effective_chat.id)
        started = await self._scheduler_service.trigger_now(chat_id=chat_id)
        if started:
            text = "✅ Новий запуск новин розпочато вручну для цього чату."
        else:
            text = "⏸ Попередній запуск новин ще виконується або задача не доступна зараз."

        if update.message is not None:
            await update.message.reply_text(text)

    async def set_topic_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set or update the current forum topic id for this chat."""
        if update.effective_chat is None or update.message is None:
            return
        if not await self._require_admin(update, context):
            return

        chat_id = str(update.effective_chat.id)
        chat_name = update.effective_chat.title or (update.effective_user.first_name if update.effective_user else "Unknown user")
        chat_type = update.effective_chat.type
        message_thread_id = update.message.message_thread_id

        if message_thread_id is None:
            await update.message.reply_text("⚠️ Ця команда працює лише в темі/форумах. Відправте її в темі, а не в основному чаті.")
            return

        success = await self._telegram_bot.register_chat_db(chat_id, chat_name, chat_type, message_thread_id)
        if success:
            await update.message.reply_text(f"✅ Для чату встановлено topic_id={message_thread_id}")
        else:
            await update.message.reply_text("❌ Не вдалося зберегти topic_id.")

    async def add_rss_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add one or more comma-separated RSS URLs for the current chat."""
        if update.effective_chat is None or update.message is None:
            return
        if not await self._require_admin(update, context):
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
        saved, failed = [], []
        for rss_url in rss_urls:
            try:
                await asyncio.to_thread(self._rss_links.save, chat_id, rss_url)
                saved.append(rss_url)
            except Exception:
                failed.append(rss_url)

        if saved:
            await update.message.reply_text(
                f"✅ Збережено RSS-лінків для цього чату: {len(saved)}\n" + "\n".join(saved)
            )
        if failed:
            await update.message.reply_text(
                "⚠️ Не вдалося зберегти:\n" + "\n".join(failed)
            )

    async def remove_rss_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove one or more comma-separated RSS URLs from the current chat."""
        if update.effective_chat is None or update.message is None:
            return
        if not await self._require_admin(update, context):
            return

        if not context.args:
            await update.message.reply_text(
                "Використання: /removerss https://example.com/rss, https://example.org/feed"
            )
            return

        rss_urls = []
        for value in " ".join(context.args).split(","):
            rss_url = value.strip()
            if rss_url and rss_url not in rss_urls:
                rss_urls.append(rss_url)

        chat_id = str(update.effective_chat.id)
        removed, failed = [], []
        for rss_url in rss_urls:
            try:
                await asyncio.to_thread(self._rss_links.remove, chat_id, rss_url)
                removed.append(rss_url)
            except Exception:
                failed.append(rss_url)

        if removed:
            await update.message.reply_text(
                f"✅ Видалено RSS-лінків для цього чату: {len(removed)}\n" + "\n".join(removed)
            )
        if failed:
            await update.message.reply_text(
                "⚠️ Не вдалося видалити:\n" + "\n".join(failed)
            )

    async def list_rss_links(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all active RSS links stored for the current chat."""
        if update.effective_chat is None or update.message is None:
            return

        chat_id = str(update.effective_chat.id)
        links = await asyncio.to_thread(self._rss_links.get_for_chat, chat_id)
        if not links:
            await update.message.reply_text("📭 Для цього чату не збережено жодного RSS-лінка.")
            return

        formatted = "\n".join(f"- {item['url']}" for item in links)
        await update.message.reply_text(f"📚 RSS для цього чату:\n{formatted}")

    async def set_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set a custom prompt for the current chat."""
        if update.effective_chat is None or update.message is None:
            return
        if not await self._require_admin(update, context):
            return

        if not context.args:
            await update.message.reply_text("Використання: /setprompt <текст промпту>")
            return

        custom_prompt = " ".join(context.args)
        chat_id = str(update.effective_chat.id)
        try:
            await asyncio.to_thread(self._prompts.save_custom, chat_id, custom_prompt)
        except InvalidPromptError as e:
            await update.message.reply_text(f"❌ Некоректний prompt: {e}")
            return
        await update.message.reply_text("✅ Користувацький prompt для цього чату збережено. Тепер він буде використовуватися замість prompt.txt.")

    async def reset_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reset the custom prompt for the current chat and use the default one again."""
        if update.effective_chat is None or update.message is None:
            return
        if not await self._require_admin(update, context):
            return

        chat_id = str(update.effective_chat.id)
        await asyncio.to_thread(self._prompts.reset_custom, chat_id)
        await update.message.reply_text("✅ Користувацький prompt скинуто. Знову використовується prompt.txt.")

    async def show_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display the active prompt for the current chat."""
        if update.effective_chat is None or update.message is None:
            return

        chat_id = str(update.effective_chat.id)
        active_prompt = await asyncio.to_thread(self._prompts.get_for_chat, chat_id)
        preview = active_prompt[:800] + ("..." if len(active_prompt) > 800 else "")
        await update.message.reply_text(f"📝 Активний prompt для цього чату:\n\n{preview}")

    async def stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Deactivate this chat's subscription. RSS feeds and custom prompt
        are kept, so a later /start picks up right where this left off."""
        if update.effective_chat is None or update.message is None:
            return
        if not await self._require_admin(update, context):
            return

        chat_id = str(update.effective_chat.id)
        success = await self._telegram_bot.deactivate_chat_db(chat_id)
        if success:
            await update.message.reply_text(
                "⏹ Чат відписано від новин. Викличте /start, щоб відновити."
            )
        else:
            await update.message.reply_text("❌ Не вдалося відписати чат.")

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show the available bot commands and their descriptions."""
        if update.message is None:
            return

        help_text = (
            "📖 Доступні команди:\n\n"
            "/start — зареєструвати цей чат у боті\n"
            "/help — показати список команд\n"
            "/runjob — негайно запустити обробку новин\n"
            "/news — те саме, що /runjob\n"
            "/listfeeds — показати RSS-лінки цього чату\n"
            "/prompt — показати активний prompt цього чату\n"
            "\nКоманди нижче доступні лише адміністраторам чату (у групах):\n"
            "/settopic — встановити поточну тему форуму для надсилання новин\n"
            "/addrss <url1>, <url2> — додати один або кілька RSS-лінків для цього чату\n"
            "/removerss <url1>, <url2> — видалити один або кілька RSS-лінків цього чату\n"
            "/setprompt <текст> — зберегти власний prompt для цього чату\n"
            "/resetprompt — повернути використання стандартного prompt.txt\n"
            "/stop — відписати цей чат від новин"
        )
        await update.message.reply_text(help_text)
