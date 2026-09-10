from google import genai

from app.db.prompt_repository import PromptRepository
from app.models import Article
from app.retry import retry


class EmptyGenerationError(Exception):
    """Gemini returned a response with no candidates."""


class NewsGenerator:
    """Rewrites a raw article into a chat-ready news post via the Gemini API.

    Depends on PromptRepository (to resolve the per-chat or default prompt)
    through constructor injection. The Gemini client itself is created once
    per instance rather than shared as a module-level global.
    """

    def __init__(self, model: str, prompt_repository: PromptRepository, client: genai.Client | None = None):
        self._model = model
        self._prompts = prompt_repository
        self._client = client or genai.Client()
        print("Клієнт Gemini ініціалізовано.")

    @retry(
        max_retries=3,
        delay=2,
        on_retry=lambda exc, attempt, total, self, prompt: print(
            f"⚠️ Помилка при генерації новини (спроба {attempt}/{total}): {exc}"
        ),
        on_failure=lambda exc, self, prompt: print("⏹ Вичерпані всі спроби генерації новини."),
    )
    def _generate_content(self, prompt):
        response = self._client.models.generate_content(model=self._model, contents=prompt)
        if not response.candidates:
            # Treat an empty response the same as a transient failure so it
            # goes through the same retry+backoff path instead of looping
            # immediately with no delay.
            raise EmptyGenerationError("Gemini повернув порожню відповідь.")
        return response.candidates[0].content.parts[0].text.strip()

    def generate(self, article: Article, chat_id=None) -> str:
        """
        Генерує текст новини через GEMINI API з retry механізмом.
        Якщо для чату є custom prompt, він має пріоритет над prompt.txt.
        """
        prompt_template = (
            self._prompts.get_for_chat(str(chat_id))
            if chat_id is not None
            else self._prompts.get_for_chat("default")
        )

        prompt = prompt_template.format(
            title=article.title,
            summary=article.summary,
            url=article.url
        )

        text = self._generate_content(prompt)
        if text is None:
            return "⚠️ Gemini не повернув текст."

        print(f"Статтю '{article.title}' переписано")
        return text
