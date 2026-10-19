"""Setup commands: the /setup checklist, and each chat's Instagram settings.

Secrets (the Instagram token, the R2 keys) are only accepted in a private
chat with the bot: everyone in a group sees its messages, and Telegram
keeps them in the history. A group's /setup checklist carries a button
that opens the private chat through a deep link (/start setup_<chat id>);
the bot checks the user is an admin of that chat and remembers, for an
hour, that they're setting it up, so what they send privately applies to
that chat (re-checking they're still an admin each time). Messages that
carry secrets are deleted as soon as they're read (a bot may delete
incoming messages in a private chat); one sent to a group by mistake is
deleted there if the bot has the right to, with a warning to revoke the key.

Credentials are checked before they're saved: the token against the Graph
API, the R2 keys by uploading a file and fetching it back through the
bucket's public URL, as Instagram will.
"""
import asyncio
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db.rss_link_repository import RssLinkRepository
from app.permissions import is_chat_admin, require_admin
from app.services.image_host import ImageHostError
from app.services.instagram_caption import MAX_HASHTAGS, normalize_hashtag
from app.services.instagram_client import InstagramError
from app.services.instagram_connector import InstagramConnector
from app.services.instagram_settings import InstagramSettingsService
from app.setup_checklist import ChecklistData, render_checklist
from app.telegram_bot import TelegramBot

SETUP_DEEP_LINK_PREFIX = "setup_"
SESSION_TTL_SECONDS = 3600
_CLEAR_WORDS = {"off", "-", "none"}
_TOPIC_USAGE = (
    "Звідки брати пости для Instagram:\n"
    "• надішліть /ig_topic у потрібній гілці форуму — лише з неї;\n"
    "• /ig_topic all — з усього чату;\n"
    "• /ig_topic news — з тієї ж гілки, що й новини (так за замовчуванням)."
)
_NO_ENCRYPTION_KEY = (
    "❌ На сервері не задано ключ шифрування (SECRETS_ENCRYPTION_KEY), тож токени й ключі "
    "не можна безпечно зберегти. Зверніться до власника бота."
)


def _topic_name(message) -> str | None:
    """The forum topic's name, when Telegram includes it: a message sent
    straight into a topic (not as a reply) replies to the topic's creation
    message, which carries the name."""
    reply = getattr(message, "reply_to_message", None)
    created = getattr(reply, "forum_topic_created", None)
    return getattr(created, "name", None)


