from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import ASCENDING

from app.db.database import Database
from app.models import Article
from app.retry import retry

# How many runs may fail on one article (Gemini returned nothing, Telegram
# rejected the message, ...) before it's skipped for good. get_next_unsent
# returns the same newest unsent article until something newer arrives, so
# without this cap one article that can never be sent would block its
# chat's queue until a newer one turns up (or forever, on a quiet feed).
MAX_SEND_ATTEMPTS = 3


class ArticleRepository:
    """Persistence for Article, backed by the `articles` collection.

    `max_article_age`, if set, limits get_next_unsent to articles published
    within that window. Feeds can add articles faster than one per run gets
    sent; with the newest posted first, the leftovers would otherwise sit in
    the queue indefinitely and surface as stale news whenever the feeds go
    quiet. Articles past the window simply stay in the database unposted.
    """

    def __init__(self, database: Database, max_article_age: timedelta | None = None):
        self._db = database
        self._max_article_age = max_article_age

    def ensure_indexes(self):
        """Create the indexes the hot queries need (no-op if they already exist).

        - (chat_id, guid): the per-entry duplicate check on every feed poll.
        - (chat_id, published): get_next_unsent's filter on the age window
          plus its sort, so it doesn't scan every article a chat ever had.
        """
        self._db.articles.create_index([("chat_id", ASCENDING), ("guid", ASCENDING)])
        self._db.articles.create_index([("chat_id", ASCENDING), ("published", ASCENDING)])
        print("✅ Індекси для статей створено.")

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
        # Descending: the NEWEST unsent article first, so the channel always
        # posts the freshest news. When feeds add articles faster than one
        # per run gets sent, the older ones wait and eventually age out of
        # the max_article_age window unposted, instead of the channel
        # lagging behind the news working through the backlog in order.
        return self._db.articles.find_one(query, sort=[("published", -1)])

    def get_next_unsent(self, chat_id=None) -> Article | None:
        """Отримує найновішу невідправлену статтю з бази даних з retry механізмом."""
        query = {
            "$or": [
                {"is_sent": False},
                {"is_sent": None},
                {"is_sent": {"$exists": False}}
            ],
            "skipped": {"$exists": False},
            # Already drafted and waiting on a reviewer (moderation mode).
            "review_chat_id": {"$exists": False},
        }
        if chat_id is not None:
            query["chat_id"] = str(chat_id)
        if self._max_article_age is not None:
            query["published"] = {"$gte": datetime.now(timezone.utc) - self._max_article_age}

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

    def exists_by_guid(self, guid, chat_id=None) -> bool:
        """Перевіряє, чи існує стаття з таким guid (feed entry id/link) в базі даних.

        More reliable than exists(title, ...): a feed entry's id/link stays
        stable even if its title gets a minor edit, and two unrelated
        entries sharing a title won't be wrongly treated as duplicates.
        """
        query = {"guid": guid}
        if chat_id is not None:
            query["chat_id"] = str(chat_id)
        try:
            return self._count(query) != 0
        except Exception:
            print(f"⏹ Не вдалося перевірити наявність статті: {guid}")
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

    def get_by_id(self, article_id) -> Article | None:
        """Look an article up by its `_id`, given as the string form that
        travels in a Telegram button's callback_data."""
        if isinstance(article_id, str) and ObjectId.is_valid(article_id):
            article_id = ObjectId(article_id)
        doc = self._db.articles.find_one({"_id": article_id})
        return Article.from_dict(doc) if doc else None

    def mark_pending_review(self, article_id, review_chat_id: str, draft_text: str):
        """Record that a draft of this article was sent to a reviewer.

        Takes it out of get_next_unsent (so the next run drafts the next
        article instead of this one again) and keeps the exact text the
        reviewer saw, which is what gets published if they approve it.
        """
        self._db.articles.update_one(
            {"_id": article_id},
            {"$set": {"review_chat_id": str(review_chat_id), "draft_text": draft_text}},
        )

    def mark_skipped(self, article_id):
        """Take an article out of the queue for good (e.g. a reviewer skipped it)."""
        self._db.articles.update_one({"_id": article_id}, {"$set": {"skipped": True}})

    def record_failure(self, article: Article) -> bool:
        """Count one failed generate/send attempt for `article`.

        Once it reaches MAX_SEND_ATTEMPTS the article is flagged `skipped`,
        which takes it out of get_next_unsent so the chat's queue moves on.
        Returns True if the article was skipped by this call.

        Writes the incremented count with $set rather than $inc: a chat is
        never processed by two runs at once (SchedulerService's `_running`
        guard), so the in-memory count is current.
        """
        article.fail_count += 1
        update = {"fail_count": article.fail_count}
        skipped = article.fail_count >= MAX_SEND_ATTEMPTS
        if skipped:
            update["skipped"] = True

        try:
            self._db.articles.update_one({"_id": article.id}, {"$set": update})
        except Exception as exc:
            print(f"⏹ Не вдалося записати невдалу спробу для статті '{article.title}': {exc}")
            return False

        if skipped:
            print(f"⏭ Стаття '{article.title}' пропущена після {article.fail_count} невдалих спроб.")
        else:
            print(f"⚠️ Невдала спроба {article.fail_count}/{MAX_SEND_ATTEMPTS} для статті '{article.title}'.")
        return skipped

