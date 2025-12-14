import os
from dotenv import load_dotenv


# Завантажуємо змінні з .env
load_dotenv()

# ----------------- Налаштування -----------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MONGODB_URL = os.getenv("MONGODB_URL")
