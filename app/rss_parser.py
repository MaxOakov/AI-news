import feedparser
import datetime
import time
from app.mongo import article_exists, create_article, get_chat_rss_links


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
def fetch_articles_for_chat(chat_id, rss_feeds):
    """
    Перевіряє всі RSS-фіди конкретного чату на наявність нових статей з retry механізмом.
    """
    if not rss_feeds:
        return []

    max_retries = 3
    for url in rss_feeds:
        for retry_count in range(max_retries):
            try:
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
                break
            except Exception as e:
                print(f"⚠️ Помилка при парсингу RSS {url} (спроба {retry_count + 1}/{max_retries}): {e}")
                if retry_count < max_retries - 1:
                    time.sleep(2)
                else:
                    print(f"⏹ Вичерпані спроби для {url}")
    return []
# ----------------- Кінець функції витягування статей з rss -----------------
