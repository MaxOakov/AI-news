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


def test_get_next_unsent_returns_oldest_first(article_repository):
    from datetime import datetime, timezone

    old = Article(title="Old", url="https://a", published=datetime(2020, 1, 1, tzinfo=timezone.utc))
    newer = Article(title="Newer", url="https://b", published=datetime(2025, 1, 1, tzinfo=timezone.utc))
    newest = Article(title="Newest", url="https://c", published=datetime(2030, 1, 1, tzinfo=timezone.utc))
    # Insert out of chronological order to prove the query does the sorting.
    article_repository.create([newest, old, newer])

    first = article_repository.get_next_unsent()
    assert first.title == "Old"

    article_repository.mark_as_sent(first.id)
    second = article_repository.get_next_unsent()
    assert second.title == "Newer"

    article_repository.mark_as_sent(second.id)
    third = article_repository.get_next_unsent()
    assert third.title == "Newest"


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


def test_get_latest_published_at_empty_returns_none(article_repository):
    assert article_repository.get_latest_published_at() is None


def test_get_latest_published_at_returns_max_published(article_repository, sample_article):
    from dataclasses import replace
    from datetime import datetime, timezone

    older = replace(sample_article, published=datetime(2020, 1, 1, tzinfo=timezone.utc))
    newer = replace(sample_article, published=datetime(2030, 1, 1, tzinfo=timezone.utc))
    article_repository.create([older, newer])
    assert article_repository.get_latest_published_at() == newer.published
