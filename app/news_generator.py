from google import genai
import time
from app.mongo import get_prompt_for_chat

# Ініціалізація клієнта Ggoogle Gemini API та Telegram-бота
client = genai.Client()
print("Клієнт Gemini ініціалізовано.")


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
