import os
from pathlib import Path
from dotenv import load_dotenv


# Завантажуємо змінні з .env
load_dotenv()

# ----------------- Налаштування -----------------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")  # Модель за замовчуванням
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGODB_URL = os.getenv("MONGODB_URL")

# Невідправлені статті, старші за цю кількість годин, більше не публікуються
# (щоб канал не відставав від новин, коли фіди дають більше статей, ніж бот встигає відправити)
MAX_ARTICLE_AGE_HOURS = int(os.getenv("MAX_ARTICLE_AGE_HOURS", "12"))

# Моделі, доступні для вибору через /gemini_version
GEMINI_MODEL_OPTIONS = [
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite-preview",
]

# .env у корені проєкту (у Docker це змонтований каталог хоста, тож зміни зберігаються)
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


# ----------------- Instagram -----------------
# Instagram і Cloudflare R2 налаштовуються для кожного чату окремо (/setup)
# і зберігаються в MongoDB, а токени й ключі — зашифрованими цим ключем.
# Він живе лише тут, не в базі: без нього вкрадена копія бази нічого не дає.
# Без ключа Instagram недоступний, а решта бота працює як звичайно.
# Згенерувати: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Кілька ключів через кому — для ротації: шифрує перший, розшифровують усі.
# Якщо ключ втратити, токени й ключі доведеться ввести в чатах заново.
SECRETS_ENCRYPTION_KEY = os.getenv("SECRETS_ENCRYPTION_KEY")
INSTAGRAM_GRAPH_API_VERSION = os.getenv("INSTAGRAM_GRAPH_API_VERSION", "v23.0")
