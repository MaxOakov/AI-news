from datetime import datetime

from app.db.database import Database
from app.retry import retry


class ChatModelRepository:
    """Per-chat Gemini model choice, backed by the `chat_models` collection
    (one document per chat that picked its own model)."""

    def __init__(self, database: Database):
        self._db = database

    def get(self, chat_id) -> str | None:
        doc = self._db.chat_models.find_one({"chat_id": str(chat_id)})
        return (doc.get("model") or None) if doc else None

    @retry(
        max_retries=3,
        delay=1,
        on_retry=lambda exc, attempt, total, *a, **kw: print(
            f"⚠️ Помилка при збереженні моделі Gemini (спроба {attempt}/{total}): {exc}"
        ),
    )
    def save(self, chat_id, model: str):
        return self._db.chat_models.update_one(
            {"chat_id": str(chat_id)},
            {
                "$set": {"chat_id": str(chat_id), "model": model, "updated_at": datetime.now()},
                "$setOnInsert": {"created_at": datetime.now()},
            },
            upsert=True,
        )

    def reset(self, chat_id):
        """Forget the chat's choice, so it uses the default model again."""
        return self._db.chat_models.delete_one({"chat_id": str(chat_id)})