class SetupCommands:
    def __init__(
        self,
        telegram_bot: TelegramBot,
        rss_link_repository: RssLinkRepository,
        instagram_settings: InstagramSettingsService,
        connector: InstagramConnector,
        clock=time.monotonic,
    ):
        self._telegram_bot = telegram_bot
        self._rss_links = rss_link_repository
        self._settings = instagram_settings
        self._connector = connector
        self._clock = clock
        # user id → (chat id they're setting up privately, expiry time)
        self._sessions: dict[str, tuple[str, float]] = {}

    # ----------------------------------------------------------------------
    # Checklist
    # ----------------------------------------------------------------------
    async def setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/setup: the checklist for this chat (in a private chat: for the
        chat being set up there)."""
        if update.effective_chat is None or update.message is None:
            return
        target = await self._target_chat(update, context)
        if target is not None:
            await self._reply_checklist(update, context, target, live_check=True)

    async def send_first_start_checklist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Shown once, after the first /start in a chat."""
        if update.effective_chat is None or update.message is None:
            return
        await self._reply_checklist(update, context, str(update.effective_chat.id), live_check=False)

    async def start_from_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/start setup_<chat id> in a private chat: the button from a group's
        /setup. Starts setting that chat up here instead of registering this
        private chat for news."""
        message, user = update.message, update.effective_user
        if message is None or user is None or update.effective_chat is None:
            return

        payload = context.args[0] if context.args else ""
        target = payload.removeprefix(SETUP_DEEP_LINK_PREFIX)
        if not payload.startswith(SETUP_DEEP_LINK_PREFIX) or not target.lstrip("-").isdigit():
            await message.reply_text("⚠️ Некоректне посилання. Відкрийте /setup у потрібній групі ще раз.")
            return
        if not await is_chat_admin(context.bot, target, user.id):
            await message.reply_text("⛔ Налаштовувати чат можуть лише його адміністратори.")
            return

        self._sessions[str(user.id)] = (target, self._clock() + SESSION_TTL_SECONDS)
        await self._reply_checklist(update, context, target, live_check=True)

    # ----------------------------------------------------------------------
    # Instagram settings
    # ----------------------------------------------------------------------
    async def ig_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/ig_account <Instagram user id> <access token> (private chat only)."""
        if not await self._accept_secret_message(update, context):
            return
        target = await self._target_chat(update, context)
        if target is None:
            return
        message = update.message
        if len(context.args) != 2 or not context.args[0].isdigit():
            await message.reply_text("Використання: /ig_account <ID акаунта Instagram (цифри)> <токен доступу>")
            return
        if not self._settings.can_store_secrets:
            await message.reply_text(_NO_ENCRYPTION_KEY)
            return

        user_id, token = context.args
        try:
            check = await self._connector.check_account(user_id, token)
        except InstagramError as exc:
            await message.reply_text(f"❌ Instagram не прийняв токен: {exc}")
            return

        try:
            await self._settings.save_account(
                target, user_id, check.username, check.api_host, token, str(update.effective_user.id)
            )
        except Exception as exc:
            print(f"❌ Не вдалося зберегти акаунт Instagram для чату {target}: {type(exc).__name__}")
            await message.reply_text("❌ Не вдалося зберегти налаштування. Спробуйте пізніше.")
            return
        await self._reply_checklist(
            update, context, target, live_check=False, intro=f"✅ Акаунт Instagram @{check.username} підключено."
        )

    async def ig_r2(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/ig_r2 <account id> <access key id> <secret access key> <bucket>
        <public URL> (private chat only)."""
        if not await self._accept_secret_message(update, context):
            return
        target = await self._target_chat(update, context)
        if target is None:
            return
        message = update.message
        if len(context.args) != 5:
            await message.reply_text(
                "Використання: /ig_r2 <Account ID> <Access Key ID> <Secret Access Key> <бакет> <публічний URL бакета>\n"
                "Публічний URL — адреса r2.dev бакета або ваш домен, напр. https://pub-xxxx.r2.dev"
            )
            return
        if not self._settings.can_store_secrets:
            await message.reply_text(_NO_ENCRYPTION_KEY)
            return

        account_id, access_key_id, secret_access_key, bucket, public_url = context.args
        public_url = public_url.rstrip("/")
        if not account_id.isalnum():
            await message.reply_text("❌ Account ID має складатися лише з літер і цифр (його видно в панелі Cloudflare).")
            return
        if not public_url.startswith("https://"):
            await message.reply_text("❌ Публічний URL бакета має починатися з https://")
            return

        await message.reply_text("⏳ Перевіряю бакет: завантажую тестовий файл і відкриваю його за публічним URL…")
        try:
            await self._connector.check_r2(account_id, access_key_id, secret_access_key, bucket, public_url)
        except ImageHostError as exc:
            await message.reply_text(f"❌ Бакет не підходить: {exc}")
            return

        try:
            await self._settings.save_r2(target, account_id, bucket, public_url, access_key_id, secret_access_key)
        except Exception as exc:
            print(f"❌ Не вдалося зберегти R2 для чату {target}: {type(exc).__name__}")
            await message.reply_text("❌ Не вдалося зберегти налаштування. Спробуйте пізніше.")
            return
        await self._reply_checklist(
            update, context, target, live_check=False, intro=f"✅ Сховище R2 (бакет {bucket}) підключено."
        )

    async def ig_track(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/ig_track <hashtags…> | off: posts with any of them go to Instagram."""
        if update.effective_chat is None or update.message is None:
            return
        target = await self._target_chat(update, context)
        if target is None:
            return
        if not context.args:
            await update.message.reply_text(
                "Використання: /ig_track #в_інсту #анонс … — в Instagram підуть пости з будь-яким "
                "із цих хештегів (/ig_track off — не відбирати жодних, тоді Instagram вимкнеться)"
            )
            return
        hashtags = await self._parse_hashtags(update, context.args)
        if hashtags is None:
            return

        await self._settings.save_trigger_hashtags(target, hashtags)
        intro = (
            f"✅ В Instagram підуть пости з {' або '.join(hashtags)}." if hashtags
            else "✅ Хештеги для відбору очищено — в Instagram нічого не піде, доки не задасте нові."
        )
        await self._reply_checklist(update, context, target, live_check=False, intro=intro)

    async def ig_tags(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/ig_tags <hashtags…> | off: hashtags added at the end of each caption."""
        if update.effective_chat is None or update.message is None:
            return
        target = await self._target_chat(update, context)
        if target is None:
            return
        if not context.args:
            await update.message.reply_text(
                "Використання: /ig_tags #аніме #анімеукраїнською … (або /ig_tags off — не додавати хештеги)"
            )
            return
        hashtags = await self._parse_hashtags(update, context.args)
        if hashtags is None:
            return

        await self._settings.save_extra_hashtags(target, hashtags)
        intro = "✅ Додаткові хештеги збережено." if hashtags else "✅ Додаткові хештеги більше не додаються."
        await self._reply_checklist(update, context, target, live_check=False, intro=intro)

    async def ig_topic(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/ig_topic (sent inside a forum topic) | all | news: where posts
        for Instagram are taken from."""
        if update.effective_chat is None or update.message is None:
            return
        target = await self._target_chat(update, context)
        if target is None:
            return
        message = update.message
        mode = context.args[0].lower() if context.args else ""

        if mode == "all":
            await self._settings.save_topic(target, None, None, all_topics=True)
            intro = "✅ В Instagram підуть пости з усього чату, з будь-якої гілки."
        elif mode == "news":
            await self._settings.save_topic(target, None, None, all_topics=False)
            intro = "✅ В Instagram підуть пости з тієї ж гілки, що й новини (/settopic)."
        elif mode or update.effective_chat.type == "private" or not getattr(message, "is_topic_message", False):
            # A topic can only be picked from inside it: its id comes with the message.
            await message.reply_text(_TOPIC_USAGE)
            return
        else:
            name = _topic_name(message)
            await self._settings.save_topic(target, message.message_thread_id, name, all_topics=False)
            intro = f"✅ В Instagram підуть пости з гілки «{name}»." if name else "✅ В Instagram підуть пости з цієї гілки."
        await self._reply_checklist(update, context, target, live_check=False, intro=intro)

    async def ig_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/ig_reset: delete all of the chat's Instagram settings (and secrets)."""
        if update.effective_chat is None or update.message is None:
            return
        target = await self._target_chat(update, context)
        if target is None:
            return
        deleted = await self._settings.reset(target)
        intro = (
            "🗑 Налаштування Instagram цього чату видалено разом із токеном і ключами."
            if deleted else "ℹ️ Instagram для цього чату й так не налаштовано."
        )
        await self._reply_checklist(update, context, target, live_check=False, intro=intro)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    async def _target_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
        """The chat a setup command applies to, or None (after replying why).

        In a group: the group itself, for its admins. In a private chat:
        the chat this user opened setup for through a group's button, while
        they're still its admin; else this private chat, if it gets news.
        """
        chat = update.effective_chat
        if chat.type != "private":
            return str(chat.id) if await require_admin(update, context) else None

        user = update.effective_user
        if user is None:
            return None
        session_chat = self._session_chat(user.id)
        if session_chat is not None:
            if await is_chat_admin(context.bot, session_chat, user.id):
                return session_chat
            self._sessions.pop(str(user.id), None)
            await update.message.reply_text("⛔ Ви більше не адміністратор чату, який налаштовували.")
            return None

        own_chat = str(chat.id)
        if await self._telegram_bot.get_known_chat(own_chat) is not None:
            return own_chat
        await update.message.reply_text(
            "ℹ️ Щоб налаштувати групу, викличте в ній /setup і натисніть кнопку «🔐 Налаштувати Instagram» — "
            "тоді я знатиму, для якого чату ці налаштування."
        )
        return None

    @staticmethod
    async def _parse_hashtags(update: Update, args: list[str]) -> list[str] | None:
        """`args` as a list of distinct hashtags ([] for "off"; commas work as
        separators too), or None after replying what's wrong with them."""
        values = " ".join(args).replace(",", " ").split()
        if len(values) == 1 and values[0].lower() in _CLEAR_WORDS:
            return []
        hashtags, seen = [], set()
        for value in values:
            hashtag = normalize_hashtag(value)
            if hashtag is None:
                await update.message.reply_text(f"❌ «{value}» не схожий на хештег: лише літери, цифри та _.")
                return None
            if hashtag.casefold() not in seen:
                seen.add(hashtag.casefold())
                hashtags.append(hashtag)
        if len(hashtags) > MAX_HASHTAGS:
            await update.message.reply_text(
                f"❌ Не більше {MAX_HASHTAGS} хештегів — стільки Instagram дозволяє в одному пості."
            )
            return None
        return hashtags

    def _session_chat(self, user_id) -> str | None:
        entry = self._sessions.get(str(user_id))
        if entry is None:
            return None
        chat_id, expires_at = entry
        if self._clock() > expires_at:
            del self._sessions[str(user_id)]
            return None
        return chat_id

    async def _accept_secret_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Whether a command carrying secrets may go on: only in a private
        chat, where its message is deleted right away. In a group, the
        message is deleted if the bot can, with a warning, and it's refused."""
        message, chat = update.message, update.effective_chat
        if message is None or chat is None:
            return False

        if chat.type == "private":
            if context.args:
                await self._delete(message)
            return True

        if not context.args:
            await message.reply_text(
                "🔐 Токен і ключі вводяться лише в особистих повідомленнях боту: /setup → «🔐 Налаштувати Instagram»."
            )
            return False

        deleted = await self._delete(message)
        await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=message.message_thread_id,
            text=(
                "⛔ Не надсилайте токени й ключі в групу — їх бачать усі учасники. "
                + ("Я видалив повідомлення" if deleted else "Видаліть це повідомлення")
                + ", але вважайте ключ скомпрометованим і перевипустіть його. "
                "Ключі вводяться лише в особистих повідомленнях боту: /setup → «🔐 Налаштувати Instagram»."
            ),
        )
        return False

    @staticmethod
    async def _delete(message) -> bool:
        try:
            await message.delete()
            return True
        except Exception as exc:
            print(f"⚠️ Не вдалося видалити повідомлення з ключем: {type(exc).__name__}")
            return False

    async def _reply_checklist(self, update, context, target: str, live_check: bool, intro: str | None = None):
        in_private = update.effective_chat.type == "private"
        text = render_checklist(await self._collect(context, target, live_check), in_private=in_private)
        if intro:
            text = f"{intro}\n\n{text}"
        markup = None if in_private else self._setup_button(context, target)
        await update.message.reply_text(text, reply_markup=markup)

    @staticmethod
    def _setup_button(context, target: str) -> InlineKeyboardMarkup | None:
        try:
            username = context.bot.username
        except Exception:  # PTB raises RuntimeError until the bot is initialized
            username = None
        if not username:
            return None
        url = f"https://t.me/{username}?start={SETUP_DEEP_LINK_PREFIX}{target}"
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔐 Налаштувати Instagram", url=url)]])

    async def _collect(self, context, target: str, live_check: bool) -> ChecklistData:
        chat = await self._telegram_bot.get_known_chat(target)
        if chat is not None:
            name, chat_type, topic_id = chat.chat_name, chat.chat_type, chat.message_thread_id
        else:
            name = await self._chat_title(context, target)
            chat_type = "supergroup" if target.startswith("-") else "private"
            topic_id = None

        try:
            feed_count = len(await asyncio.to_thread(self._rss_links.get_for_chat, target))
        except Exception as exc:
            print(f"⚠️ Не вдалося прочитати RSS-стрічки чату {target}: {exc}")
            feed_count = 0

        settings = None
        try:
            settings = await self._settings.get(target)
        except Exception as exc:
            print(f"⚠️ Не вдалося прочитати налаштування Instagram чату {target}: {type(exc).__name__}")

        account_error = None
        if live_check and settings is not None and settings.has_account:
            # The token can stop working at any time (e.g. the Facebook
            # session it came from was logged out), so check it live.
            try:
                await self._connector.instagram_client(settings).get_username()
            except InstagramError as exc:
                account_error = str(exc)
            except Exception as exc:
                account_error = f"не вдалося перевірити ({type(exc).__name__})"

        return ChecklistData(
            chat_name=name,
            is_group=chat_type in ("group", "supergroup"),
            is_active=target in self._telegram_bot.chats,
            feed_count=feed_count,
            topic_id=topic_id,
            settings=settings,
            can_store_secrets=self._settings.can_store_secrets,
            account_error=account_error,
        )

    @staticmethod
    async def _chat_title(context, chat_id: str) -> str:
        try:
            chat = await context.bot.get_chat(chat_id)
            return chat.title or chat.first_name or chat_id
        except Exception:
            return chat_id
