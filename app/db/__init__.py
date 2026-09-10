from app.config import MONGODB_URL
from app.db.database import Database
from app.db.article_repository import ArticleRepository
from app.db.chat_repository import ChatRepository
from app.db.rss_link_repository import RssLinkRepository
from app.db.prompt_repository import PromptRepository

# A single shared Database and its repositories, used across the app for
# now so existing call sites can migrate from `app.mongo`'s free functions
# to repository methods without a full dependency-injection rewrite yet.
# A later phase moves this construction into main.py's composition root and
# passes repositories into services via their constructors instead.
database = Database(MONGODB_URL)
article_repository = ArticleRepository(database)
chat_repository = ChatRepository(database)
rss_link_repository = RssLinkRepository(database)
prompt_repository = PromptRepository(database)

__all__ = [
    "Database",
    "ArticleRepository",
    "ChatRepository",
    "RssLinkRepository",
    "PromptRepository",
    "database",
    "article_repository",
    "chat_repository",
    "rss_link_repository",
    "prompt_repository",
]
