from types import SimpleNamespace

import app.services.rss_service as rss_service_module


def _fake_feed(entries, bozo=False, bozo_exception=None):
    ns = SimpleNamespace(entries=entries)
    if bozo:
        ns.bozo = True
        ns.bozo_exception = bozo_exception or RuntimeError("simulated parse error")
    return ns


def _fake_entry(
    title="Entry",
    link=None,
    summary="sum",
    published_parsed=(2026, 1, 1, 0, 0, 0, 0, 0, 0),
    entry_id=None,
):
    # Default link derived from the title so two entries with different
    # titles don't accidentally collide on the same guid fallback unless a
    # test deliberately sets matching links/ids.
    kwargs = dict(title=title, link=link or f"https://x/{title}", summary=summary)
    if entry_id is not None:
        kwargs["id"] = entry_id
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


# --------------------------------------------------------------------------
# GUID-based dedup (replaces the old exact-title match)
# --------------------------------------------------------------------------
def test_dedup_uses_entry_id_when_present(rss_feed_service, article_repository, monkeypatch):
    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _fake_feed([_fake_entry(title="Same Title", entry_id="guid-1")]),
    )
    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    stored = article_repository._db.articles.docs
    assert len(stored) == 1
    assert stored[0]["guid"] == "guid-1"


def test_dedup_by_guid_skips_reposted_entry_with_edited_title(
    rss_feed_service, article_repository, monkeypatch
):
    # Same guid, slightly different title (e.g. a publisher fixed a typo) —
    # must still be recognized as the same article and skipped.
    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _fake_feed([_fake_entry(title="Original Title", entry_id="guid-1")]),
    )
    rss_feed_service.fetch_new_articles("1", ["https://feed"])

    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _fake_feed([_fake_entry(title="Original Title (edited)", entry_id="guid-1")]),
    )
    rss_feed_service.fetch_new_articles("1", ["https://feed"])

    assert len(article_repository._db.articles.docs) == 1


def test_dedup_allows_two_different_entries_sharing_a_title(
    rss_feed_service, article_repository, monkeypatch
):
    # Old title-based dedup would have wrongly treated these as duplicates.
    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _fake_feed([_fake_entry(title="Weekly Update", entry_id="guid-a")]),
    )
    rss_feed_service.fetch_new_articles("1", ["https://feed-a"])

    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _fake_feed([_fake_entry(title="Weekly Update", entry_id="guid-b")]),
    )
    rss_feed_service.fetch_new_articles("1", ["https://feed-b"])

    assert len(article_repository._db.articles.docs) == 2


def test_dedup_falls_back_to_link_when_no_entry_id(rss_feed_service, article_repository, monkeypatch):
    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _fake_feed([_fake_entry(title="No Id", link="https://stable-link")]),
    )
    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    assert len(article_repository._db.articles.docs) == 1
    assert article_repository._db.articles.docs[0]["guid"] == "https://stable-link"


def test_entry_guid_returns_none_when_entry_has_neither_id_nor_link():
    # A real RSS entry always has a link, so this is a defensive fallback
    # rather than something feedparser produces in practice: if it were
    # ever hit, entry.link is still required to build article.url, so the
    # entry fails to store and gets retried like any other parse error --
    # tested at the unit level here rather than through the full pipeline.
    entry = SimpleNamespace(title="No Guid At All")
    assert rss_service_module._entry_guid(entry) is None


def test_entry_guid_prefers_id_over_link():
    entry = SimpleNamespace(id="guid-1", link="https://link")
    assert rss_service_module._entry_guid(entry) == "guid-1"


def test_entry_guid_falls_back_to_link_when_no_id():
    entry = SimpleNamespace(link="https://link")
    assert rss_service_module._entry_guid(entry) == "https://link"


# --------------------------------------------------------------------------
# Multiple entries per poll (was: only feed.entries[:1])
# --------------------------------------------------------------------------
def test_multiple_new_entries_in_one_poll_are_all_stored(
    rss_feed_service, article_repository, monkeypatch
):
    # Stay within the configured window regardless of its actual value, so
    # this test asserts "more than one entry gets stored per poll" without
    # assuming a specific window size.
    n = min(5, rss_service_module._MAX_ENTRIES_PER_POLL)
    entries = [_fake_entry(title=f"Entry {i}", entry_id=f"guid-{i}") for i in range(n)]
    monkeypatch.setattr(rss_service_module.feedparser, "parse", lambda url: _fake_feed(entries))
    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    assert len(article_repository._db.articles.docs) == n


def test_entries_beyond_the_window_are_not_fetched(rss_feed_service, article_repository, monkeypatch):
    entries = [_fake_entry(title=f"Entry {i}", entry_id=f"guid-{i}") for i in range(15)]
    monkeypatch.setattr(rss_service_module.feedparser, "parse", lambda url: _fake_feed(entries))
    rss_feed_service.fetch_new_articles("1", ["https://feed"])
    assert len(article_repository._db.articles.docs) == rss_service_module._MAX_ENTRIES_PER_POLL


def test_mixed_new_and_already_seen_entries_only_stores_new_ones(
    rss_feed_service, article_repository, monkeypatch
):
    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _fake_feed([_fake_entry(title="Seen", entry_id="guid-seen")]),
    )
    rss_feed_service.fetch_new_articles("1", ["https://feed"])

    entries = [
        _fake_entry(title="Seen", entry_id="guid-seen"),
        _fake_entry(title="Fresh", entry_id="guid-fresh"),
    ]
    monkeypatch.setattr(rss_service_module.feedparser, "parse", lambda url: _fake_feed(entries))
    rss_feed_service.fetch_new_articles("1", ["https://feed"])

    assert len(article_repository._db.articles.docs) == 2
    assert article_repository.exists("Fresh", "1") is True


# --------------------------------------------------------------------------
# Real fetch/parse failures (feedparser's bozo flag) are surfaced and retried
# --------------------------------------------------------------------------
def test_bozo_with_no_entries_is_treated_as_a_failure(
    rss_feed_service, article_repository, monkeypatch
):
    calls = {"n": 0}

    def parse(url):
        calls["n"] += 1
        return _fake_feed([], bozo=True, bozo_exception=RuntimeError("connection refused"))

    monkeypatch.setattr(rss_service_module.feedparser, "parse", parse)
    rss_feed_service.fetch_new_articles("1", ["https://broken-feed"])
    # retried 3 times like any other transient failure, then gives up
    assert calls["n"] == 3
    assert article_repository._db.articles.docs == []


def test_bozo_with_usable_entries_is_not_treated_as_a_failure(
    rss_feed_service, article_repository, monkeypatch
):
    # Many real feeds set bozo=1 for minor spec violations while feedparser
    # still recovers usable entries -- those must not be discarded.
    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _fake_feed([_fake_entry(title="Still Works", entry_id="g1")], bozo=True),
    )
    rss_feed_service.fetch_new_articles("1", ["https://quirky-feed"])
    assert article_repository.exists("Still Works", "1") is True
