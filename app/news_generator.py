from google import genai
from pathlib import Path

# Ініціалізація клієнта Ggoogle Gemini API та Telegram-бота
client = genai.Client()


def generate_news(article):
    """
    Генерує текст новини через GEMINI API.
    """

    print("Стаття відправлена на переписування...")

    prompt_template = Path("prompt.txt").read_text(encoding="utf-8")


    

    prompt = prompt_template.format(
        title=article["title"],
        summary=article["summary"],
        url=article["url"]
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    retry_count = 0
    max_retries = 3
    while retry_count < max_retries:
        try:
            if response.candidates:
                print(f"Статтю '{article['title']}' переписано")
                return response.candidates[0].content.parts[0].text.strip()
        except Exception as e:
            retry_count += 1
            print(f"⚠️ Помилка при генерації новини (спроба {retry_count}): {e}")

    return "⚠️ Gemini не повернув текст."
