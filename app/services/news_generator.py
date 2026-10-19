import asyncio

from google import genai

from app.db.prompt_repository import PromptRepository
from app.services.model_settings import GeminiModelSettings
from app.models import Article
from app.retry import retry_async


class EmptyGenerationError(Exception):
    """Gemini returned a response with no candidates."""


class NewsGenerator:
    """Rewrites a raw article into a chat-ready news post via the Gemini API.

    Depends on PromptRepository (to resolve the per-chat or default prompt)
    and GeminiModelSettings (the per-chat or default model) through
    constructor injection. The Gemini client itself is created once
    per instance rather than shared as a module-level global.

    Uses the SDK's native async client (client.aio) so a generation call
    doesn't block the event loop; PromptRepository's own lookup is still a
    synchronous pymongo call, so it's offloaded via asyncio.to_thread.
    """

    def __init__(
        self,
        model_settings: GeminiModelSettings,
        prompt_repository: PromptRepository,
        client: genai.Client | None = None,
    ):
        self._models = model_settings
        self._prompts = prompt_repository
        self._client = client or genai.Client()
        print("Клієнт Gemini ініціалізовано.")

    @retry_async(
        max_retries=3,
        delay=2,
        on_retry=lambda exc, attempt, total, self, prompt, model: print(
            f"⚠️ Помилка при генерації новини (спроба {attempt}/{total}): {exc}"
        ),
        on_failure=lambda exc, self, prompt, model: print("⏹ Вичерпані всі спроби генерації новини."),
    )
    async def _generate_content(self, prompt, model):
        response = await self._client.aio.models.generate_content(model=model, contents=prompt)
        if not response.candidates:
            # Treat an empty response the same as a transient failure so it
            # goes through the same retry+backoff path instead of looping
            # immediately with no delay.
            raise EmptyGenerationError("Gemini повернув порожню відповідь.")
        return response.candidates[0].content.parts[0].text.strip()

    async def generate(self, article: Article, chat_id=None) -> str | None:
        """
        Генерує текст новини через GEMINI API з retry механізмом.
        Якщо для чату є custom prompt, він має пріоритет над prompt.txt,
        а обрана для чату модель — над моделлю за замовчуванням.

        Returns None once every retry has failed, so the caller doesn't
        post an error message to the chat in place of the news.
        """
        prompt_template = await asyncio.to_thread(
            self._prompts.get_for_chat,
            str(chat_id) if chat_id is not None else "default",
        )

        prompt = prompt_template.format(
            title=article.title,
            summary=article.summary,
            url=article.url
        )

        # Looked up on every call, so a chat's /gemini_version choice applies to its next post.
        model = await asyncio.to_thread(self._models.model_for_chat, chat_id)
        text = await self._generate_content(prompt, model)
        if text is None:
            return None

        print(f"Статтю '{article.title}' переписано")
        return text
