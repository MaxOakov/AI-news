from app.rss_parser import fetch_articles, reed_rss
from app.news_generator import generate_news
from app import loop
from app.telegram_bot import send_telegram


# Головна задача
async def job():
    """Один цикл отримання новин."""
    RSS_FEEDS = reed_rss()
    fetched_article = fetch_articles(RSS_FEEDS)

    # Якщо новин нема — пропускаємо
    if fetched_article is None:
        print("👉 Наступна перевірка після запуску скедулера.")
        return

    try:
        # Генеруємо текст новини
        news_text = generate_news(fetched_article)

        # Відправляємо в Telegram
        await send_telegram(news_text)
        print("📨 Новина відправлена у Telegram.")

    except Exception as e:
        print(f"❌ Помилка під час обробки новини: {e}")


# async def job():
    # feed = reed_rss()
    # fetched_article = fetch_articles(feed)
    # if fetched_article is None:
    #     print("Запуск відкладаєтсья")
    #     return
    # news_text = generate_news(fetched_article)
    # await send_all(news_text)