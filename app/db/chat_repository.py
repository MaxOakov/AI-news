from datetime import datetime

from app.db.database import Database
from app.models import Chat


class ChatRepository:
    """Persistence for Chat, backed by the `chats` collection."""

    def __init__(self, database: Database):
        self._db = database

    def register(self, chat: Chat):
        """Save chat to DB, including optional forum topic id.

        `message_thread_id` is only written when Chat.to_dict() includes it,
        so registering a chat again without one (e.g. a plain /start) never
        clears a topic id set earlier via /settopic.
        """
        return self._db.chats.update_one(
            {"chat_id": chat.chat_id},
            {
                "$set": chat.to_dict(),
                "$setOnInsert": {"added_at": datetime.now()}
            },
            upsert=True
        )

    def get_all_active(self) -> list[Chat]:
        """Retrieve all active chats from DB."""
        return [Chat.from_dict(doc) for doc in self._db.chats.find({"is_active": True})]

    def deactivate(self, chat_id: str):
        """Mark chat as inactive."""
        return self._db.chats.update_one(
            {"chat_id": str(chat_id)},
            {"$set": {"is_active": False}}
        )
