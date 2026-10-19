from app.db.chat_model_repository import ChatModelRepository


class GeminiModelSettings:
    """Which Gemini model each chat's news are written with.

    A chat's own choice (/gemini_version) is stored in MongoDB; chats
    without one use `default_model` (GEMINI_MODEL from .env). Only models
    in `options` can be chosen, and a stored choice that's no longer an
    option falls back to the default instead of breaking generation.
    """

    def __init__(self, repository: ChatModelRepository, options: list[str], default_model: str):
        self._repository = repository
        self._options = list(options)
        self._default = default_model

    @property
    def default(self) -> str:
        return self._default

    @property
    def options(self) -> list[str]:
        return list(self._options)

    def chat_choice(self, chat_id) -> str | None:
        """The model this chat picked itself, or None if it uses the default."""
        try:
            model = self._repository.get(str(chat_id))
        except Exception as exc:
            print(f"⚠️ Не вдалося прочитати модель Gemini чату {chat_id}: {exc}")
            return None
        return model if model in self._options else None

    def model_for_chat(self, chat_id) -> str:
        """The model to generate this chat's news with."""
        if chat_id is None:
            return self._default
        return self.chat_choice(chat_id) or self._default

    def set_for_chat(self, chat_id, model: str) -> None:
        """Raises ValueError for a model not in `options`."""
        if model not in self._options:
            raise ValueError(f"Невідома модель: {model}")
        self._repository.save(str(chat_id), model)

    def reset_for_chat(self, chat_id) -> None:
        self._repository.reset(str(chat_id))
