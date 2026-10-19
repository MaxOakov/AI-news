import asyncio

from app.db.instagram_settings_repository import InstagramSettingsRepository
from app.models import InstagramRoute, InstagramSettings


class InstagramSettingsService:
    """Per-chat Instagram settings, plus an in-memory index of the chats
    where posting is fully set up (chat id → InstagramRoute: which hashtags
    and topic pick its posts).

    The forwarder sees every message of every group the bot is in; the
    index lets it drop all but the configured chats' messages without a
    database hit. It holds no secrets: those are read (and decrypted) only
    when a post is actually published.
    """

    def __init__(self, repository: InstagramSettingsRepository):
        self._repository = repository
        self._routes: dict[str, InstagramRoute] = {}

    @property
    def can_store_secrets(self) -> bool:
        return self._repository.can_store_secrets

    def ensure_indexes(self):
        self._repository.ensure_indexes()

    async def load(self):
        """Build the index from the database (once, at startup)."""
        all_settings = await asyncio.to_thread(self._repository.get_all)
        self._routes = {s.chat_id: s.route for s in all_settings if s.is_ready}
        print(f"✅ Instagram налаштовано для чатів: {len(self._routes)}")

    def route_for(self, chat_id) -> InstagramRoute | None:
        """How the chat's posts are picked, if posting to Instagram is set up there."""
        return self._routes.get(str(chat_id))

    async def get(self, chat_id) -> InstagramSettings | None:
        return await asyncio.to_thread(self._repository.get, str(chat_id))

    async def save_account(self, chat_id, user_id, username, api_host, token, admin_user_id):
        await asyncio.to_thread(
            self._repository.save_account, str(chat_id), user_id, username, api_host, token, admin_user_id
        )
        await self._refresh(chat_id)

    async def save_r2(self, chat_id, account_id, bucket, public_base_url, access_key_id, secret_access_key):
        await asyncio.to_thread(
            self._repository.save_r2, str(chat_id), account_id, bucket, public_base_url, access_key_id, secret_access_key
        )
        await self._refresh(chat_id)

    async def save_trigger_hashtags(self, chat_id, hashtags: list[str]):
        await asyncio.to_thread(self._repository.save_trigger_hashtags, str(chat_id), hashtags)
        await self._refresh(chat_id)

    async def save_extra_hashtags(self, chat_id, hashtags: list[str]):
        await asyncio.to_thread(self._repository.save_extra_hashtags, str(chat_id), hashtags)
        await self._refresh(chat_id)

    async def save_topic(self, chat_id, topic_id: int | None, topic_name: str | None, all_topics: bool):
        await asyncio.to_thread(self._repository.save_topic, str(chat_id), topic_id, topic_name, all_topics)
        await self._refresh(chat_id)

    async def reset(self, chat_id) -> bool:
        deleted = await asyncio.to_thread(self._repository.delete, str(chat_id))
        self._routes.pop(str(chat_id), None)
        return deleted

    async def _refresh(self, chat_id):
        settings = await self.get(chat_id)
        if settings is not None and settings.is_ready:
            self._routes[str(chat_id)] = settings.route
        else:
            self._routes.pop(str(chat_id), None)
