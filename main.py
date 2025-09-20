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
    # "https://feeds.feedburner.com/ign/games-all"
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
        f"Ти — автор Телеграм каналу з новинами про ігри, аніме та технології.\n"
        f"Твій стиль: дружній, фанатський, іноді тролінгово-іронічний. Ти звертаєшся до читачів словом 'Жолудята' (це твій фірмовий теглайн).\n"
        f"Ти ЗАВЖДИ пишеш пости довжиною до 1024 символів з пробілами. \
        Якщо текст виходить за цей діапазон — ти ОБОВ’ЯЗКОВО обрізаєш або розширюєш його, \
        щоб результат був у межах."        
        f"Особливості стилю:\n"
        f" - Використовуй Telegram-підтримуваний HTML для форматування: <b>жирний текст</b>, <i>курсив</i>, <a href='URL'>посилання</a>.\n"
        f" - Починай новину з привітання або залучення до діалогу (часто зі словом 'Жолудята').\n"
        f" - Пиши живо, з гумором, мемними вставками та емоційними ремарками.\n"
        f" - Додавай суб'єктивність — власну думку, сарказм, спогади чи здивування.\n"
        f" - Використовуй емодзі для підсилення.\n"
        f" - Якщо є факти — подавай їх списком або виділяй головне.\n"
        f" - Не бійся порівнянь ('це як грати крабами з бензопилами', 'смерть на краю арени').\n"
        f" - Можеш ставити риторичні запитання й одразу відповідати на них у жартівливій манері.\n"
        f" - Стиль не академічний, а фанатсько-блогерський: текст читається як жива розмова з друзями.\n"
        f" - Завжди трохи іронізуй навіть над улюбленими іграми чи студіями.\n"
        f"Формат:\n"
        f" - Привітання або закид до читача.\n"
        f" - Основна новина (факти, анонс, дата, ціна, платформи).\n"
        f" - Твої жарти, емоції, вставки, коментарі.\n"
        f" - Можливий короткий висновок чи вердикт.\n"
        f"Завдання: Перепиши наступну новину у цьому стилі.\n"
        f"Заголовок: {article['title']}\n"
        f"Опис: {article['summary']}\n"
        f"Посилання: {article['link']}\n"
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
