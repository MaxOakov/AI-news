from pathlib import Path
from app.config import MONGODB_URL
from pymongo import MongoClient
from datetime import datetime
import time


client = None
test_db = None


def get_default_prompt_text():
    """Load the default prompt from the project root prompt.txt file."""
    prompt_path = Path(__file__).resolve().parent.parent / "prompt.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    legacy_path = Path(__file__).resolve().parent.parent / "prompt_anikoe.txt"
    if legacy_path.exists():
        return legacy_path.read_text(encoding="utf-8")
    return "Rewrite the following news in a friendly gaming-news tone. {title}\n{summary}\n{url}"


def get_db():
    """Create and cache the MongoDB database connection lazily."""
    global client, test_db

    if test_db is not None:
        return test_db

    if not MONGODB_URL:
        raise RuntimeError("MONGODB_URL is not configured.")

    client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        test_db = client["news"]
        print("Pinged your deployment. You successfully connected to MongoDB!")
        return test_db
    except Exception as exc:
        raise RuntimeError(f"MongoDB connection failed: {exc}") from exc



def create_article(new_articles, chat_id=None):
    """Зберігає статтю в MongoDB з retry механізмом."""
    max_retries = 3
    news_collection = get_db().articles
    for article in new_articles:
        if chat_id is not None:
            article["chat_id"] = str(chat_id)
        for retry_count in range(max_retries):
            try:
                result = news_collection.insert_one(article)
                print(f"Стаття збережена з id: {result.inserted_id}")
                break
            except Exception as e:
                print(f"⚠️ Помилка при збереженні статті (спроба {retry_count + 1}/{max_retries}): {e}")
                if retry_count < max_retries - 1:
                    time.sleep(1)
                else:
                    print(f"⏹ Не вдалося зберегти статтю: {article.get('title', 'Unknown')}")


def get_article(chat_id=None):
    """Отримує статтю з бази даних з retry механізмом."""
    max_retries = 3
    query = {
        "$or": [
            {"is_sent": False},
            {"is_sent": None},
            {"is_sent": {"$exists": False}}
        ]
    }
    if chat_id is not None:
        query["chat_id"] = str(chat_id)

    for retry_count in range(max_retries):
        try:
            saved_articles = get_db().articles.find_one(
                query,
                sort=[("published", -1)]
            )
            return saved_articles
        except Exception as e:
            print(f"⚠️ Помилка при отриманні статті (спроба {retry_count + 1}/{max_retries}): {e}")
            if retry_count < max_retries - 1:
                time.sleep(1)
            else:
                print("⏹ Не вдалося отримати статтю з бази даних.")
                return None


def article_exists(title, chat_id=None):
    """Перевіряє, чи існує стаття з таким заголовком в базі даних з retry механізмом."""
    max_retries = 3
    news_collection = get_db().articles
    query = {"title": title}
    if chat_id is not None:
        query["chat_id"] = str(chat_id)
    for retry_count in range(max_retries):
        try:
            return news_collection.count_documents(query, limit=1) != 0
        except Exception as e:
            print(f"⚠️ Помилка при перевірці статті (спроба {retry_count + 1}/{max_retries}): {e}")
            if retry_count < max_retries - 1:
                time.sleep(1)
            else:
                print(f"⏹ Не вдалося перевірити наявність статті: {title}")
                return False


def mark_article_as_sent(article_id):
    """Позначає статтю як відправлену в Telegram."""
    news_collection = get_db().articles
    result = news_collection.update_one(
        {"_id": article_id},
        {"$set": {"is_sent": True}}
    )
    if result.modified_count > 0:
        print(f"Стаття з id {article_id} позначена як відправлена.")
    else:
        print(f"Не вдалося позначити статтю з id {article_id} як відправлену.")


def get_latest_article_time():
    """Отримує час публікації найновішої статті в базі даних."""
    news_collection = get_db().articles
    latest_article = news_collection.find_one(sort=[("published", -1)])
    if latest_article:
        return latest_article["published"]
    return None


# Add these functions to mongo.py
def register_chat(chat_id: str, chat_name: str, chat_type: str = "private", message_thread_id: int | None = None):
    """Save chat to DB, including optional forum topic id."""
    chats_collection = get_db().chats
    payload = {
        "chat_id": str(chat_id),
        "chat_name": chat_name,
        "chat_type": chat_type,
        "is_active": True,
    }
    if message_thread_id is not None:
        payload["message_thread_id"] = int(message_thread_id)

    return chats_collection.update_one(
        {"chat_id": str(chat_id)},
        {
            "$set": payload,
            "$setOnInsert": {"added_at": datetime.now()}
        },
        upsert=True
    )


def get_all_active_chats():
    """Retrieve all active chats from DB."""
    chats_collection = get_db().chats
    return list(chats_collection.find({"is_active": True}))


def deactivate_chat(chat_id: str):
    """Mark chat as inactive."""
    chats_collection = get_db().chats
    return chats_collection.update_one(
        {"chat_id": str(chat_id)},
        {"$set": {"is_active": False}}
    )


def save_rss_link(chat_id: str, rss_url: str):
    """Store a single RSS feed URL for a chat."""
    rss_collection = get_db().rss_links
    normalized_url = rss_url.strip()
    return rss_collection.update_one(
        {"chat_id": str(chat_id), "url": normalized_url},
        {
            "$set": {
                "chat_id": str(chat_id),
                "url": normalized_url,
                "is_active": True,
                "updated_at": datetime.now(),
            },
            "$setOnInsert": {"created_at": datetime.now()},
        },
        upsert=True,
    )


def get_chat_rss_links(chat_id: str):
    """Return all active RSS links for a particular chat."""
    rss_collection = get_db().rss_links
    return list(rss_collection.find({"chat_id": str(chat_id), "is_active": True}))


def get_all_rss_links():
    """Return all active RSS links across every chat."""
    rss_collection = get_db().rss_links
    return list(rss_collection.find({"is_active": True}))


def remove_rss_link(chat_id: str, rss_url: str):
    """Remove a RSS link for a chat."""
    rss_collection = get_db().rss_links
    return rss_collection.delete_one({"chat_id": str(chat_id), "url": rss_url.strip()})


def save_chat_prompt(chat_id: str, custom_prompt: str):
    """Save a custom prompt for a particular chat."""
    chat_prompts = get_db().chat_prompts
    cleaned = custom_prompt.strip()
    if not cleaned:
        return None
    return chat_prompts.update_one(
        {"chat_id": str(chat_id)},
        {
            "$set": {
                "chat_id": str(chat_id),
                "custom_prompt": cleaned,
                "updated_at": datetime.now(),
            },
            "$setOnInsert": {"created_at": datetime.now()},
        },
        upsert=True,
    )


def get_chat_prompt(chat_id: str):
    """Return the custom prompt for a chat, or None if it is not set."""
    chat_prompts = get_db().chat_prompts
    doc = chat_prompts.find_one({"chat_id": str(chat_id)})
    if not doc:
        return None
    prompt = str(doc.get("custom_prompt", "")).strip()
    return prompt or None


def reset_chat_prompt(chat_id: str):
    """Remove the custom prompt for a chat and fall back to the default one."""
    chat_prompts = get_db().chat_prompts
    return chat_prompts.delete_one({"chat_id": str(chat_id)})


def get_prompt_for_chat(chat_id: str):
    """Resolve the prompt for this chat: per-chat custom prompt first, default prompt as fallback."""
    custom_prompt = get_chat_prompt(str(chat_id))
    if custom_prompt:
        return custom_prompt
    return get_default_prompt_text()