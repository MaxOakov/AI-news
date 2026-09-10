import feedparser
import datetime
from app.mongo import article_exists, create_article, get_chat_rss_links
from app.retry import retry


# Read RSS links per chat from MongoDB, no global file state.
def get_chat_rss_feeds(chat_id):
    """Return all active RSS URLs for a specific chat."""
    links = get_chat_rss_links(str(chat_id))
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
    on_retry=lambda exc, attempt, total, url, chat_id: print(
        f"⚠️ Помилка при парсингу RSS {url} (спроба {attempt}/{total}): {exc}"
    ),
    on_failure=lambda exc, url, chat_id: print(f"⏹ Вичерпані спроби для {url}"),
)
def _parse_and_store_feed(url, chat_id):
    """Parse a single RSS feed and store its newest entry if it's not already known."""
    feed = feedparser.parse(url)
    for entry in feed.entries[:1]:
        if hasattr(entry, 'published_parsed'):
            if article_exists(entry.title, chat_id):
                print(f"Пропускаємо. Стаття '{entry.title}' вже існує для чату {chat_id}.")
                continue
            create_article([{
                "title": entry.title,
                "url": entry.link,
                "summary": getattr(entry, 'summary', ''),
                "published": datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc),
                "is_sent": False,
                "chat_id": str(chat_id),
            }], chat_id=str(chat_id))
            print(f"Збережено нову статтю для чату {chat_id}: '{entry.title}'")


def fetch_articles_for_chat(chat_id, rss_feeds):
    """
    Перевіряє всі RSS-фіди конкретного чату на наявність нових статей з retry механізмом.
    """
    if not rss_feeds:
        return []

    for url in rss_feeds:
        _parse_and_store_feed(url, chat_id)
    return []
# ----------------- Кінець функції витягування статей з rss -----------------
