import asyncio
import threading
import time
from types import SimpleNamespace

import app.services.rss_service as rss_service_module
from app.news_pipeline import NewsPipeline


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


# --------------------------------------------------------------------------
# Async rework regression tests: blocking sync calls run off the event loop
# (via asyncio.to_thread), and independent chats process concurrently.
# --------------------------------------------------------------------------
async def test_event_loop_is_not_blocked_during_a_slow_sync_call(news_pipeline, rss_feed_service, monkeypatch):
    """A slow *synchronous* repository/service call (standing in for real
    blocking I/O like pymongo or feedparser) must run via asyncio.to_thread
    rather than directly on the event loop, so other coroutines keep making
    progress while it's in flight. If this call blocked the loop directly,
    the ticker below couldn't tick at all during the 0.2s sleep.
    """
    def slow_get_feeds(chat_id):
        time.sleep(0.2)
        return []

    monkeypatch.setattr(rss_feed_service, "get_feeds_for_chat", slow_get_feeds)

    progress = {"ticks": 0}

    async def ticker():
        while True:
            progress["ticks"] += 1
            await asyncio.sleep(0.02)

    ticker_task = asyncio.create_task(ticker())
    try:
        # chat=None is safe here: get_feeds_for_chat returning [] means
        # _process_chat returns before it ever touches chat.message_thread_id.
        await news_pipeline._process_chat("1", None)
    finally:
        ticker_task.cancel()

    assert progress["ticks"] >= 3


async def test_chats_are_processed_concurrently_not_sequentially(
    news_pipeline, telegram_bot, rss_link_repository, monkeypatch
):
    """run(chat_id=None) must process multiple chats concurrently (bounded
    by the semaphore), not strictly one after another, so a slow feed in
    one chat doesn't serialize the whole hourly run."""
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "1", "https://feed-a")
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "2", "https://feed-b")
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "3", "https://feed-c")

    concurrency = {"current": 0, "peak": 0}
    lock = threading.Lock()  # slow_parse runs in different to_thread worker threads

    def slow_parse(url):
        with lock:
            concurrency["current"] += 1
            concurrency["peak"] = max(concurrency["peak"], concurrency["current"])
        time.sleep(0.1)
        with lock:
            concurrency["current"] -= 1
        return _feed_with_one_entry(f"Article for {url}")

    monkeypatch.setattr(rss_service_module.feedparser, "parse", slow_parse)

    await news_pipeline.run(chat_id=None)

    assert concurrency["peak"] > 1


async def test_max_concurrent_chats_bounds_the_semaphore(
    rss_feed_service, news_generator, article_repository, telegram_bot, rss_link_repository, monkeypatch
):
    """The concurrency cap is configurable and actually enforced."""
    bounded_pipeline = NewsPipeline(
        rss_feed_service, news_generator, article_repository, telegram_bot, max_concurrent_chats=1
    )
    for chat_id, url in [("1", "https://feed-a"), ("2", "https://feed-b")]:
        await _register_chat_with_feed(telegram_bot, rss_link_repository, chat_id, url)

    concurrency = {"current": 0, "peak": 0}
    lock = threading.Lock()

    def slow_parse(url):
        with lock:
            concurrency["current"] += 1
            concurrency["peak"] = max(concurrency["peak"], concurrency["current"])
        time.sleep(0.05)
        with lock:
            concurrency["current"] -= 1
        return _feed_with_one_entry(f"Article for {url}")

    monkeypatch.setattr(rss_service_module.feedparser, "parse", slow_parse)

    await bounded_pipeline.run(chat_id=None)

    assert concurrency["peak"] == 1


async def test_unexpected_exception_in_one_chat_does_not_abort_the_others(
    news_pipeline, rss_feed_service, telegram_bot, rss_link_repository, fake_tg_bot, monkeypatch
):
    # feedparser failures don't reach here at all: _parse_and_store_feed's
    # own @retry decorator already catches and swallows those. To exercise
    # run()'s asyncio.gather(return_exceptions=True) handling, raise from a
    # call site with no retry/try-except of its own instead.
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "1", "https://feed-a")
    await _register_chat_with_feed(telegram_bot, rss_link_repository, "2", "https://feed-b")

    real_get_feeds = rss_feed_service.get_feeds_for_chat

    def flaky_get_feeds(chat_id):
        if chat_id == "1":
            raise RuntimeError("boom - simulated unexpected failure")
        return real_get_feeds(chat_id)

    monkeypatch.setattr(rss_feed_service, "get_feeds_for_chat", flaky_get_feeds)
    monkeypatch.setattr(
        rss_service_module.feedparser, "parse", lambda url: _feed_with_one_entry(f"Article for {url}")
    )

    await news_pipeline.run(chat_id=None)  # must not raise

    sent_chat_ids = {m["chat_id"] for m in fake_tg_bot.sent}
    assert sent_chat_ids == {"2"}
