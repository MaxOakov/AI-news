import asyncio

from google import genai

from app.db.prompt_repository import PromptRepository
from app.models import Article
from app.retry import retry_async


class EmptyGenerationError(Exception):
    """Gemini returned a response with no candidates."""


class NewsGenerator:
    """Rewrites a raw article into a chat-ready news post via the Gemini API.

    Depends on PromptRepository (to resolve the per-chat or default prompt)
    through constructor injection. The Gemini client itself is created once
    per instance rather than shared as a module-level global.

    Uses the SDK's native async client (client.aio) so a generation call
    doesn't block the event loop; PromptRepository's own lookup is still a
    synchronous pymongo call, so it's offloaded via asyncio.to_thread.
    """

    def __init__(self, model: str, prompt_repository: PromptRepository, client: genai.Client | None = None):
        self._model = model
        self._prompts = prompt_repository
        self._client = client or genai.Client()
        print("Клієнт Gemini ініціалізовано.")

    @retry_async(
        max_retries=3,
        delay=2,
        on_retry=lambda exc, attempt, total, self, prompt: print(
            f"⚠️ Помилка при генерації новини (спроба {attempt}/{total}): {exc}"
        ),
        on_failure=lambda exc, self, prompt: print("⏹ Вичерпані всі спроби генерації новини."),
    )
    async def _generate_content(self, prompt):
        response = await self._client.aio.models.generate_content(model=self._model, contents=prompt)
        if not response.candidates:
            # Treat an empty response the same as a transient failure so it
            # goes through the same retry+backoff path instead of looping
            # immediately with no delay.
            raise EmptyGenerationError("Gemini повернув порожню відповідь.")
        return response.candidates[0].content.parts[0].text.strip()

    async def generate(self, article: Article, chat_id=None) -> str:
        """
        Генерує текст новини через GEMINI API з retry механізмом.
        Якщо для чату є custom prompt, він має пріоритет над prompt.txt.
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

        text = await self._generate_content(prompt)
        if text is None:
            return "⚠️ Gemini не повернув текст."

        print(f"Статтю '{article.title}' переписано")
        return text
