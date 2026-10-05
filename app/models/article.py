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
    guid: str | None = None  # feed entry's stable id (or link, as a fallback)
    image_url: str | None = None  # the feed entry's image, if it has one
    fail_count: int = 0  # failed generate/send attempts; see ArticleRepository.record_failure
    skipped: bool = False  # never to be posted (too many failures, or a reviewer skipped it)
    # Set once a draft has been sent to a reviewer (moderation mode); see
    # ArticleRepository.mark_pending_review.
    review_chat_id: str | None = None
    draft_text: str | None = None
    id: Any = None  # Mongo's `_id`; unset until the article is inserted.

    @property
    def preview_url(self) -> str | None:
        """What the Telegram link preview above the post should show: the
        entry's own image if it has one, else the article page (whose
        og:image Telegram picks up)."""
        return self.image_url or self.url or None

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
        if self.guid is not None:
            data["guid"] = self.guid
        if self.image_url is not None:
            data["image_url"] = self.image_url
        if self.fail_count:
            data["fail_count"] = self.fail_count
        if self.skipped:
            data["skipped"] = True
        if self.review_chat_id is not None:
            data["review_chat_id"] = self.review_chat_id
        if self.draft_text is not None:
            data["draft_text"] = self.draft_text
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
            guid=doc.get("guid"),
            image_url=doc.get("image_url"),
            fail_count=int(doc.get("fail_count") or 0),
            skipped=bool(doc.get("skipped", False)),
            review_chat_id=doc.get("review_chat_id"),
            draft_text=doc.get("draft_text"),
            id=doc.get("_id"),
        )
