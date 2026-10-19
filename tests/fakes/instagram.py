"""Fakes for the Instagram side: the R2 image host, the Instagram client,
the connector that builds them per chat, the page-image fetcher, and the
forwarder as ArticlePublisher sees it. (InstagramClient and
InstagramConnector themselves are tested against an httpx.MockTransport.)"""
from app.services.image_host import ImageHostError
from app.services.instagram_client import InstagramError
from app.services.instagram_connector import AccountCheck
from app.services.page_image import PageImageError

# Defaults for a chat set up by configure_instagram.
ADMIN = "555"
TRIGGER = "#Команда_AniKoe"
EXTRA = ["#аніме", "#анімеукраїнською", "#анімеукраїна", "#українаніме", "#анімеоналайн"]


def configure_instagram(repository, chat_id, trigger=TRIGGER, extra=EXTRA, admin=ADMIN):
    """Fully set up Instagram for a chat, straight through an
    InstagramSettingsRepository: `trigger` is a hashtag or a list of them
    (None leaves the setup incomplete)."""
    repository.save_account(chat_id, "17841400000", "anikoe", "graph.facebook.com", f"token-{chat_id}", admin)
    repository.save_r2(chat_id, "acc123", "bucket", "https://pub.example", "key-id", "key-secret")
    if trigger:
        repository.save_trigger_hashtags(chat_id, [trigger] if isinstance(trigger, str) else list(trigger))
    repository.save_extra_hashtags(chat_id, extra)


class FakeImageHost:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.uploaded: list[str] = []
        self.deleted: list[str] = []

    def upload(self, key, data, content_type="image/jpeg"):
        self.objects[key] = data
        self.uploaded.append(key)
        return f"https://img.example/{key}"

    def delete(self, key):
        self.objects.pop(key, None)
        self.deleted.append(key)


class FakeInstagramClient:
    def __init__(self, username="anikoe"):
        self.published: list[dict] = []
        self.username = username
        self._fail_with: str | None = None

    def fail(self, message="simulated Instagram failure"):
        """Make every later call raise InstagramError(message)."""
        self._fail_with = message

    async def get_username(self):
        if self._fail_with:
            raise InstagramError(self._fail_with)
        return self.username

    async def publish_photos(self, image_urls, caption):
        if self._fail_with:
            raise InstagramError(self._fail_with)
        self.published.append({"image_urls": list(image_urls), "caption": caption})
        return f"ig-media-{len(self.published)}"


class FakeConnector:
    """Stand-in for InstagramConnector: hands out one shared fake client and
    image host, recording the settings they were built from, and answers
    credential checks as configured."""

    def __init__(self):
        self.instagram = FakeInstagramClient()
        self.image_host_fake = FakeImageHost()
        self.clients_built_for: list = []
        self.hosts_built_for: list = []
        self.account_checks: list[tuple] = []
        self.r2_checks: list[tuple] = []
        self.account_check = AccountCheck(username="anikoe", api_host="graph.facebook.com")
        self.account_error: str | None = None
        self.r2_error: str | None = None

    def instagram_client(self, settings):
        self.clients_built_for.append(settings)
        return self.instagram

    def image_host(self, settings):
        self.hosts_built_for.append(settings)
        return self.image_host_fake

    async def check_account(self, user_id, token):
        self.account_checks.append((user_id, token))
        if self.account_error:
            raise InstagramError(self.account_error)
        return self.account_check

    async def check_r2(self, account_id, access_key_id, secret_access_key, bucket, public_base_url):
        self.r2_checks.append((account_id, access_key_id, secret_access_key, bucket, public_base_url))
        if self.r2_error:
            raise ImageHostError(self.r2_error)


class FakePageImageFetcher:
    """Stand-in for PageImageFetcher: `images[url]` is what a link yields;
    an unknown link fails like a page without a picture."""

    def __init__(self, images: dict[str, bytes] | None = None):
        self.images = images or {}
        self.fetched: list[str] = []

    async def fetch_image(self, url):
        self.fetched.append(url)
        if url not in self.images:
            raise PageImageError("на сторінці немає картинки")
        return self.images[url]


class FakeForwarder:
    """Records what ArticlePublisher hands to the Instagram forwarder."""

    def __init__(self):
        self.forwarded: list[tuple] = []

    def forward_article(self, chat_id, message_thread_id, article, text):
        self.forwarded.append((chat_id, message_thread_id, article, text))
