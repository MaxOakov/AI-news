# AI News Bot

A Telegram bot that turns RSS feeds into fan-style news posts. It fetches articles from configured RSS feeds, rewrites them with the Gemini API using a customizable prompt, and posts the result — with a link back to the source — to one or more Telegram chats/channels. Runs on an hourly schedule during active hours, and can also be triggered on demand from Telegram.

## Features

- **Per-chat RSS feeds** — each Telegram chat manages its own list of RSS sources via bot commands.
- **AI rewriting** — articles are rewritten by the Gemini API in a configurable tone/format (see [Custom Prompts](#custom-prompts)).
- **Per-chat custom prompts** — any chat can override the default `prompt.txt` with its own prompt.
- **Scheduler** — runs once on startup, then every hour during active hours (08:00–22:00 Europe/Kyiv by default), skipping overlapping runs and retrying on transient (503) errors.
- **Forum topic support** — a chat can pin news delivery to a specific forum topic via `/settopic`.
- **Duplicate protection** — new entries are matched by the feed's own entry id (falling back to its link, then its title), so a minor title edit or a repost doesn't slip past, and articles already sent to a chat aren't sent again (tracked in MongoDB).
- **Persistence** — chats, RSS links, custom prompts, and sent/unsent articles are stored in MongoDB, so state survives restarts.

## Architecture

The app is wired together explicitly in a composition root ([main.py](main.py)) rather than relying on module-level singletons — every class receives its dependencies through its constructor.

```
app/
├── config.py              # Loads settings from .env
├── db/
│   ├── database.py         # MongoDB connection
│   ├── article_repository.py
│   ├── chat_repository.py
│   ├── rss_link_repository.py
│   └── prompt_repository.py
├── models/                # Article, Chat dataclasses
├── services/
│   ├── rss_service.py      # Fetches & stores new RSS entries
│   └── news_generator.py   # Rewrites articles via Gemini
├── telegram_bot.py         # Sends messages, tracks registered chats
├── bot_commands.py         # Telegram command handlers
├── news_pipeline.py        # Orchestrates one fetch → generate → send run
├── scheduler.py            # Hourly scheduling + retry logic
└── retry.py                # Shared sync/async retry decorators
```

## Requirements

- Python 3.8+ (Docker image uses 3.14)
- A MongoDB database (e.g. a free MongoDB Atlas cluster)
- A Telegram bot token ([@BotFather](https://t.me/BotFather))
- A Gemini API key

## Setup

1. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**

   Create a `.env` file in the project root:

   ```
   GEMINI_API_KEY=your_gemini_api_key
   GEMINI_MODEL=gemini-2.5-flash
   TELEGRAM_TOKEN=your_telegram_bot_token
   MONGODB_URL=your_mongodb_connection_string
   ```

   | Variable | Required | Description |
   |---|---|---|
   | `GEMINI_API_KEY` | Yes | API key for the Gemini client |
   | `GEMINI_MODEL` | No | Gemini model name (defaults to `gemini-3.1-flash-lite-preview`) |
   | `TELEGRAM_TOKEN` | Yes | Bot token from BotFather |
   | `MONGODB_URL` | Yes | MongoDB connection string (database name used: `news`) |

3. **(Optional) customize the default prompt**

   Edit [prompt.txt](prompt.txt) — see [Custom Prompts](#custom-prompts).

4. **Run the bot**

   ```bash
   python main.py
   # or
   python run.py
   ```

### Running with Docker

```bash
docker compose up --build
```

This builds the image from [Dockerfile](Dockerfile) and runs the container with `.env` loaded, using the `docker-compose.yml` in this repo.

## Usage

Add the bot to a Telegram chat/channel (as admin, if it's a channel) and register it there:

| Command | Description |
|---|---|
| `/start` | Register the current chat with the bot |
| `/help` | List available commands |
| `/runjob`, `/news` | Trigger a news run immediately, for this chat only |
| `/listfeeds` | List RSS feeds registered for this chat |
| `/prompt` | Show the active prompt for this chat |

The commands below change shared chat configuration, so in group/supergroup chats they're restricted to chat admins (anyone can use them in a private chat):

| Command | Description |
|---|---|
| `/settopic` | Pin news delivery to the current forum topic (must be run inside that topic) |
| `/addrss <url1>, <url2>` | Add one or more RSS feeds for this chat |
| `/removerss <url1>, <url2>` | Remove one or more RSS feeds from this chat |
| `/setprompt <text>` | Use a custom prompt for this chat instead of `prompt.txt` |
| `/resetprompt` | Revert to the default `prompt.txt` |
| `/stop` | Deactivate this chat's subscription (RSS feeds and custom prompt are kept; `/start` picks up where this left off) |

Each scheduled or manually-triggered run: fetches new entries from every RSS feed registered for a chat (up to the few most recent per feed per poll), picks the *oldest* unsent article so a backlog works down in order instead of newer items perpetually jumping the queue, rewrites it with Gemini, and sends it to that chat.

## Custom Prompts

The default prompt lives in [prompt.txt](prompt.txt). It's a template rendered with `str.format`, so it must contain these placeholders:

- `{title}` — article title
- `{summary}` — article summary/excerpt
- `{url}` — link to the original article

A chat can override this with its own prompt via `/setprompt`, which must not use any placeholder besides these three (validated at save time, so a typo can't silently break future news runs); `/resetprompt` reverts it to `prompt.txt`.

## Adding RSS Sources

RSS feeds are managed per chat with `/addrss`, `/removerss`, and `/listfeeds` (stored in MongoDB). [rss_feed_links.txt](rss_feed_links.txt) is a plain reference list, not read by the app at runtime.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for recent changes.
