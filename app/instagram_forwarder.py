"""Taking a chat's posts to Instagram, with each chat's own settings
(account, R2 bucket, hashtags, topic; see InstagramSettingsService).

In a chat where Instagram is set up, a post goes to Instagram when its
text contains any of the chat's tracked hashtags and there's a picture
for it. Posts are taken from the chat's Instagram topic (/ig_topic): by
default the topic its news go to (/settopic), or the whole chat if it has
none; and only while the chat is subscribed (/start). Posts with a video
(or GIF) are skipped for now. The picture is, in order:

- the post's own photos (an album becomes a carousel);
- for a text post, the picture of its link preview: the linked image
  itself, or the linked page's og:image (see PageImageFetcher).

Telegram never delivers a bot's own messages to it as updates, so the news
posts this bot publishes don't come through `handle`. ArticlePublisher
hands them over via `forward_article` instead, right after sending one,
with the same picture its link preview shows (Article.preview_url).

Telegram delivers an album as one update per item, sharing a
media_group_id, with the caption on just one of them. So album items are
collected for `album_wait` seconds and then handled as one post.

The work runs in background tasks, so a slow download or Instagram's
processing never holds up the bot's other updates or the news run.
"""
import asyncio
import html
import uuid
from collections.abc import Awaitable, Callable

from app.db.instagram_post_repository import InstagramPostRepository
from app.models import Article, InstagramSettings
from app.services.image_prep import prepare_for_instagram
from app.services.instagram_caption import build_caption, has_any_hashtag
from app.services.instagram_client import MAX_CAROUSEL_ITEMS
from app.services.instagram_connector import InstagramConnector
from app.services.instagram_settings import InstagramSettingsService
from app.services.page_image import PageImageFetcher
from app.telegram_bot import TelegramBot, html_to_plain_text

ImageLoader = Callable[[], Awaitable[bytes]]


def _link_preview_url(message) -> str | None:
    """The URL a text message's link preview is of: the one set explicitly
    for the preview, else the message's first link (as Telegram picks it)."""
    options = getattr(message, "link_preview_options", None)
    if options is not None:
        if options.is_disabled:
            return None
        if options.url:
            return options.url
    for entity in sorted(message.entities or (), key=lambda e: e.offset):
        if entity.type == "text_link":
            return entity.url
        if entity.type == "url":
            return message.parse_entity(entity)
    return None


