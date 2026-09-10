import feedparser
import datetime

from app.db.article_repository import ArticleRepository
from app.db.rss_link_repository import RssLinkRepository
from app.models import Article
from app.retry import retry

# How many of a feed's most recent entries to check per poll. Bounded so a
# feed that suddenly dumps its whole archive can't blow up one poll, but
# large enough that a feed publishing faster than the hourly schedule
# doesn't silently lose everything past the single newest item.
_MAX_ENTRIES_PER_POLL = 3


class FeedFetchError(Exception):
    """feedparser reported a parsing/fetch problem and returned nothing usable."""


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


class RssFeedService:
    """Fetches new articles from each chat's RSS feeds and stores them.

    Depends on ArticleRepository (to check for duplicates and persist new
    articles) and RssLinkRepository (to read which feeds a chat follows)
    through constructor injection, rather than importing the persistence
    layer's free functions directly.
    """

    def __init__(self, article_repository: ArticleRepository, rss_link_repository: RssLinkRepository):
        self._articles = article_repository
        self._rss_links = rss_link_repository

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
        feed = feedparser.parse(url)
        if getattr(feed, "bozo", False) and not feed.entries:
            # bozo alone isn't fatal: many real feeds have minor XML quirks
            # feedparser still recovers entries from despite flagging them.
            # bozo with zero entries means the fetch/parse genuinely failed
            # (feed down, unreachable, not XML at all, ...), which
            # feedparser reports by quietly returning an empty result
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
