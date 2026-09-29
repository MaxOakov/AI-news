import os
from pathlib import Path
from dotenv import load_dotenv


# Завантажуємо змінні з .env
load_dotenv()

# ----------------- Налаштування -----------------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")  # Модель за замовчуванням
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGODB_URL = os.getenv("MONGODB_URL")

# Моделі, доступні для вибору через /gemini_version
GEMINI_MODEL_OPTIONS = [
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite-preview",
]

# .env у корені проєкту (у Docker це змонтований каталог хоста, тож зміни зберігаються)
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
