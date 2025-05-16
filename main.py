from dotenv import load_dotenv
import os
import time
import feedparser
from openai import OpenAI
# Альтернативний імпорт Bot з python-telegram-bot
try:
    from telegram import Bot
except ImportError:
    from telegram.bot import Bot
import schedule

# Завантажуємо змінні з .env
load_dotenv()

# ----------------- Налаштування -----------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Ініціалізація клієнта OpenAI (версія >=1.0.0)
client = OpenAI(api_key=OPENAI_API_KEY)
# Ініціалізація Telegram-бота
bot = Bot(token=TELEGRAM_TOKEN)

# RSS-стрічки для парсингу
RSS_FEEDS = [
    "https://feeds.feedburner.com/ign/all"
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
        for entry in feed.entries[:5]:
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "summary": getattr(entry, 'summary', '')
            })
    return articles


def generate_news(article):
    """
    Генерує текст новини через OpenAI API (chat.completions).
    """
    prompt = (
        f"Ти — журналіст українського IT-порталу. Напиши стислий пост новини на основі цих даних:\n"
        f"Заголовок: {article['title']}\n"
        f"Опис: {article['summary']}\n"
        f"Посилання: {article['link']}\n"
    )
    response = client.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[
            {"role": "system", "content": "Ти професійний журналіст."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=300,
        temperature=0.7
    )
    # Повертаємо текст відповіді
    return response.choices[0].message.content.strip()


def send_telegram(message):
    """
    Відправляє текст у вказаний Telegram-чат.
    """
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="HTML")


def job():
    """
    Основна задача: зібрати статті, згенерувати новини і відправити.
    """
    articles = fetch_articles()
    for art in articles:
        news_text = generate_news(art)
        send_telegram(news_text)
        time.sleep(1)  # убезпечуємося від лімітів API


# ----------------- Планувальник -----------------
# Щоденний запуск job() о 14:20 (Europe/Kyiv)
# schedule.every().day.at("14:23").do(job)

if __name__ == "__main__":
    print("Запуск автоматизатора новин...")
    job()

    # while True:
    #     schedule.run_pending()
    #     time.sleep(60)
