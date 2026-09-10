from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Article:
    """A single news article, as it flows between the RSS layer, MongoDB,
    the Gemini rewrite step and Telegram delivery.

    Replaces the raw dicts that used to travel through rss_parser.py ->
    mongo.py -> news_generator.py -> job.py, each of which had to agree on
    the same set of keys (`title`, `summary`, `url`, `_id`, ...) by
    convention only.
    """

    title: str
    url: str
    summary: str = ""
    published: datetime | None = None
    is_sent: bool = False
    chat_id: str | None = None
    id: Any = None  # Mongo's `_id`; unset until the article is inserted.

    def to_dict(self) -> dict:
        """Shape this article the way MongoDB expects it."""
        data = {
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "published": self.published,
            "is_sent": self.is_sent,
        }
        if self.chat_id is not None:
            data["chat_id"] = self.chat_id
        if self.id is not None:
            data["_id"] = self.id
        return data

    @classmethod
    def from_dict(cls, doc: dict) -> "Article":
        """Build an Article from a MongoDB document."""
        return cls(
            title=doc.get("title", ""),
            url=doc.get("url", ""),
            summary=doc.get("summary", "") or "",
            published=doc.get("published"),
            is_sent=bool(doc.get("is_sent", False)),
            chat_id=doc.get("chat_id"),
            id=doc.get("_id"),
        )
