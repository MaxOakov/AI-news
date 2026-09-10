from app.db.database import Database
from app.models import Article
from app.retry import retry


class ArticleRepository:
    """Persistence for Article, backed by the `articles` collection."""

    def __init__(self, database: Database):
        self._db = database

    @retry(
        max_retries=3,
        delay=1,
        on_retry=lambda exc, attempt, total, *a, **kw: print(
            f"⚠️ Помилка при збереженні статті (спроба {attempt}/{total}): {exc}"
        ),
    )
    def _insert(self, article: Article):
        result = self._db.articles.insert_one(article.to_dict())
        article.id = result.inserted_id
        print(f"Стаття збережена з id: {result.inserted_id}")

    def create(self, articles: list[Article], chat_id=None):
        """Зберігає статті в MongoDB з retry механізмом."""
        for article in articles:
            if chat_id is not None:
                article.chat_id = str(chat_id)
            try:
                self._insert(article)
            except Exception:
                print(f"⏹ Не вдалося зберегти статтю: {article.title}")

    @retry(
        max_retries=3,
        delay=1,
        on_retry=lambda exc, attempt, total, *a, **kw: print(
            f"⚠️ Помилка при отриманні статті (спроба {attempt}/{total}): {exc}"
        ),
    )
    def _find_unsent(self, query):
        return self._db.articles.find_one(query, sort=[("published", -1)])

    def get_next_unsent(self, chat_id=None) -> Article | None:
        """Отримує статтю з бази даних з retry механізмом."""
        query = {
            "$or": [
                {"is_sent": False},
                {"is_sent": None},
                {"is_sent": {"$exists": False}}
            ]
        }
        if chat_id is not None:
            query["chat_id"] = str(chat_id)

        try:
            doc = self._find_unsent(query)
        except Exception:
            print("⏹ Не вдалося отримати статтю з бази даних.")
            return None

        return Article.from_dict(doc) if doc else None

    @retry(
        max_retries=3,
        delay=1,
        on_retry=lambda exc, attempt, total, *a, **kw: print(
            f"⚠️ Помилка при перевірці статті (спроба {attempt}/{total}): {exc}"
        ),
    )
    def _count(self, query):
        return self._db.articles.count_documents(query, limit=1)

    def exists(self, title, chat_id=None) -> bool:
        """Перевіряє, чи існує стаття з таким заголовком в базі даних з retry механізмом."""
        query = {"title": title}
        if chat_id is not None:
            query["chat_id"] = str(chat_id)
        try:
            return self._count(query) != 0
        except Exception:
            print(f"⏹ Не вдалося перевірити наявність статті: {title}")
            return False

    def mark_as_sent(self, article_id):
        """Позначає статтю як відправлену в Telegram."""
        result = self._db.articles.update_one(
            {"_id": article_id},
            {"$set": {"is_sent": True}}
        )
        if result.modified_count > 0:
            print(f"Стаття з id {article_id} позначена як відправлена.")
        else:
            print(f"Не вдалося позначити статтю з id {article_id} як відправлену.")

    def get_latest_published_at(self):
        """Отримує час публікації найновішої статті в базі даних."""
        latest = self._db.articles.find_one(sort=[("published", -1)])
        return latest["published"] if latest else None
