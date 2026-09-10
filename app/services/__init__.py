from app.config import GEMINI_MODEL
from app.db import article_repository, rss_link_repository, prompt_repository
from app.services.rss_service import RssFeedService
from app.services.news_generator import NewsGenerator

# Shared service instances, wired to the shared repositories from app.db.
# A later phase moves this construction into main.py's composition root.
rss_feed_service = RssFeedService(article_repository, rss_link_repository)
news_generator = NewsGenerator(GEMINI_MODEL, prompt_repository)

__all__ = [
    "RssFeedService",
    "NewsGenerator",
    "rss_feed_service",
    "news_generator",
]