class InstagramForwarder:
    def __init__(
        self,
        settings: InstagramSettingsService,
        post_repository: InstagramPostRepository,
        connector: InstagramConnector,
        page_image_fetcher: PageImageFetcher,
        telegram_bot: TelegramBot,
        album_wait: float = 3,
    ):
        self._settings = settings
        self._posts = post_repository
        self._connector = connector
        self._page_images = page_image_fetcher
        self._telegram_bot = telegram_bot
        self._album_wait = album_wait
        self._albums: dict[tuple[str, str], list] = {}
        self._tasks: set[asyncio.Task] = set()

    def ensure_indexes(self):
        self._posts.ensure_indexes()

    async def handle(self, update, context):
        message = update.effective_message
        if message is None or not self._watches(str(message.chat.id), message.message_thread_id):
            return

        if message.media_group_id:
            key = (str(message.chat.id), str(message.media_group_id))
            album = self._albums.get(key)
            if album is None:
                self._albums[key] = [message]
                self._spawn(self._flush_album(key, context.bot))
            else:
                album.append(message)
        else:
            self._spawn(self._process_messages([message], context.bot))

    def forward_article(self, chat_id, message_thread_id, article: Article, text: str):
        """Take a news post this bot just sent to `chat_id`/`message_thread_id`
        (`text`, as HTML) to Instagram, if the chat has it set up, watches
        that topic, and the post has one of its tracked hashtags. Returns at
        once; the work runs in the background."""
        chat_id = str(chat_id)
        if not self._watches(chat_id, message_thread_id):
            return
        text = html_to_plain_text(text)
        if not has_any_hashtag(text, self._settings.route_for(chat_id).hashtags):
            return
        url = article.preview_url
        if not url:
            print(f"⏭ Стаття '{article.title}' без картинки — в Instagram не переносимо.")
            return
        self._spawn(self._run(
            chat_id, f"article:{article.id}", [lambda: self._page_images.fetch_image(url)], text
        ))

    async def wait_idle(self):
        """Wait until every post handled so far is done (for tests and shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _watches(self, chat_id: str, message_thread_id) -> bool:
        """Whether messages from this chat/topic may go to Instagram. Uses
        only in-memory state: it runs for every message of every group."""
        route = self._settings.route_for(chat_id)
        if route is None:
            return False
        chat = self._telegram_bot.chats.get(chat_id)
        if chat is None:
            return False
        return route.watches_topic(message_thread_id, chat.message_thread_id)

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _flush_album(self, key, bot):
        await asyncio.sleep(self._album_wait)
        await self._process_messages(self._albums.pop(key), bot)

    async def _process_messages(self, messages: list, bot):
        messages = sorted(messages, key=lambda m: m.message_id)
        first = messages[0]
        chat_id = str(first.chat.id)
        post_key = str(first.media_group_id or first.message_id)
        text = next((m.caption or m.text for m in messages if m.caption or m.text), "")

        route = self._settings.route_for(chat_id)
        if route is None or not has_any_hashtag(text, route.hashtags):
            return
        if any(m.video or m.animation or m.video_note for m in messages):
            print(f"⏭ Пост {post_key} містить відео — в Instagram поки не переносимо.")
            return

        photos = [m.photo[-1] for m in messages if m.photo][:MAX_CAROUSEL_ITEMS]
        if photos:
            loaders = [lambda p=photo: self._download_telegram_photo(bot, p) for photo in photos]
        elif (url := _link_preview_url(first)) is not None:
            loaders = [lambda: self._page_images.fetch_image(url)]
        else:
            print(f"⏭ Пост {post_key} без фото і без посилання — в Instagram не переносимо.")
            return

        await self._run(chat_id, post_key, loaders, text)

    @staticmethod
    async def _download_telegram_photo(bot, photo) -> bytes:
        file = await bot.get_file(photo.file_id)
        return bytes(await file.download_as_bytearray())

    async def _run(self, chat_id: str, post_key: str, loaders: list[ImageLoader], text: str):
        try:
            settings = await self._settings.get(chat_id)
        except Exception as exc:
            print(f"❌ Не вдалося прочитати налаштування Instagram чату {chat_id}: {exc}")
            return
        if settings is None or not settings.is_ready:
            print(f"⏭ Instagram для чату {chat_id} більше не налаштовано — пост {post_key} пропущено.")
            return

        try:
            claimed = await asyncio.to_thread(self._posts.claim, chat_id, post_key)
        except Exception as exc:
            print(f"❌ Не вдалося перевірити пост {post_key} у БД: {exc}")
            return
        if not claimed:
            print(f"⏭ Пост {post_key} вже оброблено раніше.")
            return

        where = self._chat_label(chat_id)
        try:
            media_id = await self._publish(
                settings, post_key, loaders, build_caption(text, settings.extra_hashtags)
            )
        except Exception as exc:
            print(f"❌ Не вдалося опублікувати пост {post_key} з {where} в Instagram: {exc}")
            await self._record(self._posts.mark_failed, chat_id, post_key, str(exc))
            await self._notify(settings, f"❌ Не вдалося опублікувати пост {post_key} з {where} в Instagram: {exc}")
            return

        print(f"📸 Пост {post_key} з {where} опубліковано в Instagram (media id {media_id}).")
        await self._record(self._posts.mark_published, chat_id, post_key, media_id)
        await self._notify(
            settings, f"📸 Пост {post_key} з {where} опубліковано в Instagram @{settings.instagram_username}."
        )

    async def _publish(self, settings: InstagramSettings, post_key, loaders: list[ImageLoader], caption) -> str:
        image_host = self._connector.image_host(settings)
        keys = []
        try:
            urls = []
            for index, load in enumerate(loaders):
                jpeg = await asyncio.to_thread(prepare_for_instagram, await load())
                # Random suffix: the bucket is public, so keys shouldn't be guessable.
                safe_key = post_key.replace(":", "-")
                key = f"instagram/{settings.chat_id}/{safe_key}-{index}-{uuid.uuid4().hex}.jpg"
                urls.append(await asyncio.to_thread(image_host.upload, key, jpeg))
                keys.append(key)
            return await self._connector.instagram_client(settings).publish_photos(urls, caption)
        finally:
            # Instagram has its own copy once a container is processed.
            for key in keys:
                try:
                    await asyncio.to_thread(image_host.delete, key)
                except Exception as exc:
                    print(f"⚠️ Не вдалося видалити {key} з R2: {exc}")

    def _chat_label(self, chat_id: str) -> str:
        chat = self._telegram_bot.chats.get(chat_id)
        return f"«{chat.chat_name}»" if chat is not None else f"чату {chat_id}"

    async def _record(self, method, *args):
        try:
            await asyncio.to_thread(method, *args)
        except Exception as exc:
            print(f"⚠️ Не вдалося зберегти стан публікації в Instagram: {exc}")

    async def _notify(self, settings: InstagramSettings, text: str):
        """Tell the admin who connected the account (in their private chat)."""
        if settings.admin_user_id:
            await self._telegram_bot.send_message(settings.admin_user_id, html.escape(text))
