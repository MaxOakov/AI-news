from app.rss_parser import fetch_articles, reed_rss
from app.news_generator import generate_news
from app import loop
from app.telegram_bot import send_all
from app.telegram_bot import send_all  # приклад, якщо є

# Головна задача
async def job():
    feed = reed_rss()
    fetched_article = fetch_articles(feed)
    news_text = generate_news(fetched_article)
    await send_all(news_text)