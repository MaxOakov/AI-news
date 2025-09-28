import feedparser
from datetime import datetime


#Створюємо змінну, яка зберігатиме в собі новини з RSS стрічок
RSS_FEEDS = []

# Читаємо RSS-стрічки для парсингу з файлу rss_feed_links та добавляємо їх в list
def reed_rss(): 
    with open('rss_feed_links.txt', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                RSS_FEEDS.append(line)
    return RSS_FEEDS


# ----------------- Функції -----------------
def fetch_articles(RSS_FEEDS):
    """
    Завантажує статті з RSS-фідів
    Повертає list[dict]: title, link, summary.
    """
    latest_article = []
    latest_time = None
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            # Беремо тільки, якщо є дата публікації
            if hasattr(entry, 'published_parsed'):
                entry_time = datetime(*entry.published_parsed[:6])
                if latest_time is None or entry_time > latest_time:
                    latest_time = entry_time
                    latest_article = {
                        "title": entry.title,
                        "link": entry.link,
                        "summary": getattr(entry, 'summary', ''),
                        "published": entry_time 
                        }

    if latest_article:
        print(f"Найсвіжіша новина: {latest_article['title']}")
    else:
        print("Немає новин із датами публікації.")
    return latest_article

    