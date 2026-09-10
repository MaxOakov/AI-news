import app.services.rss_service as rss_service_module
from types import SimpleNamespace


def _feed_with_one_entry(title):
    entry = SimpleNamespace(
        title=title, link="https://x/link", summary="sum",
        published_parsed=(2026, 1, 1, 0, 0, 0, 0, 0, 0),
    )
    return SimpleNamespace(entries=[entry])


async def _register_chat_with_feed(telegram_bot, rss_link_repository, chat_id, url):
    await telegram_bot.register_chat_db(chat_id, f"Chat {chat_id}", "group")
    rss_link_repository.save(chat_id, url)


# --------------------------------------------------------------------------
# /runjob chat-scoping regression: the real bug found during the refactor
# was that a manual /runjob from one chat triggered a full run for every
# registered chat instead of just the requesting one.
# --------------------------------------------------------------------------
async def test_run_with_chat_id_only_affects_that_chat(
    news_pipeline, telegram_bot, rss_link_repository, fake_tg_bot, monkeypatch
):
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "1", "https://feed-a")
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "2", "https://feed-b")

    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _feed_with_one_entry(f"Article for {url}"),
    )

    await news_pipeline.run(chat_id="1")

    assert len(fake_tg_bot.sent) == 1
    assert fake_tg_bot.sent[0]["chat_id"] == "1"


async def test_run_without_chat_id_covers_every_chat(
    news_pipeline, telegram_bot, rss_link_repository, fake_tg_bot, monkeypatch
):
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "1", "https://feed-a")
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "2", "https://feed-b")

    monkeypatch.setattr(
        rss_service_module.feedparser,
        "parse",
        lambda url: _feed_with_one_entry(f"Article for {url}"),
    )

    await news_pipeline.run(chat_id=None)

    sent_chat_ids = {m["chat_id"] for m in fake_tg_bot.sent}
    assert sent_chat_ids == {"1", "2"}


async def test_run_with_unregistered_chat_id_is_a_safe_noop(
    news_pipeline, fake_tg_bot, rss_link_repository, monkeypatch
):
    calls = []
    monkeypatch.setattr(rss_link_repository, "get_for_chat", lambda chat_id: calls.append(chat_id) or [])

    await news_pipeline.run(chat_id="does-not-exist")  # must not raise

    assert fake_tg_bot.sent == []
    assert calls == []  # never even got to looking up feeds


async def test_run_coerces_chat_id_to_str(
    news_pipeline, telegram_bot, rss_link_repository, fake_tg_bot, monkeypatch
):
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "42", "https://feed")
    monkeypatch.setattr(
        rss_service_module.feedparser, "parse", lambda url: _feed_with_one_entry("Article")
    )

    await news_pipeline.run(chat_id=42)  # int, not str

    assert len(fake_tg_bot.sent) == 1
    assert fake_tg_bot.sent[0]["chat_id"] == "42"


# --------------------------------------------------------------------------
# _process_chat behavior (exercised through run())
# --------------------------------------------------------------------------
async def test_no_feeds_for_chat_skips_processing(news_pipeline, telegram_bot, fake_tg_bot):
    await telegram_bot.register_chat_db("1", "Chat")
    await news_pipeline.run(chat_id="1")
    assert fake_tg_bot.sent == []


async def test_no_unsent_article_skips_send(
    news_pipeline, telegram_bot, rss_link_repository, fake_tg_bot, monkeypatch
):
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "1", "https://feed")
    monkeypatch.setattr(
        rss_service_module.feedparser, "parse", lambda url: SimpleNamespace(entries=[])
    )
    await news_pipeline.run(chat_id="1")
    assert fake_tg_bot.sent == []


async def test_successful_send_marks_article_as_sent(
    news_pipeline, telegram_bot, rss_link_repository, article_repository, monkeypatch
):
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "1", "https://feed")
    monkeypatch.setattr(
        rss_service_module.feedparser, "parse", lambda url: _feed_with_one_entry("Article")
    )
    await news_pipeline.run(chat_id="1")
    assert article_repository.get_next_unsent("1") is None  # it's now marked sent


async def test_failed_send_leaves_article_unsent(
    news_pipeline, telegram_bot, rss_link_repository, article_repository, fake_tg_bot, monkeypatch
):
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "1", "https://feed")
    monkeypatch.setattr(
        rss_service_module.feedparser, "parse", lambda url: _feed_with_one_entry("Article")
    )
    fake_tg_bot.fail_times(99)

    await news_pipeline.run(chat_id="1")

    assert article_repository.get_next_unsent("1") is not None  # still unsent


async def test_message_thread_id_forwarded_to_send(
    news_pipeline, telegram_bot, rss_link_repository, fake_tg_bot, monkeypatch
):
    await telegram_bot.register_chat_db("1", "Chat", message_thread_id=77)
    rss_link_repository.save("1", "https://feed")
    monkeypatch.setattr(
        rss_service_module.feedparser, "parse", lambda url: _feed_with_one_entry("Article")
    )

    await news_pipeline.run(chat_id="1")

    assert fake_tg_bot.sent[0]["message_thread_id"] == 77
