import asyncio
from app.rss_parser import fetch_articles_for_chat, get_chat_rss_feeds
from app.news_generator import generate_news
from app.telegram_bot import telegram_bot
from app.mongo import get_article, mark_article_as_sent


async def job():
    """Main job: fetch per-chat feeds and send to each registered chat."""
    for chat_id, chat_data in list(telegram_bot.chats.items()):
        rss_feeds = get_chat_rss_feeds(chat_id)
        if not rss_feeds:
            print(f"ℹ️ У чату {chat_id} немає RSS-лінків. Пропускаємо.")
            continue

        fetch_articles_for_chat(chat_id, rss_feeds)
        selected_article = get_article(chat_id)
        if not selected_article:
            print(f"❌ Немає нових статей для відправки в чат {chat_id}")
            continue

        print(f"✍️ Вибрана стаття для чату {chat_id}: '{selected_article['title']}'")
        news_text = generate_news(selected_article)
        message_thread_id = chat_data.get("message_thread_id") if isinstance(chat_data, dict) else None
        sent = await telegram_bot.send_message(
            chat_id,
            news_text,
            message_thread_id=message_thread_id,
        )

        if sent:
            mark_article_as_sent(selected_article['_id'])
            print(f"📊 Відправлено в чат {chat_id}")
        else:
            print(f"❌ Не вдалося відправити статтю в чат {chat_id}")
