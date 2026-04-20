from google import genai
from pathlib import Path
import time

# Ініціалізація клієнта Ggoogle Gemini API та Telegram-бота
client = genai.Client()
print("Клієнт Gemini ініціалізовано.")


def generate_news(article):
    """
    Генерує текст новини через GEMINI API з retry механізмом.
    """
    prompt_template = Path("prompt.txt").read_text(encoding="utf-8")

    prompt = prompt_template.format(
        title=article["title"],
        summary=article["summary"],
        url=article["url"]
    )

    max_retries = 3
    for retry_count in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite-preview",
                contents=prompt
            )
            if response.candidates:
                print(f"Статтю '{article['title']}' переписано")
                return response.candidates[0].content.parts[0].text.strip()
        except Exception as e:
            print(f"⚠️ Помилка при генерації новини (спроба {retry_count + 1}/{max_retries}): {e}")
            if retry_count < max_retries - 1:
                time.sleep(2)  # Затримка перед повторною спробою
            else:
                print("⏹ Вичерпані всі спроби генерації новини.")

    return "⚠️ Gemini не повернув текст."
