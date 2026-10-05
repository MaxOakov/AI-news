from freezegun import freeze_time

from app.db.article_repository import MAX_SEND_ATTEMPTS
from app.models import Article


def test_create_inserts_and_sets_id(article_repository, sample_article):
    article_repository.create([sample_article])
    assert sample_article.id is not None
    stored = article_repository._db.articles.docs
    assert len(stored) == 1
    assert stored[0]["title"] == sample_article.title


def test_create_sets_chat_id_when_given(article_repository, sample_article):
    article_repository.create([sample_article], chat_id=999)
    assert sample_article.chat_id == "999"


def test_create_retries_then_succeeds(article_repository, sample_article, monkeypatch):
    calls = {"n": 0}
    real_insert_one = article_repository._db.articles.insert_one

    def flaky_insert_one(doc):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return real_insert_one(doc)

    monkeypatch.setattr(article_repository._db.articles, "insert_one", flaky_insert_one)
    article_repository.create([sample_article])
    assert calls["n"] == 2
    assert sample_article.id is not None


def test_create_swallows_exhausted_retries(article_repository, sample_article, monkeypatch):
    def always_fails(doc):
        raise RuntimeError("down")

    monkeypatch.setattr(article_repository._db.articles, "insert_one", always_fails)
    article_repository.create([sample_article])  # must not raise
    assert sample_article.id is None
    assert article_repository._db.articles.docs == []


def test_get_next_unsent_returns_none_when_empty(article_repository):
    assert article_repository.get_next_unsent() is None


def test_get_next_unsent_returns_article_when_found(article_repository, sample_article):
    article_repository.create([sample_article])
    result = article_repository.get_next_unsent()
    assert isinstance(result, Article)
    assert result.title == sample_article.title


def test_get_next_unsent_returns_newest_first(article_repository):
    from datetime import datetime, timezone

    old = Article(title="Old", url="https://a", published=datetime(2020, 1, 1, tzinfo=timezone.utc))
    newer = Article(title="Newer", url="https://b", published=datetime(2025, 1, 1, tzinfo=timezone.utc))
    newest = Article(title="Newest", url="https://c", published=datetime(2030, 1, 1, tzinfo=timezone.utc))
    # Insert out of chronological order to prove the query does the sorting.
    article_repository.create([newer, old, newest])

    first = article_repository.get_next_unsent()
    assert first.title == "Newest"

    article_repository.mark_as_sent(first.id)
    second = article_repository.get_next_unsent()
    assert second.title == "Newer"

    article_repository.mark_as_sent(second.id)
    third = article_repository.get_next_unsent()
    assert third.title == "Old"


def test_get_next_unsent_scopes_by_chat_id(article_repository, sample_article):
    article_repository.create([sample_article], chat_id="chat-a")
    assert article_repository.get_next_unsent(chat_id="chat-b") is None
    assert article_repository.get_next_unsent(chat_id="chat-a") is not None


def test_get_next_unsent_ignores_already_sent(article_repository, sample_article):
    article_repository.create([sample_article])
    article_repository.mark_as_sent(sample_article.id)
    assert article_repository.get_next_unsent() is None


def test_get_next_unsent_retries_exhausted_returns_none(article_repository, monkeypatch):
    def always_fails(query, sort=None):
        raise RuntimeError("down")

    monkeypatch.setattr(article_repository._db.articles, "find_one", always_fails)
    assert article_repository.get_next_unsent() is None


def test_exists_true_and_false(article_repository, sample_article):
    assert article_repository.exists(sample_article.title) is False
    article_repository.create([sample_article])
    assert article_repository.exists(sample_article.title) is True


def test_exists_retries_exhausted_returns_false(article_repository, monkeypatch):
    def always_fails(query, limit=None):
        raise RuntimeError("down")

    monkeypatch.setattr(article_repository._db.articles, "count_documents", always_fails)
    assert article_repository.exists("anything") is False


