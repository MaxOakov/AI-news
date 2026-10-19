from datetime import datetime, timezone

from pymongo import ASCENDING

from app.db.database import Database

STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"


class InstagramPostRepository:
    """Which Telegram posts were already taken to Instagram, backed by the
    `instagram_posts` collection.

    A post is keyed by its chat and `post_key` (the message id, or the
    media_group_id for an album), so the same post is never published twice,
    even if Telegram redelivers its update after a restart.
    """

    def __init__(self, database: Database):
        self._db = database

    def ensure_indexes(self):
        self._db.instagram_posts.create_index(
            [("chat_id", ASCENDING), ("post_key", ASCENDING)], unique=True
        )

    def claim(self, chat_id, post_key) -> bool:
        """Record a post as being published. Returns False if it was
        already claimed (published, failed or in progress), True if this
        call claimed it and the caller should go ahead."""
        result = self._db.instagram_posts.update_one(
            {"chat_id": str(chat_id), "post_key": str(post_key)},
            {"$setOnInsert": {"status": STATUS_PENDING, "created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return result.upserted_id is not None

    def mark_published(self, chat_id, post_key, media_id: str):
        self._set(chat_id, post_key, {"status": STATUS_PUBLISHED, "ig_media_id": media_id})

    def mark_failed(self, chat_id, post_key, error: str):
        self._set(chat_id, post_key, {"status": STATUS_FAILED, "error": error})

    def _set(self, chat_id, post_key, fields: dict):
        self._db.instagram_posts.update_one(
            {"chat_id": str(chat_id), "post_key": str(post_key)}, {"$set": fields}
        )
