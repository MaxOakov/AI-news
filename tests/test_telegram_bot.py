from app.models import Chat


# --------------------------------------------------------------------------
# load_chats_from_db
# --------------------------------------------------------------------------
async def test_load_chats_from_db_populates_cache(telegram_bot, chat_repository):
    chat_repository.register(Chat(chat_id="1", chat_name="A"))
    chat_repository.register(Chat(chat_id="2", chat_name="B"))

    await telegram_bot.load_chats_from_db()

    assert set(telegram_bot.chats) == {"1", "2"}
    assert telegram_bot.chats["1"].chat_name == "A"


async def test_load_chats_from_db_replaces_not_merges(telegram_bot, chat_repository):
    chat_repository.register(Chat(chat_id="1", chat_name="A"))
    await telegram_bot.load_chats_from_db()
    assert set(telegram_bot.chats) == {"1"}

    chat_repository.deactivate("1")
    chat_repository.register(Chat(chat_id="2", chat_name="B"))
    await telegram_bot.load_chats_from_db()

    assert set(telegram_bot.chats) == {"2"}


async def test_load_chats_from_db_swallows_repository_errors(telegram_bot, chat_repository, monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(chat_repository, "get_all_active", boom)
    await telegram_bot.load_chats_from_db()  # must not raise
    assert telegram_bot.chats == {}


# --------------------------------------------------------------------------
# register_chat_db — topic-id preservation regression (the real bug found
# during the refactor: a plain /start after /settopic must not clear the
# chat's stored forum-topic id).
# --------------------------------------------------------------------------
async def test_register_chat_db_topic_id_preservation(telegram_bot, chat_repository):
    ok1 = await telegram_bot.register_chat_db("123", "Chat", "group", message_thread_id=42)
    assert ok1 is True
    assert telegram_bot.chats["123"].message_thread_id == 42

    # Plain /start again, no topic id supplied -> must NOT clear it.
    ok2 = await telegram_bot.register_chat_db("123", "Chat", "group", message_thread_id=None)
    assert ok2 is True
    assert telegram_bot.chats["123"].message_thread_id == 42
    assert chat_repository._db.chats.docs[0]["message_thread_id"] == 42

    # A genuinely new topic id must still take effect.
    ok3 = await telegram_bot.register_chat_db("123", "Chat", "group", message_thread_id=99)
    assert ok3 is True
    assert telegram_bot.chats["123"].message_thread_id == 99


async def test_register_chat_db_first_ever_registration_without_topic(telegram_bot):
    ok = await telegram_bot.register_chat_db("999", "New Chat", "private", message_thread_id=None)
    assert ok is True
    assert telegram_bot.chats["999"].message_thread_id is None


async def test_register_chat_db_repository_failure_returns_false(telegram_bot, chat_repository, monkeypatch):
    def boom(chat):
        raise RuntimeError("db down")

    monkeypatch.setattr(chat_repository, "register", boom)
    ok = await telegram_bot.register_chat_db("1", "Chat")
    assert ok is False
    assert "1" not in telegram_bot.chats


# --------------------------------------------------------------------------
# deactivate_chat_db
# --------------------------------------------------------------------------
async def test_deactivate_chat_db_removes_from_cache_and_deactivates_in_db(
    telegram_bot, chat_repository
):
    await telegram_bot.register_chat_db("1", "Chat")
    ok = await telegram_bot.deactivate_chat_db("1")
    assert ok is True
    assert "1" not in telegram_bot.chats
    assert chat_repository.get_all_active() == []


async def test_deactivate_chat_db_repository_failure_returns_false(
    telegram_bot, chat_repository, monkeypatch
):
    await telegram_bot.register_chat_db("1", "Chat")

    def boom(chat_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(chat_repository, "deactivate", boom)
    ok = await telegram_bot.deactivate_chat_db("1")
    assert ok is False
    assert "1" in telegram_bot.chats  # unchanged on failure


async def test_start_after_stop_preserves_topic_id_via_db_fallback(telegram_bot):
    # Regression test: /stop evicts the chat from the in-memory cache, so a
    # later plain /start (no explicit /settopic) has nothing cached to merge
    # the topic id from. It must fall back to the database instead of
    # silently losing message_thread_id for the rest of the process's life.
    await telegram_bot.register_chat_db("1", "Chat", message_thread_id=42)
    await telegram_bot.deactivate_chat_db("1")
    assert "1" not in telegram_bot.chats

    ok = await telegram_bot.register_chat_db("1", "Chat", message_thread_id=None)
    assert ok is True
    assert telegram_bot.chats["1"].message_thread_id == 42


# --------------------------------------------------------------------------
# send_message
# --------------------------------------------------------------------------
async def test_send_message_no_token_returns_false(chat_repository):
    from app.telegram_bot import TelegramBot

    bot = TelegramBot(token="", chat_repository=chat_repository)
    assert bot.bot is None
    assert await bot.send_message("1", "hi") is False


async def test_send_message_happy_path(telegram_bot, fake_tg_bot):
    ok = await telegram_bot.send_message("1", "hi", message_thread_id=5)
    assert ok is True
    assert fake_tg_bot.sent == [
        {"chat_id": "1", "text": "hi", "parse_mode": "HTML", "message_thread_id": 5}
    ]


async def test_send_message_omits_empty_thread_id(telegram_bot, fake_tg_bot):
    await telegram_bot.send_message("1", "hi", message_thread_id="")
    assert "message_thread_id" not in fake_tg_bot.sent[0]

    await telegram_bot.send_message("1", "hi", message_thread_id=None)
    assert "message_thread_id" not in fake_tg_bot.sent[1]


async def test_send_message_invalid_thread_id_is_dropped(telegram_bot, fake_tg_bot):
    await telegram_bot.send_message("1", "hi", message_thread_id="not-a-number")
    assert "message_thread_id" not in fake_tg_bot.sent[0]
    assert fake_tg_bot.sent[0]["text"] == "hi"


async def test_send_message_retries_then_succeeds(telegram_bot, fake_tg_bot):
    fake_tg_bot.fail_times(1)
    ok = await telegram_bot.send_message("1", "hi")
    assert ok is True
    assert fake_tg_bot._attempts == 2


async def test_send_message_exhausted_returns_false(telegram_bot, fake_tg_bot):
    fake_tg_bot.fail_times(99)
    ok = await telegram_bot.send_message("1", "hi")
    assert ok is False
    assert fake_tg_bot.sent == []


# --------------------------------------------------------------------------
# send_to_all_chats
# --------------------------------------------------------------------------
async def test_send_to_all_chats_uses_each_chats_topic_id(telegram_bot, fake_tg_bot):
    await telegram_bot.register_chat_db("1", "A", message_thread_id=10)
    await telegram_bot.register_chat_db("2", "B", message_thread_id=None)

    results = await telegram_bot.send_to_all_chats("broadcast")

    assert results == {"1": True, "2": True}
    sent_by_chat = {m["chat_id"]: m for m in fake_tg_bot.sent}
    assert sent_by_chat["1"]["message_thread_id"] == 10
    assert "message_thread_id" not in sent_by_chat["2"]
