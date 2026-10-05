import feedparser
import datetime
import functools
import html
import re
import time
from collections.abc import Callable

import httpx

from app.db.article_repository import ArticleRepository
from app.db.rss_link_repository import RssLinkRepository
from app.models import Article
from app.retry import retry

# How many of a feed's most recent entries to check per poll. Bounded so a
# feed that suddenly dumps its whole archive can't blow up one poll, but
# large enough that a feed publishing faster than the hourly schedule
# doesn't silently lose everything past the single newest item.
_MAX_ENTRIES_PER_POLL = 3

# Limits for downloading one feed. feedparser's own fetching has no timeout,
# so a server that accepts the connection and then never answers would hang
# its worker thread, and with it the whole run, indefinitely.
_FETCH_TIMEOUT_SECONDS = 15
_MAX_FEED_BYTES = 5 * 1024 * 1024
_USER_AGENT = "Mozilla/5.0 (compatible; AI-news-bot/1.0)"


class FeedFetchError(Exception):
    """feedparser reported a parsing/fetch problem and returned nothing usable."""


def make_http_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """The HTTP client feeds are downloaded with (shared across chats so
    connections to the same host get reused). `transport` is for tests."""
    return httpx.Client(
        timeout=_FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
        transport=transport,
    )


def download_feed(url: str, client: httpx.Client) -> bytes:
    """Download a feed's raw body, bounded in total time and size.

    The client's timeout bounds each network wait (connect, each read), not
    the whole download, so a server trickling bytes slowly could otherwise
    still hold the thread for a long time; the deadline here caps that.
    """
    deadline = time.monotonic() + _FETCH_TIMEOUT_SECONDS
    chunks = []
    size = 0
    with client.stream("GET", url) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > _MAX_FEED_BYTES:
                raise FeedFetchError(f"фід більший за {_MAX_FEED_BYTES} байт")
            if time.monotonic() > deadline:
                raise FeedFetchError(f"завантаження довше за {_FETCH_TIMEOUT_SECONDS} с")
            chunks.append(chunk)
    return b"".join(chunks)


def _entry_guid(entry) -> str | None:
    """A feed entry's stable identity: its id/guid if the feed provides
    one, else its link. Preferred over the entry's title for dedup, since
    a title can get a minor edit between polls, or two unrelated entries
    can coincidentally share one.
    """
    guid = getattr(entry, "id", None)
    if guid:
        return str(guid)
    link = getattr(entry, "link", None)
    return str(link) if link else None


_IMG_SRC_RE = re.compile(r"""<img\b[^>]*?\bsrc=["']([^"']+)["']""", re.IGNORECASE)


def _http_url(value) -> str | None:
    url = str(value or "").strip()
    return url if url.startswith(("http://", "https://")) else None


def _entry_image(entry) -> str | None:
    """The entry's image, if the feed provides one, in the order feeds most
    commonly carry it: Media RSS (<media:content>, <media:thumbnail>), an
    image <enclosure>, then the first <img> in the summary/content HTML."""
    for media in getattr(entry, "media_content", None) or []:
        medium = media.get("medium")
        mime = str(media.get("type") or "")
        if medium == "image" or mime.startswith("image/") or (medium is None and not mime):
            if url := _http_url(media.get("url")):
                return url
    for thumbnail in getattr(entry, "media_thumbnail", None) or []:
        if url := _http_url(thumbnail.get("url")):
            return url
    for link in getattr(entry, "links", None) or []:
        if link.get("rel") == "enclosure" and str(link.get("type") or "").startswith("image/"):
            if url := _http_url(link.get("href")):
                return url
    html_parts = [getattr(entry, "summary", "") or ""]
    html_parts += [c.get("value", "") for c in getattr(entry, "content", None) or []]
    for part in html_parts:
        if match := _IMG_SRC_RE.search(part):
            if url := _http_url(html.unescape(match.group(1))):
                return url
    return None


class RssFeedService:
    """Fetches new articles from each chat's RSS feeds and stores them.

    Depends on ArticleRepository (to check for duplicates and persist new
    articles) and RssLinkRepository (to read which feeds a chat follows)
    through constructor injection, rather than importing the persistence
    layer's free functions directly.

    `download` fetches a feed URL's raw body; it defaults to download_feed
    with a fresh HTTP client. Its result is handed to feedparser.parse.
    """

    def __init__(
        self,
        article_repository: ArticleRepository,
        rss_link_repository: RssLinkRepository,
        download: Callable[[str], bytes] | None = None,
    ):
        self._articles = article_repository
        self._rss_links = rss_link_repository
        self._download = download or functools.partial(download_feed, client=make_http_client())

    def get_feeds_for_chat(self, chat_id) -> list[str]:
        """Return all active RSS URLs for a specific chat."""
        links = self._rss_links.get_for_chat(str(chat_id))
        urls = []
        for item in links:
            url = str(item.get("url", "")).strip()
            if url:
                urls.append(url)
        print(f"Завантажені RSS для chat_id={chat_id}: {urls}")
        return urls

    # ----------------- Початок функції витягування статей з rss -----------------
    @retry(
        max_retries=3,
        delay=2,
        on_retry=lambda exc, attempt, total, self, url, chat_id: print(
            f"⚠️ Помилка при парсингу RSS {url} (спроба {attempt}/{total}): {exc}"
        ),
        on_failure=lambda exc, self, url, chat_id: print(f"⏹ Вичерпані спроби для {url}"),
    )
    def _parse_and_store_feed(self, url, chat_id):
        """Parse a single RSS feed and store any of its newest entries that
        aren't already known."""
        feed = feedparser.parse(self._download(url))
        if getattr(feed, "bozo", False) and not feed.entries:
            # bozo alone isn't fatal: many real feeds have minor XML quirks
            # feedparser still recovers entries from despite flagging them.
            # bozo with zero entries means the parse genuinely failed (an
            # HTML error page, not XML at all, ...; network failures already
            # raised from the download), which feedparser reports by
            # quietly returning an empty result
            # rather than raising. Surface it as an exception so the retry
            # decorator above actually retries and eventually logs, instead
            # of silently treating a broken feed as "nothing new this poll".
            raise FeedFetchError(getattr(feed, "bozo_exception", "unknown feedparser error"))

        for entry in feed.entries[:_MAX_ENTRIES_PER_POLL]:
            if not hasattr(entry, 'published_parsed'):
                continue

            guid = _entry_guid(entry)
            duplicate = (
                self._articles.exists_by_guid(guid, chat_id)
                if guid
                else self._articles.exists(entry.title, chat_id)
            )
            if duplicate:
                print(f"Пропускаємо. Стаття '{entry.title}' вже існує для чату {chat_id}.")
                continue

            article = Article(
                title=entry.title,
                url=entry.link,
                summary=getattr(entry, 'summary', ''),
                published=datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc),
                is_sent=False,
                chat_id=str(chat_id),
                guid=guid,
                image_url=_entry_image(entry),
            )
            self._articles.create([article], chat_id=str(chat_id))
            print(f"Збережено нову статтю для чату {chat_id}: '{entry.title}'")

    def fetch_new_articles(self, chat_id, rss_feeds):
        """
        Перевіряє всі RSS-фіди конкретного чату на наявність нових статей з retry механізмом.
        """
        if not rss_feeds:
            return []

        for url in rss_feeds:
            self._parse_and_store_feed(url, chat_id)
        return []
    # ----------------- Кінець функції витягування статей з rss -----------------
