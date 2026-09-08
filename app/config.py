import os
from dotenv import load_dotenv


# Завантажуємо змінні з .env
load_dotenv()

# ----------------- Налаштування -----------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")  # Модель за замовчуванням
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGODB_URL = os.getenv("MONGODB_URL")
