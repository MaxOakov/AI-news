from google import genai
from app.config import GEMINI_MODEL
from app.mongo import get_prompt_for_chat
from app.retry import retry


# Ініціалізація клієнта Ggoogle Gemini API та Telegram-бота
client = genai.Client()
print("Клієнт Gemini ініціалізовано.")


class EmptyGenerationError(Exception):
    """Gemini returned a response with no candidates."""


@retry(
    max_retries=3,
    delay=2,
    on_retry=lambda exc, attempt, total, *a, **kw: print(
        f"⚠️ Помилка при генерації новини (спроба {attempt}/{total}): {exc}"
    ),
    on_failure=lambda exc, *a, **kw: print("⏹ Вичерпані всі спроби генерації новини."),
)
def _generate_content(prompt):
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    if not response.candidates:
        # Treat an empty response the same as a transient failure so it
        # goes through the same retry+backoff path instead of looping
        # immediately with no delay.
        raise EmptyGenerationError("Gemini повернув порожню відповідь.")
    return response.candidates[0].content.parts[0].text.strip()


def generate_news(article, chat_id=None):
    """
    Генерує текст новини через GEMINI API з retry механізмом.
    Якщо для чату є custom prompt, він має пріоритет над prompt.txt.
    """
    prompt_template = get_prompt_for_chat(str(chat_id)) if chat_id is not None else get_prompt_for_chat("default")

    prompt = prompt_template.format(
        title=article["title"],
        summary=article["summary"],
        url=article["url"]
    )

    text = _generate_content(prompt)
    if text is None:
        return "⚠️ Gemini не повернув текст."

    print(f"Статтю '{article['title']}' переписано")
    return text
