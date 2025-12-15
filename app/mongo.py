from app.config import MONGODB_URL
from pymongo import MongoClient


connection_string = MONGODB_URL
client = MongoClient(connection_string)
try:
    client.news.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
    print()
except Exception as e:
    print(e)

# Перевірка підключення та виведення баз даних і колекційq
dbs = client.list_database_names()
test_db = client.news
collections = test_db.list_collection_names()
print("Databases:", dbs)
print("Collections in 'news' database:", collections)
print()


def create_article(new_articles):
    """Зберігає статтю в MongoDB."""
    news_collection = test_db.articles
    for article in new_articles:
        result = news_collection.insert_one(article)
        print(f"Стаття збережена з id: {result.inserted_id}")


def get_article():
    """Отримує статтю з бази даних."""
    saved_articles = test_db.articles.find_one(
        {
            "$or": [
                {"is_sent": False},
                {"is_sent": None},
                {"is_sent": {"$exists": False}}
            ]
        },
        sort=[("published", -1)]
    )
    return saved_articles


def article_exists(title):
    """Перевіряє, чи існує стаття з таким заголовком в базі даних."""
    news_collection = test_db.articles
    return news_collection.count_documents({"title": title}, limit = 1) != 0


def mark_article_as_sent(article_id):
    """Позначає статтю як відправлену в Telegram."""
    news_collection = test_db.articles
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
    news_collection = test_db.articles
    latest_article = news_collection.find_one(sort=[("published", -1)])
    if latest_article:
        return latest_article["published"]
    return None
