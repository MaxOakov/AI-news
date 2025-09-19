from dotenv import load_dotenv
import os
import time
import feedparser
from google import genai
import asyncio

# Імпорт Bot з python-telegram-bot
from telegram import Bot
import schedule

# Завантажуємо змінні з .env
load_dotenv()

# ----------------- Налаштування -----------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Ініціалізація клієнта Ggoogle Gemini API та Telegram-бота
client = genai.Client()
bot = Bot(token=TELEGRAM_TOKEN)

# RSS-стрічки для парсингу
RSS_FEEDS = [
    "https://feeds.feedburner.com/ign/games-all",
    "https://www.vg247.com/feed/news"
]

# ----------------- Функції -----------------
def fetch_articles():
    """
    Завантажує статті з RSS-фідів (до 5 найновіших з кожної).
    Повертає list[dict]: title, link, summary.
    """
    articles = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:1]:
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "summary": getattr(entry, 'summary', '')
            })
    print("Статті вивантажено...")
    return articles


def generate_news(article):
    """
    Генерує текст новини через GEMINI API.
    """
    prompt = (
        f"Ти — журналіст українського IT-порталу. Напиши стислий пост новини на основі:\n"
        f"Заголовок: {article['title']}\n"
        f"Опис: {article['summary']}\n"
        f"Посилання: {article['link']}\n"
        f"Використовуй дружній та енергійний стиль письма, якщо можливо встав жарт у тексті.\n"
        f"Використовуй Telegram-підтримуваний HTML для форматування: <b>жирний текст</b>, <i>курсив</i>, <a href='URL'>посилання</a>.\n"
        f"Заголовок поста завжди робити жирнрим текстом, щоб привернути більше уваги\n"
    )
    response = client.models.generate_content(
        model = "gemini-2.5-flash",
        contents = prompt
        )
    print("Статті відправлено на переписування...")

    # Повертаємо текст відповіді
    if response.candidates:
        print(f"Статтю {article['title']} переписано")
        return response.candidates[0].content.parts[0].text.strip()
    else:
        return "⚠️ Gemini не повернув текст."


async def send_all(articles):
    for art in articles:
        news_text = generate_news(art)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=news_text, parse_mode="HTML")
        await asyncio.sleep(1)  # замість time.sleep — щоб не блокувати loop


def job():
    """
    Основна задача: зібрати статті, згенерувати новини і відправити.
    """
    articles = fetch_articles()
    asyncio.run(send_all(articles))


# ----------------- Планувальник -----------------
# Щоденний запуск job() о 14:20 (Europe/Kyiv)
# schedule.every().day.at("14:23").do(job)

if __name__ == "__main__":
    print("Запуск автоматизатора новин...")
    job()

    # while True:
    #     schedule.run_pending()
    #     time.sleep(60)
