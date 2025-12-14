import feedparser
from datetime import datetime


# Створюємо змінні
RSS_FEEDS = []
latest_time = None


# Читаємо RSS-стрічки для парсингу з файлу rss_feed_links та добавляємо їх в list але без дублювання, бо швидкість обрбки падає
def reed_rss(): 
    """Читає RSS-посилання з файлу без дублювання."""
    RSS_FEEDS.clear()
    with open('rss_feed_links.txt', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                RSS_FEEDS.append(line)
    print("Завантажені RSS:", RSS_FEEDS)
    return RSS_FEEDS




# ----------------- Функція витягування статті з rss -----------------
def fetch_articles(RSS_FEEDS):
    """
    Завантажує нову статтю, якщо вона новіша за попередню.
    Повертає dict або None.
    """
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if hasattr(entry, 'published_parsed'):
                entry_time = datetime(*entry.published_parsed[:6])

                if newest_time is None or entry_time > newest_time:
                    newest_time = entry_time
                    newest_article = {
                        "title": entry.title,
                        "link": entry.link,
                        "summary": getattr(entry, 'summary', ''),
                        "published": entry_time
                    }

    # Якщо нова стаття знайдена
    if newest_article:
        if latest_time is None or newest_article["published"] > latest_time:
            latest_time = newest_article["published"]
            print(f"✅ Знайдена нова стаття: {newest_article['title']}")
            return newest_article
        else:
            print("ℹ️ Стаття така ж сама, пропускаємо цей цикл.")
            return None

    print("Немає нових статей із датами публікації.")
    return None

# def fetch_articles(RSS_FEEDS):
    """
    Завантажує найсвіжішу статтю з RSS-фідів
    Пропускає, якщо дата публікації збігається з останньою
    """
    global last_published_time
    latest_article = None
    latest_time = None

    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
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
        if last_published_time == latest_time:
            print(f"Стаття та ж сама, що й раніше. Пропускаємо. Наступний запуск о …") 
            return None
        else:
            last_published_time = latest_time
            print(f"Найсвіжіша новина: {latest_article['title']}")
            return latest_article
    else:
        print("Немає новин із датами публікації.")
        return None
    