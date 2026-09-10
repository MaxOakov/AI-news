from types import SimpleNamespace

import app.services.rss_service as rss_service_module


def _fake_feed(entries):
    return SimpleNamespace(entries=entries)


def _fake_entry(title="Entry", link="https://x/link", summary="sum", published_parsed=(2026, 1, 1, 0, 0, 0, 0, 0, 0)):
    kwargs = dict(title=title, link=link, summary=summary)
    if published_parsed is not None:
        kwargs["published_parsed"] = published_parsed
    return SimpleNamespace(**kwargs)


def test_get_feeds_for_chat_filters_blank_urls(rss_feed_service, rss_link_repository):
    rss_link_repository.save("1", "https://a")
    rss_link_repository._db.rss_links.docs.append(
        {"chat_id": "1", "url": "   ", "is_active": True}
    )
    feeds = rss_feed_service.get_feeds_for_chat("1")
    assert feeds == ["https://a"]


def test_fetch_new_articles_empty_list_is_noop(rss_feed_service, monkeypatch):
    calls = []
    monkeypatch.setattr(rss_service_module.feedparser, "parse", lambda url: calls.append(url))
    assert rss_feed_service.fetch_new_articles("1", []) == []
    assert calls == []


def test_fetch_new_articles_stores_new_entry(rss_feed_service, article_repository, monkeypatch):
    monkeypatch.setattr(
        rss_service_module.feedparser, "parse", lambda url: _fake_feed([_fake_entry(title="New")])
    )
    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    assert article_repository.exists("New", "1") is True


def test_fetch_new_articles_skips_already_existing(rss_feed_service, article_repository, monkeypatch):
    monkeypatch.setattr(
        rss_service_module.feedparser, "parse", lambda url: _fake_feed([_fake_entry(title="Dup")])
    )
    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    first_count = len(article_repository._db.articles.docs)

    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    assert len(article_repository._db.articles.docs) == first_count  # not stored twice


def test_fetch_new_articles_entry_missing_published_parsed_is_skipped(
    rss_feed_service, article_repository, monkeypatch
):
    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _fake_feed([_fake_entry(title="NoDate", published_parsed=None)]),
    )
    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    assert article_repository._db.articles.docs == []


def test_fetch_new_articles_zero_entries_is_noop(rss_feed_service, article_repository, monkeypatch):
    monkeypatch.setattr(rss_service_module.feedparser, "parse", lambda url: _fake_feed([]))
    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    assert article_repository._db.articles.docs == []


def test_fetch_new_articles_retries_then_succeeds(rss_feed_service, article_repository, monkeypatch):
    attempts = {"n": 0}

    def flaky_parse(url):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("network blip")
        return _fake_feed([_fake_entry(title="Recovered")])

    monkeypatch.setattr(rss_service_module.feedparser, "parse", flaky_parse)
    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    assert attempts["n"] == 2
    assert article_repository.exists("Recovered", "1") is True


def test_fetch_new_articles_exhausted_continues_to_next_url(
    rss_feed_service, article_repository, monkeypatch
):
    calls = []

    def parse(url):
        calls.append(url)
        if url == "https://always-down":
            raise RuntimeError("down")
        return _fake_feed([_fake_entry(title=f"From {url}")])

    monkeypatch.setattr(rss_service_module.feedparser, "parse", parse)
    result = rss_feed_service.fetch_new_articles(
        "1", ["https://always-down", "https://good-feed"]
    )
    assert result == []
    # 3 retries against the always-failing url, then it moves on to the good one
    assert calls.count("https://always-down") == 3
    assert calls.count("https://good-feed") == 1
    assert article_repository.exists("From https://good-feed", "1") is True
