# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Telegram bot that polls per-chat RSS feeds, rewrites one article per chat per run with Gemini (`google-genai`), and posts it to the chat. State (chats, feeds, custom prompts, articles) lives in MongoDB (database `news`). User-facing strings and log output are in Ukrainian; keep new messages consistent with that.

## Commands

```bash
pip install -r requirements.txt -r requirements-dev.txt   # runtime + pytest, pytest-asyncio, pytest-cov, freezegun, pip-tools
pytest                                                    # full suite (pytest.ini: testpaths=tests, asyncio_mode=auto, pythonpath=.)
pytest tests/test_news_pipeline.py                        # one file
pytest tests/test_news_pipeline.py::test_name             # one test
pytest --cov=app --cov-report=term-missing                # what CI runs
python main.py                                            # run the bot (needs .env: TELEGRAM_TOKEN, GEMINI_API_KEY, MONGODB_URL, optional GEMINI_MODEL)
docker compose up --build
```

Dependencies: edit `requirements.in` (direct deps only), then regenerate the pinned `requirements.txt` with `pip-compile --strip-extras --no-emit-index-url requirements.in`; never hand-edit `requirements.txt`.

No linter/formatter is configured.

CI ([.github/workflows/tests.yml](.github/workflows/tests.yml)) only runs the test suite on Python 3.14. There is no automated deploy: building and deploying are done manually.

## Architecture

**Dependency injection via a single composition root.** [main.py](main.py) `build_app()` constructs the whole object graph explicitly; every class takes its collaborators through its constructor. There are no module-level singletons (the docstrings reference the old globals this replaced) — don't reintroduce them. New dependencies get wired in `build_app()`, and new commands are registered as `CommandHandler`s in `main()`.

Flow of one run:
`SchedulerService` → `NewsPipeline.run(chat_id=None|id)` → per chat: `RssFeedService.get_feeds_for_chat` → `fetch_new_articles` (stores new entries via `ArticleRepository`) → `ArticleRepository.get_next_unsent` (oldest first) → `NewsGenerator.generate` (resolves prompt via `PromptRepository`) → `TelegramBot.send_message` → `mark_as_sent` only if sending succeeded.

**Sync/async boundary.** Repositories and `RssFeedService` are synchronous (pymongo, feedparser). Async callers must wrap them in `asyncio.to_thread(...)`. Gemini (`client.aio`) and Telegram sending are natively async. `NewsPipeline` processes all chats concurrently with `asyncio.gather`, bounded by a semaphore (`max_concurrent_chats`).

**Scheduler.** Uses the `schedule` library inside an asyncio loop that ticks every 60s; runs once at startup, then hourly, only during `active_hours` (Europe/Kyiv, 8–22). An instance `_running` flag prevents overlapping runs; manual `/runjob`/`/news` go through `trigger_now(chat_id)` and share that guard. Retries on errors whose message contains `"503"`.

**Retries.** [app/retry.py](app/retry.py) provides `retry` / `retry_async` decorators with `on_retry`/`on_failure` callbacks. Note `max_retries` is total attempts, and callbacks receive the wrapped function's args (so lambda signatures must match, e.g. `lambda exc, attempt, total, self, prompt: ...`). If `on_failure` is given, its return value replaces raising.

**TelegramBot** keeps an in-memory `chats: dict[str, Chat]` cache (guarded by an `asyncio.Lock`) loaded from Mongo at startup; the pipeline iterates this cache, not the DB. Chat IDs are always normalized to `str`.

**BotCommands**: state-changing commands (`/settopic`, `/addrss`, `/removerss`, `/setprompt`, `/resetprompt`, `/stop`) are gated by `_require_admin` in groups (creator/administrator, or anonymous-admin posts via `sender_chat`); always allowed in private chats.

**Gemini model switching.** `/gemini_version` shows inline buttons (`callback_data="set_model:<model>"`, handled by a `CallbackQueryHandler`). `GeminiModelSettings` validates against `GEMINI_MODEL_OPTIONS` in [app/config.py](app/config.py), rewrites `GEMINI_MODEL` in `.env` (`ENV_PATH`, project root; it only persists across container restarts if that file is mounted from the host — `docker compose` mounts the project dir, a plain `docker run --env-file` does not) and sets `NewsGenerator.model`. The model is global across chats; the button press is admin-gated.

**Prompts.** Default prompt is `prompt.txt` at the project root (copied into the Docker image), rendered with `str.format(title=, summary=, url=)`. Per-chat custom prompts in `chat_prompts` override it and are validated at save time (`InvalidPromptError`) — any other `{placeholder}` or literal braces break formatting.

**RSS dedup** is by entry GUID (`id` → `link` → title fallback); only `_MAX_ENTRIES_PER_POLL` newest entries per feed are checked each poll. `rss_feed_links.txt` is a reference list only, not read at runtime.

## Testing

Tests never touch real MongoDB, Gemini, or Telegram. [tests/conftest.py](tests/conftest.py) builds the real app classes on top of fakes in [tests/fakes/](tests/fakes/):
- `FakeCollection` — in-memory pymongo stand-in supporting only the query/update operators the repositories actually use (equality, `$or`, `$exists`, `$set`, `$setOnInsert`, upsert, sort). If a repository starts using a new Mongo operator, extend the fake.
- `FakeGenAIClient` / `FakeTGBot` — with `fail_times(n)` etc. to exercise retry paths.
- Injection points: `Database._db` is set directly to skip the lazy connect; `NewsGenerator(..., client=fake)`; `TelegramBot.bot = fake`.

An autouse `no_sleep` fixture replaces the `time`/`asyncio` **names** inside `app.retry` and `app.scheduler` with proxies whose `sleep` is instant. It deliberately does not patch `time.sleep`/`asyncio.sleep` globally (that would break concurrency tests). If you add a new module that sleeps for retries/backoff, add it to that fixture the same way.
