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
python main.py                                            # run the bot (needs .env: TELEGRAM_TOKEN, GEMINI_API_KEY, MONGODB_URL, optional GEMINI_MODEL, MAX_ARTICLE_AGE_HOURS, SECRETS_ENCRYPTION_KEY for Instagram)
docker compose up --build
```

Dependencies: edit `requirements.in` (direct deps only), then regenerate the pinned `requirements.txt` with `pip-compile --strip-extras --no-emit-index-url requirements.in`; never hand-edit `requirements.txt`.

No linter/formatter is configured.

CI ([.github/workflows/tests.yml](.github/workflows/tests.yml)) only runs the test suite on Python 3.14. There is no automated deploy: building and deploying are done manually.

## Architecture

**Dependency injection via a single composition root.** [main.py](main.py) `build_app()` constructs the whole object graph explicitly; every class takes its collaborators through its constructor. There are no module-level singletons (the docstrings reference the old globals this replaced) — don't reintroduce them. New dependencies get wired in `build_app()`, and new commands are registered as `CommandHandler`s in `main()`.

Flow of one run:
`SchedulerService` → `NewsPipeline.run(chat_id=None|id)` → per chat: `RssFeedService.get_feeds_for_chat` → `fetch_new_articles` (stores new entries via `ArticleRepository`) → `ArticleRepository.get_next_unsent` (newest first, within `max_article_age`, excluding `skipped` and articles already drafted for review) → `NewsGenerator.generate` (resolves prompt via `PromptRepository`; `None` on failure) → `ArticlePublisher.publish` → `TelegramBot.send_message` (with a link preview of `Article.preview_url`; falls back to plain text if Telegram rejects the HTML) → `mark_as_sent` if sending succeeded, else `record_failure` (marks the article `skipped` after `MAX_SEND_ATTEMPTS`). `ArticleRepository.ensure_indexes()` runs once at startup in `main()`.

**Moderation.** If a chat has `reviewer_chat_id` set (`/moderation on`), `ArticlePublisher` sends the draft to that private chat instead, with buttons whose `callback_data` is `review:<pub|regen|skip>:<article id>` (64-byte limit), and `mark_pending_review` stores `review_chat_id` + `draft_text` on the article. `BotCommands.review_callback` → `ArticlePublisher.handle_review` acts on it; only the reviewer the draft was sent to can, and a handled draft's keyboard is replaced by an inert `review:done` button. `Chat.to_dict()` never includes `reviewer_chat_id` (only `ChatRepository.set_reviewer` writes it), and `register_chat_db` carries it over, so `/start` can't turn moderation off.

**Instagram forwarding.** Optional and per chat. Settings live in the `instagram_settings` collection (one doc per chat, never in `chats`) via `InstagramSettingsRepository`, which encrypts the token and both R2 keys with `SecretBox` (Fernet/MultiFernet under `SECRETS_ENCRYPTION_KEY` from `.env`; stored as `<field>_encrypted`; the plaintext carries `chat_id:field` and decrypt checks it, so a ciphertext moved to another chat/field fails). No key → `can_store_secrets` is False, secret saves raise `SecretsUnavailableError`, stored ones read back as `secrets_unreadable`; the rest of the bot is unaffected. `InstagramSettings` keeps secret fields out of `repr`. `InstagramSettingsService` wraps the repository and keeps an in-memory index chat id → `InstagramRoute` (tracked `hashtags`, `topic_id`, `all_topics`) of chats whose settings `is_ready` (`load()` at startup, refreshed on every save; `route_for(chat_id)`) — no secrets in it. A post matches if it has **any** tracked hashtag (`has_any_hashtag`). `InstagramRoute.watches_topic(thread, news_topic)`: `all_topics` → any; else `topic_id`, falling back to the chat's news topic (`Chat.message_thread_id`, read live, so `/settopic` moves it), and no topic at all = whole chat. Legacy docs with a single `trigger_hashtag` string read as a one-item `trigger_hashtags`.

`InstagramForwarder.handle` is a `MessageHandler` (group 1) on all groups/channels; `_watches` drops, from memory only, chats not in the index, chats not in `TelegramBot.chats` (stopped), and topics the route doesn't watch. It then matches the route's hashtags, skips posts with video, takes a text post's picture from its link preview (`link_preview_options.url`, else the first `url`/`text_link` entity, via `PageImageFetcher`: direct image, else `og:image` → `twitter:image` → first `<img>`), collects album items by `media_group_id` for `album_wait` seconds, and does the work in background tasks (`wait_idle()` in tests). Bots never receive their own messages as updates, so the bot's news posts come in through `ArticlePublisher._send_to_chat` → `forward_article(chat_id, message_thread_id, article, html_text)` (only after a successful send, so a moderated draft goes over once approved; it goes through `_watches` too, so with another Instagram topic chosen the bot's news stay out), keyed `article:<id>`, with `Article.preview_url` as the picture. Per post: reload + decrypt settings → `InstagramPostRepository.claim` (one-time; failures are not retried) → download → `prepare_for_instagram` (JPEG, padded to 4:5–1.91:1) → upload to the chat's R2 (`InstagramConnector.image_host(settings)`; the Graph API needs a public URL, Telegram file URLs contain the bot token) → `InstagramConnector.instagram_client(settings).publish_photos` (container → poll `status_code` → `media_publish`) → delete from R2 → private message to `settings.admin_user_id`.

**Setup.** `SetupCommands` ([app/setup_commands.py](app/setup_commands.py)) owns `/setup` and `/ig_account`, `/ig_r2`, `/ig_track` (tracked hashtags), `/ig_tags` (caption hashtags), `/ig_topic` (no args, sent inside a forum topic: that topic — checked with `is_topic_message`, since non-forum reply threads also carry a `message_thread_id`; the name comes from `reply_to_message.forum_topic_created` when present; `all` / `news`: every topic / back to the default), `/ig_reset`; text comes from [app/setup_checklist.py](app/setup_checklist.py). `BotCommands.start` calls `send_first_start_checklist` when `get_known_chat` found no record before registering. A group's checklist has a URL button `t.me/<bot>?start=setup_<chat id>`; that `/start` is routed (a `CommandHandler` with a PRIVATE + regex filter, registered before the plain `/start`) to `start_from_link`, which checks `is_chat_admin` and stores a 1-hour session user → chat; `_target_chat` resolves private commands to it (re-checking admin each time), else to the private chat itself if it gets news. Secret commands are refused outside private chats (`_accept_secret_message` deletes the message there and warns via `bot.send_message`, since a group reply would quote the deleted message); in private the message is deleted right after reading. Credentials are verified before saving (`InstagramConnector.check_account` tries graph.facebook.com / graph.instagram.com, `check_r2` uploads a file and fetches it via the public URL); `/setup` re-checks the stored token live. Never print secrets or `str()` of exceptions on secret paths; httpx/httpcore loggers are set to WARNING in `main.py` because at INFO httpx logs full request URLs (bot token, `access_token` params).

**Sync/async boundary.** Repositories and `RssFeedService` are synchronous (pymongo, feedparser). Async callers must wrap them in `asyncio.to_thread(...)`. Gemini (`client.aio`) and Telegram sending are natively async. `NewsPipeline` processes all chats concurrently with `asyncio.gather`, bounded by a semaphore (`max_concurrent_chats`).

**Scheduler.** Uses the `schedule` library inside an asyncio loop that ticks every 60s; runs once at startup, then hourly, only during `active_hours` (Europe/Kyiv, 8–22). An instance `_running` flag prevents overlapping runs; manual `/runjob`/`/news` go through `trigger_now(chat_id)` and share that guard. Retries on errors whose message contains `"503"`.

**Retries.** [app/retry.py](app/retry.py) provides `retry` / `retry_async` decorators with `on_retry`/`on_failure` callbacks. Note `max_retries` is total attempts, and callbacks receive the wrapped function's args (so lambda signatures must match, e.g. `lambda exc, attempt, total, self, prompt: ...`). If `on_failure` is given, its return value replaces raising.

**TelegramBot** keeps an in-memory `chats: dict[str, Chat]` cache (guarded by an `asyncio.Lock`) loaded from Mongo at startup; the pipeline iterates this cache, not the DB. Chat IDs are always normalized to `str`.

**BotCommands**: state-changing commands (`/settopic`, `/addrss`, `/removerss`, `/setprompt`, `/resetprompt`, `/stop`, `/moderation on|off`, and `SetupCommands`' ones) are gated by `require_admin` ([app/permissions.py](app/permissions.py); `BotCommands._require_admin` delegates to it) in groups (creator/administrator, or anonymous-admin posts via `sender_chat`); always allowed in private chats.

**Gemini model switching.** `/gemini_version` shows inline buttons (`callback_data="set_model:<model>"`, handled by a `CallbackQueryHandler`). `GeminiModelSettings` validates against `GEMINI_MODEL_OPTIONS` in [app/config.py](app/config.py), rewrites `GEMINI_MODEL` in `.env` (`ENV_PATH`, project root; it only persists across container restarts if that file is mounted from the host — `docker compose` mounts the project dir, a plain `docker run --env-file` does not) and sets `NewsGenerator.model`. The model is global across chats; the button press is admin-gated.

**Prompts.** Default prompt is `prompt.txt` at the project root (copied into the Docker image), rendered with `str.format(title=, summary=, url=)`. Per-chat custom prompts in `chat_prompts` override it and are validated at save time (`InvalidPromptError`) — any other `{placeholder}` or literal braces break formatting.

**RSS dedup** is by entry GUID (`id` → `link` → title fallback); only `_MAX_ENTRIES_PER_POLL` newest entries per feed are checked each poll. Feeds are downloaded with httpx (`download_feed`: total-time and size limits, since feedparser's own fetching has no timeout) and the body is passed to `feedparser.parse`. `rss_feed_links.txt` is a reference list only, not read at runtime.

## Testing

Tests never touch real MongoDB, Gemini, or Telegram. [tests/conftest.py](tests/conftest.py) builds the real app classes on top of fakes in [tests/fakes/](tests/fakes/):
- `FakeCollection` — in-memory pymongo stand-in supporting only the query/update operators the repositories actually use (equality, `$or`, `$exists`, `$set`, `$setOnInsert`, upsert, sort). If a repository starts using a new Mongo operator, extend the fake.
- `FakeGenAIClient` / `FakeTGBot` — with `fail_times(n)` etc. to exercise retry paths.
- `tests/fakes/instagram.py` — `FakeConnector` (hands out a shared `FakeInstagramClient` / `FakeImageHost`, scripted credential checks), `FakePageImageFetcher`, `FakeForwarder`, and `configure_instagram(repository, chat_id)` to fully set up a chat; `InstagramClient`/`InstagramConnector` are tested against `httpx.MockTransport`. conftest's `secret_box` uses a fresh generated key. `FakeTGBot.make_admin(user_id, chat_id=...)` scopes admin rights to one chat; `FakeMessage.delete()` records deletion.
- Injection points: `Database._db` is set directly to skip the lazy connect; `NewsGenerator(..., client=fake)`; `TelegramBot.bot = fake`; `RssFeedService(..., download=lambda url: url)` in conftest, so tests stub `feedparser.parse` keyed by URL and never make HTTP calls (`download_feed` itself is tested via `make_http_client(transport=httpx.MockTransport(...))`).

An autouse `no_sleep` fixture replaces the `time`/`asyncio` **names** inside `app.retry`, `app.scheduler`, `app.services.instagram_client` and `app.instagram_forwarder` with proxies whose `sleep` is instant. It deliberately does not patch `time.sleep`/`asyncio.sleep` globally (that would break concurrency tests). If you add a new module that sleeps for retries/backoff, add it to that fixture the same way.
