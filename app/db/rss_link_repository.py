from datetime import datetime

from app.db.database import Database
from app.retry import retry


class RssLinkRepository:
    """Persistence for per-chat RSS feed URLs, backed by the `rss_links` collection."""

    def __init__(self, database: Database):
        self._db = database

    @retry(
        max_retries=3,
        delay=1,
        on_retry=lambda exc, attempt, total, *a, **kw: print(
            f"⚠️ Помилка при збереженні RSS-лінка (спроба {attempt}/{total}): {exc}"
        ),
    )
    def save(self, chat_id: str, rss_url: str):
        """Store a single RSS feed URL for a chat."""
        normalized_url = rss_url.strip()
        return self._db.rss_links.update_one(
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

    def get_for_chat(self, chat_id: str):
        """Return all active RSS links for a particular chat."""
        return list(self._db.rss_links.find({"chat_id": str(chat_id), "is_active": True}))

    def get_all(self):
        """Return all active RSS links across every chat."""
        return list(self._db.rss_links.find({"is_active": True}))

    @retry(
        max_retries=3,
        delay=1,
        on_retry=lambda exc, attempt, total, *a, **kw: print(
            f"⚠️ Помилка при видаленні RSS-лінка (спроба {attempt}/{total}): {exc}"
        ),
    )
    def remove(self, chat_id: str, rss_url: str):
        """Remove a RSS link for a chat."""
        return self._db.rss_links.delete_one({"chat_id": str(chat_id), "url": rss_url.strip()})