def test_exists_by_guid_true_and_false(article_repository, sample_article):
    sample_article.guid = "guid-1"
    assert article_repository.exists_by_guid("guid-1") is False
    article_repository.create([sample_article])
    assert article_repository.exists_by_guid("guid-1") is True


def test_exists_by_guid_scopes_by_chat_id(article_repository, sample_article):
    sample_article.guid = "guid-1"
    article_repository.create([sample_article], chat_id="chat-a")
    assert article_repository.exists_by_guid("guid-1", chat_id="chat-b") is False
    assert article_repository.exists_by_guid("guid-1", chat_id="chat-a") is True


def test_exists_by_guid_different_titles_same_guid_is_a_duplicate(article_repository, sample_article):
    sample_article.guid = "guid-1"
    article_repository.create([sample_article])
    assert article_repository.exists_by_guid("guid-1") is True


def test_exists_by_guid_retries_exhausted_returns_false(article_repository, monkeypatch):
    def always_fails(query, limit=None):
        raise RuntimeError("down")

    monkeypatch.setattr(article_repository._db.articles, "count_documents", always_fails)
    assert article_repository.exists_by_guid("anything") is False


def test_mark_as_sent_sets_flag(article_repository, sample_article):
    article_repository.create([sample_article])
    article_repository.mark_as_sent(sample_article.id)
    doc = article_repository._db.articles.docs[0]
    assert doc["is_sent"] is True


def test_mark_as_sent_missing_id_does_not_raise(article_repository):
    article_repository.mark_as_sent("does-not-exist")  # just must not raise


# --------------------------------------------------------------------------
# record_failure: an article that keeps failing is eventually skipped so it
# can't block its chat's queue forever.
# --------------------------------------------------------------------------
def test_record_failure_increments_count_without_skipping(article_repository, sample_article):
    article_repository.create([sample_article])

    skipped = article_repository.record_failure(sample_article)

    assert skipped is False
    assert article_repository._db.articles.docs[0]["fail_count"] == 1
    assert article_repository.get_next_unsent().id == sample_article.id


def test_record_failure_skips_after_max_attempts(article_repository, sample_article):
    article_repository.create([sample_article])

    results = [article_repository.record_failure(sample_article) for _ in range(MAX_SEND_ATTEMPTS)]

    assert results == [False] * (MAX_SEND_ATTEMPTS - 1) + [True]
    assert article_repository._db.articles.docs[0]["skipped"] is True
    assert article_repository.get_next_unsent() is None


def test_record_failure_count_survives_reload(article_repository, sample_article):
    # The pipeline gets a fresh Article from get_next_unsent on every run,
    # so the count has to come back from the database, not live only in memory.
    article_repository.create([sample_article])
    for _ in range(MAX_SEND_ATTEMPTS):
        article = article_repository.get_next_unsent()
        assert article is not None
        article_repository.record_failure(article)

    assert article_repository.get_next_unsent() is None


def test_skipped_article_lets_next_one_through(article_repository):
    from datetime import datetime, timezone

    old = Article(title="Old", url="https://a", published=datetime(2020, 1, 1, tzinfo=timezone.utc))
    new = Article(title="New", url="https://b", published=datetime(2025, 1, 1, tzinfo=timezone.utc))
    article_repository.create([old, new])

    for _ in range(MAX_SEND_ATTEMPTS):
        article_repository.record_failure(new)

    assert article_repository.get_next_unsent().title == "Old"


def test_get_next_unsent_without_age_limit_returns_old_articles(article_repository):
    from datetime import datetime, timezone

    article_repository.create(
        [Article(title="Ancient", url="https://a", published=datetime(2000, 1, 1, tzinfo=timezone.utc))]
    )
    assert article_repository.get_next_unsent().title == "Ancient"


