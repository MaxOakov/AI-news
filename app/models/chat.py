from dataclasses import dataclass


@dataclass
class Chat:
    """A Telegram chat (or forum topic within one) that the bot posts news to.

    Replaces the ad-hoc `{"chat_name": ..., "message_thread_id": ...}` dicts
    that used to live in TelegramBot.chats and travel through job.py.
    """

    chat_id: str
    chat_name: str = "Unknown chat"
    chat_type: str = "private"
    message_thread_id: int | None = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Shape this chat the way MongoDB expects it.

        `message_thread_id` is only included when set, so saving a chat
        without one (e.g. a plain /start) never clobbers a topic id that
        was set earlier via /settopic.
        """
        data = {
            "chat_id": str(self.chat_id),
            "chat_name": self.chat_name,
            "chat_type": self.chat_type,
            "is_active": self.is_active,
        }
        if self.message_thread_id is not None:
            data["message_thread_id"] = int(self.message_thread_id)
        return data

    @classmethod
    def from_dict(cls, doc: dict) -> "Chat":
        """Build a Chat from a MongoDB document."""
        return cls(
            chat_id=str(doc.get("chat_id", "")),
            chat_name=doc.get("chat_name") or "Unknown chat",
            chat_type=doc.get("chat_type", "private"),
            message_thread_id=doc.get("message_thread_id"),
            is_active=bool(doc.get("is_active", True)),
        )
