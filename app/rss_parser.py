import feedparser
import datetime
from app.mongo import article_exists, create_article
from pprint import pprint


# Створюємо змінні
RSS_FEEDS = []

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

# ----------------- Початок функції витягування статей з rss -----------------
def fetch_articles(RSS_FEEDS):
    """
    Перевіряє всі RSS-фіди на наявність нових статей.
    Повертає список нових статей.
    """ 
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        # limit saved new articles per feed
        for entry in feed.entries[:3]:  # Перевіряємо лише перші 3 статті у фіді
            if hasattr(entry, 'published_parsed'):
                if article_exists(entry.title) == True:
                    print(f"Пропускаємо. Стаття '{entry.title}' вже існує в базі даних.")
                    continue  # Пропускаємо цю статтю, якщо вона вже є в базі даних
                else:
                    create_article([{
                        "title": entry.title,
                        "url": entry.link,
                        "summary": getattr(entry, 'summary', ''),
                        "published": datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc),
                        "is_sent": False
                       }])
                    print(f"Збережено нову статтю: '{entry.title}'")
    return []  # Повертаємо порожній список, якщо немає нових статей


# ----------------- Кінець функції витягування статей з rss -----------------

# reed_rss()  # Викликаємо функцію для початкового завантаження RSS-стрічок
# pprint(RSS_FEEDS)  # Тестовий виклик функції для отримання всіх статей
# articles = fetch_articles(RSS_FEEDS)
# for article in articles:
#     pprint(article['title'])
#     pprint(article['published'])