# --------------------------------------------------------------------------
# max_article_age: stale articles are never posted, so a growing backlog
# can't push the channel further and further behind the news.
# --------------------------------------------------------------------------
@freeze_time("2026-10-05 12:00:00")
def test_get_next_unsent_skips_articles_older_than_max_age(database):
    from datetime import datetime, timedelta, timezone
    from app.db.article_repository import ArticleRepository

    repo = ArticleRepository(database, max_article_age=timedelta(hours=12))
    repo.create([
        Article(title="Stale", url="https://a", published=datetime(2026, 10, 4, 23, 59, tzinfo=timezone.utc)),
        Article(title="At-cutoff", url="https://b", published=datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)),
        Article(title="Fresh", url="https://c", published=datetime(2026, 10, 5, 11, 0, tzinfo=timezone.utc)),
    ])

    sent = []
    while (article := repo.get_next_unsent()) is not None:
        sent.append(article.title)
        repo.mark_as_sent(article.id)

    # Newest first; the window's edge is inclusive; "Stale" never comes up.
    assert sent == ["Fresh", "At-cutoff"]


@freeze_time("2026-10-05 12:00:00")
def test_get_next_unsent_returns_none_when_everything_is_stale(database):
    from datetime import datetime, timedelta, timezone
    from app.db.article_repository import ArticleRepository

    repo = ArticleRepository(database, max_article_age=timedelta(hours=12))
    repo.create([Article(title="Stale", url="https://a", published=datetime(2026, 10, 1, tzinfo=timezone.utc))])

    assert repo.get_next_unsent() is None


@freeze_time("2026-10-05 12:00:00")
def test_get_next_unsent_age_limit_skips_articles_without_published(database):
    from datetime import timedelta
    from app.db.article_repository import ArticleRepository

    repo = ArticleRepository(database, max_article_age=timedelta(hours=12))
    repo.create([Article(title="Undated", url="https://a", published=None)])

    assert repo.get_next_unsent() is None


def test_ensure_indexes_creates_query_indexes(article_repository):
    article_repository.ensure_indexes()
    article_repository.ensure_indexes()  # idempotent

    assert article_repository._db.articles.indexes == [
        [("chat_id", 1), ("guid", 1)],
        [("chat_id", 1), ("published", 1)],
    ]


def test_record_failure_swallows_db_errors(article_repository, sample_article, monkeypatch):
    def always_fails(filter, update, upsert=False):
        raise RuntimeError("down")

    monkeypatch.setattr(article_repository._db.articles, "update_one", always_fails)
    assert article_repository.record_failure(sample_article) is False  # must not raise


# --------------------------------------------------------------------------
# Moderation support
# --------------------------------------------------------------------------
def test_get_by_id_with_fake_string_id(article_repository, sample_article):
    article_repository.create([sample_article])
    assert article_repository.get_by_id(str(sample_article.id)).title == sample_article.title


def test_get_by_id_converts_object_id_strings(article_repository):
    # Real Mongo ids are ObjectIds; callback_data carries their str() form.
    from bson import ObjectId

    oid = ObjectId()
    article_repository._db.articles.docs.append({"_id": oid, "title": "Real", "url": "https://a"})

    found = article_repository.get_by_id(str(oid))

    assert found.title == "Real"
    assert found.id == oid


def test_get_by_id_missing(article_repository):
    assert article_repository.get_by_id("nope") is None


def test_mark_pending_review_takes_article_out_of_queue(article_repository, sample_article):
    article_repository.create([sample_article])

    article_repository.mark_pending_review(sample_article.id, "7", "Draft")

    stored = article_repository.get_by_id(sample_article.id)
    assert (stored.review_chat_id, stored.draft_text, stored.is_sent) == ("7", "Draft", False)
    assert article_repository.get_next_unsent() is None


def test_mark_skipped(article_repository, sample_article):
    article_repository.create([sample_article])

    article_repository.mark_skipped(sample_article.id)

    assert article_repository.get_by_id(sample_article.id).skipped is True
    assert article_repository.get_next_unsent() is None
