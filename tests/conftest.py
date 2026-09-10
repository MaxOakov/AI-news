"""Shared fixtures for the whole suite.

Everything here is built from fakes (tests/fakes/) so no test ever touches
a real MongoDB, Gemini, or Telegram connection.
"""
import asyncio as _real_asyncio
import time as _real_time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.bot_commands import BotCommands
from app.db.article_repository import ArticleRepository
from app.db.chat_repository import ChatRepository
from app.db.database import Database
from app.db.prompt_repository import PromptRepository
from app.db.rss_link_repository import RssLinkRepository
from app.models import Article, Chat
from app.news_pipeline import NewsPipeline
from app.scheduler import SchedulerService
from app.services.news_generator import NewsGenerator
from app.services.rss_service import RssFeedService
from app.telegram_bot import TelegramBot

from tests.fakes.genai import FakeGenAIClient
from tests.fakes.mongo import FakeCollection
from tests.fakes.telegram import FakeTGBot, make_context, make_update

# Re-export the update/context factories as plain names tests can import
# directly (`from tests.fakes.telegram import make_update, make_context`)
# as well as via fixtures below, for cases that need several differently
# shaped updates in one test.
__all__ = ["make_update", "make_context"]


# --------------------------------------------------------------------------
# Retry-sleep suppression: no test should ever actually block on a retry's
# backoff delay. Autouse so no test author has to remember to request it.
#
# IMPORTANT: `app.retry.time` and `app.retry.asyncio` are the *same shared
# module objects* as the real `time`/`asyncio` modules everywhere else in
# the process (an `import time` binds the name to that one singleton, it
# doesn't copy it). So `monkeypatch.setattr("app.retry.time.sleep", ...)`
# would mutate `time.sleep` for the *entire test session*, not just inside
# app.retry, silently breaking every other test's real sleeps (including
# tests that deliberately use time.sleep/asyncio.sleep to prove concurrency
# works). Instead, replace the *name* `time`/`asyncio` inside each module's
# own namespace with a thin proxy whose `sleep` is instant but everything
# else (create_task, CancelledError, Semaphore, gather, ...) still
# delegates to the real module.
# --------------------------------------------------------------------------
class _FakeTimeModule:
    def __getattr__(self, name):
        return getattr(_real_time, name)

    @staticmethod
    def sleep(seconds):
        return None


class _FakeAsyncioModule:
    def __getattr__(self, name):
        return getattr(_real_asyncio, name)

    @staticmethod
    async def sleep(seconds):
        return None


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("app.retry.time", _FakeTimeModule())
    monkeypatch.setattr("app.retry.asyncio", _FakeAsyncioModule())
    monkeypatch.setattr("app.scheduler.asyncio", _FakeAsyncioModule())


# --------------------------------------------------------------------------
# Mongo layer
# --------------------------------------------------------------------------
@pytest.fixture
def fake_db_handle():
    return SimpleNamespace(
        articles=FakeCollection(),
        chats=FakeCollection(),
        rss_links=FakeCollection(),
        chat_prompts=FakeCollection(),
    )


@pytest.fixture
def database(fake_db_handle):
    db = Database(url=None)
    db._db = fake_db_handle  # short-circuits the lazy MongoClient connect
    return db


@pytest.fixture
def article_repository(database):
    return ArticleRepository(database)


@pytest.fixture
def chat_repository(database):
    return ChatRepository(database)


@pytest.fixture
def rss_link_repository(database):
    return RssLinkRepository(database)


@pytest.fixture
def prompt_repository(database):
    return PromptRepository(database)


# --------------------------------------------------------------------------
# Gemini layer
# --------------------------------------------------------------------------
@pytest.fixture
def fake_genai_client():
    return FakeGenAIClient()


@pytest.fixture
def news_generator(prompt_repository, fake_genai_client):
    return NewsGenerator("fake-model", prompt_repository, client=fake_genai_client)


# --------------------------------------------------------------------------
# Telegram layer
# --------------------------------------------------------------------------
@pytest.fixture
def fake_tg_bot():
    return FakeTGBot()


@pytest.fixture
def telegram_bot(chat_repository, fake_tg_bot):
    bot = TelegramBot(token="", chat_repository=chat_repository)
    bot.bot = fake_tg_bot  # constructor sets self.bot=None for a falsy token
    return bot


# --------------------------------------------------------------------------
# Sample domain data
# --------------------------------------------------------------------------
@pytest.fixture
def sample_article():
    return Article(
        title="Test title",
        url="https://example.com/a",
        summary="A summary",
        published=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_chat():
    return Chat(chat_id="123", chat_name="Test chat", chat_type="group", message_thread_id=None)


@pytest.fixture
def sample_chat_with_topic():
    return Chat(chat_id="123", chat_name="Test chat", chat_type="group", message_thread_id=42)


# --------------------------------------------------------------------------
# Composed / integration fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def rss_feed_service(article_repository, rss_link_repository):
    return RssFeedService(article_repository, rss_link_repository)


@pytest.fixture
def news_pipeline(rss_feed_service, news_generator, article_repository, telegram_bot):
    return NewsPipeline(rss_feed_service, news_generator, article_repository, telegram_bot)


@pytest.fixture
def scheduler_service(news_pipeline):
    return SchedulerService(news_pipeline, active_hours=range(8, 23))


@pytest.fixture
def bot_commands(telegram_bot, scheduler_service, rss_link_repository, prompt_repository):
    return BotCommands(telegram_bot, scheduler_service, rss_link_repository, prompt_repository)
