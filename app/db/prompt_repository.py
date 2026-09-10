from datetime import datetime
from pathlib import Path

from app.db.database import Database
from app.retry import retry

# app/db/prompt_repository.py -> app/db -> app -> project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class InvalidPromptError(ValueError):
    """A custom prompt isn't usable as a str.format() template with the
    {title}/{summary}/{url} placeholders NewsGenerator fills in.

    Raised at save time so a typo in a chat's /setprompt text can't
    silently break every future news run for that chat with no clear
    indication of why.
    """


def _validate_prompt_template(text: str) -> None:
    try:
        text.format(title="", summary="", url="")
    except Exception as exc:
        raise InvalidPromptError(
            "Промпт має використовувати лише плейсхолдери {title}, {summary}, {url} "
            f"у форматі str.format(): {exc}"
        ) from exc


class PromptRepository:
    """Resolves the Gemini rewrite prompt for a chat: a per-chat custom
    prompt stored in the `chat_prompts` collection takes priority, falling
    back to the project's prompt.txt file.
    """

    def __init__(self, database: Database):
        self._db = database

    def get_default_text(self) -> str:
        """Load the default prompt from the project root prompt.txt file."""
        prompt_path = _PROJECT_ROOT / "prompt.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        legacy_path = _PROJECT_ROOT / "prompt_anikoe.txt"
        if legacy_path.exists():
            return legacy_path.read_text(encoding="utf-8")
        return "Rewrite the following news in a friendly gaming-news tone. {title}\n{summary}\n{url}"

    @retry(
        max_retries=3,
        delay=1,
        on_retry=lambda exc, attempt, total, *a, **kw: print(
            f"⚠️ Помилка при збереженні prompt (спроба {attempt}/{total}): {exc}"
        ),
    )
    def _write_custom(self, chat_id: str, cleaned: str):
        return self._db.chat_prompts.update_one(
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

    def save_custom(self, chat_id: str, custom_prompt: str):
        """Save a custom prompt for a particular chat.

        Raises InvalidPromptError if the text isn't a usable str.format()
        template, before ever touching the database.
        """
        cleaned = custom_prompt.strip()
        if not cleaned:
            return None
        _validate_prompt_template(cleaned)
        return self._write_custom(chat_id, cleaned)

    def get_custom(self, chat_id: str):
        """Return the custom prompt for a chat, or None if it is not set."""
        doc = self._db.chat_prompts.find_one({"chat_id": str(chat_id)})
        if not doc:
            return None
        prompt = str(doc.get("custom_prompt", "")).strip()
        return prompt or None

    @retry(
        max_retries=3,
        delay=1,
        on_retry=lambda exc, attempt, total, *a, **kw: print(
            f"⚠️ Помилка при скиданні prompt (спроба {attempt}/{total}): {exc}"
        ),
    )
    def reset_custom(self, chat_id: str):
        """Remove the custom prompt for a chat and fall back to the default one."""
        return self._db.chat_prompts.delete_one({"chat_id": str(chat_id)})

    def get_for_chat(self, chat_id: str) -> str:
        """Resolve the prompt for this chat: per-chat custom prompt first, default prompt as fallback."""
        custom_prompt = self.get_custom(str(chat_id))
        if custom_prompt:
            return custom_prompt
        return self.get_default_text()
