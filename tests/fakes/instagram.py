"""Fakes for the Telegram → Instagram forwarder: the R2 image host and the
Instagram client (InstagramClient itself is tested against an
httpx.MockTransport in tests/services/test_instagram_client.py)."""
from app.services.instagram_client import InstagramError
from app.services.page_image import PageImageError


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
    def __init__(self):
        self.published: list[dict] = []
        self._fail_with: str | None = None

    def fail(self, message="simulated Instagram failure"):
        self._fail_with = message

    async def publish_photos(self, image_urls, caption):
        if self._fail_with:
            raise InstagramError(self._fail_with)
        self.published.append({"image_urls": list(image_urls), "caption": caption})
        return f"ig-media-{len(self.published)}"


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
