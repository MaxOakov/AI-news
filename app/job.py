import asyncio
from app.rss_parser import fetch_articles, reed_rss
from app.news_generator import generate_news
from app.telegram_bot import send_telegram
from app.mongo import get_article, mark_article_as_sent


# Головна задача
async def job():

    """Один цикл отримання новин."""
    RSS_FEEDS = reed_rss()
    fetched_article = fetch_articles(RSS_FEEDS)

    # Якщо новин нема — пропускаємо
    selected_article = get_article()
    print(f"Вибрана стаття для обробки: '{selected_article['title']}'")
    # Генеруємо текст новини
    news_text = generate_news(selected_article)

    # Відправляємо в Telegram
    await send_telegram(news_text) # Відправляємо новину у Telegram
    mark_article_as_sent(selected_article['_id']) # Позначаємо як відправлену
    print("📨 Новина відправлена у Telegram.")
    return