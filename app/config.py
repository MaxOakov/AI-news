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


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


# ----------------- Instagram -----------------
# Бот стежить за гілкою форуму і переносить в Instagram пости з фото,
# що містять INSTAGRAM_TRIGGER_HASHTAG. Функція вимкнена, доки не задані
# токен, id акаунта, джерело та налаштування Cloudflare R2.
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID")
# graph.facebook.com — для акаунта, прив'язаного до сторінки Facebook;
# https://graph.instagram.com/<версія> — для входу через Instagram Login.
INSTAGRAM_API_BASE_URL = os.getenv("INSTAGRAM_API_BASE_URL", "https://graph.facebook.com/v23.0")
# id форум-групи (наприклад -1001234567890) і гілки в ній
INSTAGRAM_SOURCE_CHAT_ID = os.getenv("INSTAGRAM_SOURCE_CHAT_ID")
INSTAGRAM_SOURCE_THREAD_ID = _optional_int("INSTAGRAM_SOURCE_THREAD_ID")
INSTAGRAM_TRIGGER_HASHTAG = os.getenv("INSTAGRAM_TRIGGER_HASHTAG", "#Команда_AniKoe")
INSTAGRAM_EXTRA_HASHTAGS = os.getenv(
    "INSTAGRAM_EXTRA_HASHTAGS", "#аніме #анімеукраїнською #анімеукраїна #українаніме #анімеоналайн"
).split()
# Куди писати про невдалі публікації (необов'язково)
INSTAGRAM_NOTIFY_CHAT_ID = os.getenv("INSTAGRAM_NOTIFY_CHAT_ID")

# Cloudflare R2: Instagram приймає лише публічний URL картинки, тож фото
# спершу завантажується в бакет з публічним доступом (r2.dev або свій домен).
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL")  # напр. https://pub-xxxx.r2.dev
