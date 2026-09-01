import asyncio
from app.rss_parser import fetch_articles, reed_rss
from app.news_generator import generate_news
from app.telegram_bot import telegram_bot
from app.mongo import get_article, mark_article_as_sent


async def job():
    """Main job: Fetch news and send to all registered chats."""
    RSS_FEEDS = reed_rss()
    fetched_article = fetch_articles(RSS_FEEDS)

    selected_article = get_article()
    if not selected_article:
        print("❌ Немає нових статей для відправки")
        return
    
    print(f"✍️ Вибрана стаття: '{selected_article['title']}'")
    news_text = generate_news(selected_article)

    # SEND TO ALL ACTIVE CHATS FROM DB
    results = await telegram_bot.send_to_all_chats(news_text)
    
    # Mark as sent only if sent to at least one chat
    if any(results.values()):
        mark_article_as_sent(selected_article['_id'])
        print(f"📊 Відправлено в {sum(results.values())}/{len(results)} чатів")
    else:
        print("❌ Не вдалося відправити статтю")
