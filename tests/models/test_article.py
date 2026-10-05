from datetime import datetime, timezone

from app.models import Article


def test_to_dict_without_chat_id_or_id():
    article = Article(title="T", url="https://x", summary="s")
    data = article.to_dict()
    assert "chat_id" not in data
    assert "_id" not in data
    assert data == {
        "title": "T",
        "url": "https://x",
        "summary": "s",
        "published": None,
        "is_sent": False,
    }


def test_to_dict_with_chat_id_and_id():
    article = Article(title="T", url="https://x", chat_id="42", id="abc123")
    data = article.to_dict()
    assert data["chat_id"] == "42"
    assert data["_id"] == "abc123"


def test_to_dict_without_guid_omits_key():
    article = Article(title="T", url="https://x")
    assert "guid" not in article.to_dict()


def test_to_dict_with_guid():
    article = Article(title="T", url="https://x", guid="feed-guid-1")
    assert article.to_dict()["guid"] == "feed-guid-1"


def test_from_dict_round_trip_full_doc():
    published = datetime(2026, 1, 1, tzinfo=timezone.utc)
    doc = {
        "title": "T",
        "url": "https://x",
        "summary": "s",
        "published": published,
        "is_sent": True,
        "chat_id": "42",
        "_id": "abc123",
    }
    article = Article.from_dict(doc)
    assert article.title == "T"
    assert article.url == "https://x"
    assert article.summary == "s"
    assert article.published == published
    assert article.is_sent is True
    assert article.chat_id == "42"
    assert article.id == "abc123"


def test_from_dict_missing_keys_default_safely():
    article = Article.from_dict({})
    assert article.title == ""
    assert article.url == ""
    assert article.summary == ""
    assert article.published is None
    assert article.is_sent is False
    assert article.chat_id is None
    assert article.guid is None
    assert article.id is None


def test_from_dict_reads_guid():
    article = Article.from_dict({"title": "T", "url": "https://x", "guid": "feed-guid-1"})
    assert article.guid == "feed-guid-1"


def test_from_dict_null_summary_defaults_to_empty_string():
    article = Article.from_dict({"title": "T", "url": "https://x", "summary": None})
    assert article.summary == ""


def test_to_dict_omits_zero_fail_count():
    assert "fail_count" not in Article(title="T", url="https://x").to_dict()


def test_fail_count_round_trip():
    article = Article(title="T", url="https://x", fail_count=2)
    assert article.to_dict()["fail_count"] == 2
    assert Article.from_dict(article.to_dict()).fail_count == 2


def test_from_dict_missing_fail_count_defaults_to_zero():
    assert Article.from_dict({"title": "T", "url": "https://x"}).fail_count == 0


def test_new_fields_round_trip():
    article = Article(
        title="T", url="https://x", image_url="https://img", skipped=True,
        review_chat_id="7", draft_text="Draft",
    )
    data = article.to_dict()
    assert data["image_url"] == "https://img"
    assert data["skipped"] is True
    assert data["review_chat_id"] == "7"
    assert data["draft_text"] == "Draft"

    back = Article.from_dict(data)
    assert (back.image_url, back.skipped, back.review_chat_id, back.draft_text) == (
        "https://img", True, "7", "Draft"
    )


def test_unset_new_fields_are_omitted():
    data = Article(title="T", url="https://x").to_dict()
    for key in ("image_url", "skipped", "review_chat_id", "draft_text"):
        assert key not in data


def test_preview_url_prefers_image_then_article_page():
    assert Article(title="T", url="https://x", image_url="https://img").preview_url == "https://img"
    assert Article(title="T", url="https://x").preview_url == "https://x"
    assert Article(title="T", url="").preview_url is None
