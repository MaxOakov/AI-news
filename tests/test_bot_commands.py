from unittest.mock import AsyncMock

import pytest

from tests.fakes.telegram import make_context, make_update


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------
async def test_start_no_effective_chat_is_noop(bot_commands, telegram_bot):
    update = make_update(has_chat=False)
    await bot_commands.start(update, make_context())
    assert telegram_bot.chats == {}


async def test_start_happy_path_registers_and_replies(bot_commands, telegram_bot):
    update = make_update(chat_id="1", chat_type="group", title="My Group")
    await bot_commands.start(update, make_context())

    assert "1" in telegram_bot.chats
    assert telegram_bot.chats["1"].chat_name == "My Group"
    assert len(update.message.replies) == 1
    assert "My Group" in update.message.replies[0]


async def test_start_private_chat_uses_first_name_when_no_title(bot_commands, telegram_bot):
    update = make_update(chat_id="1", chat_type="private", title=None, first_name="Alice")
    await bot_commands.start(update, make_context())
    assert telegram_bot.chats["1"].chat_name == "Alice"


async def test_start_no_message_still_registers_but_does_not_reply(bot_commands, telegram_bot):
    update = make_update(chat_id="1", has_message=False)
    await bot_commands.start(update, make_context())  # must not raise
    assert "1" in telegram_bot.chats


# --------------------------------------------------------------------------
# run_job_now — chat-scoping regression at the command-handler boundary
# --------------------------------------------------------------------------
async def test_run_job_now_passes_the_requesting_chat_id(bot_commands, scheduler_service):
    scheduler_service.trigger_now = AsyncMock(return_value=True)
    update = make_update(chat_id="42")

    await bot_commands.run_job_now(update, make_context())

    scheduler_service.trigger_now.assert_awaited_once_with(chat_id="42")
    assert "цього чату" in update.message.replies[0]


async def test_run_job_now_no_effective_chat_is_noop(bot_commands, scheduler_service):
    scheduler_service.trigger_now = AsyncMock(return_value=True)
    update = make_update(has_chat=False)

    await bot_commands.run_job_now(update, make_context())

    scheduler_service.trigger_now.assert_not_awaited()


async def test_run_job_now_still_running_gives_different_reply(bot_commands, scheduler_service):
    scheduler_service.trigger_now = AsyncMock(return_value=False)
    update = make_update(chat_id="1")

    await bot_commands.run_job_now(update, make_context())

    assert "⏸" in update.message.replies[0]


# --------------------------------------------------------------------------
# set_topic_id
# --------------------------------------------------------------------------
async def test_set_topic_id_outside_a_topic_warns(bot_commands, telegram_bot):
    update = make_update(chat_id="1", message_thread_id=None)
    await bot_commands.set_topic_id(update, make_context())
    assert "1" not in telegram_bot.chats
    assert "лише в темі" in update.message.replies[0]


async def test_set_topic_id_happy_path(bot_commands, telegram_bot):
    update = make_update(chat_id="1", chat_type="group", message_thread_id=7)
    await bot_commands.set_topic_id(update, make_context())
    assert telegram_bot.chats["1"].message_thread_id == 7
    assert "7" in update.message.replies[0]


async def test_set_topic_id_failure_reply(bot_commands, telegram_bot, chat_repository, monkeypatch):
    def boom(chat):
        raise RuntimeError("db down")

    monkeypatch.setattr(chat_repository, "register", boom)
    update = make_update(chat_id="1", message_thread_id=7)
    await bot_commands.set_topic_id(update, make_context())
    assert "❌" in update.message.replies[0]


# --------------------------------------------------------------------------
# add_rss_link
# --------------------------------------------------------------------------
async def test_add_rss_link_no_args_shows_usage(bot_commands, rss_link_repository):
    update = make_update(chat_id="1")
    await bot_commands.add_rss_link(update, make_context(args=[]))
    assert rss_link_repository._db.rss_links.docs == []
    assert "Використання" in update.message.replies[0]


async def test_add_rss_link_saves_each_unique_url(bot_commands, rss_link_repository):
    update = make_update(chat_id="1")
    args = ["https://a,", "https://b,", "https://a"]  # comma-separated + dup
    await bot_commands.add_rss_link(update, make_context(args=args))
    saved = {d["url"] for d in rss_link_repository._db.rss_links.docs}
    assert saved == {"https://a", "https://b"}


async def test_add_rss_link_rejects_whole_batch_on_invalid_url(bot_commands, rss_link_repository):
    update = make_update(chat_id="1")
    args = ["https://good,", "ftp://bad"]
    await bot_commands.add_rss_link(update, make_context(args=args))
    assert rss_link_repository._db.rss_links.docs == []
    assert "Некоректні" in update.message.replies[0]


# --------------------------------------------------------------------------
# list_rss_links
# --------------------------------------------------------------------------
async def test_list_rss_links_empty(bot_commands):
    update = make_update(chat_id="1")
    await bot_commands.list_rss_links(update, make_context())
    assert "не збережено" in update.message.replies[0]


async def test_list_rss_links_non_empty(bot_commands, rss_link_repository):
    rss_link_repository.save("1", "https://a")
    update = make_update(chat_id="1")
    await bot_commands.list_rss_links(update, make_context())
    assert "https://a" in update.message.replies[0]


# --------------------------------------------------------------------------
# set_prompt / reset_prompt / show_prompt
# --------------------------------------------------------------------------
async def test_set_prompt_no_args_shows_usage(bot_commands, prompt_repository):
    update = make_update(chat_id="1")
    await bot_commands.set_prompt(update, make_context(args=[]))
    assert prompt_repository.get_custom("1") is None


async def test_set_prompt_saves_joined_text(bot_commands, prompt_repository):
    update = make_update(chat_id="1")
    await bot_commands.set_prompt(update, make_context(args=["my", "custom", "prompt"]))
    assert prompt_repository.get_custom("1") == "my custom prompt"


async def test_reset_prompt_clears_custom(bot_commands, prompt_repository):
    prompt_repository.save_custom("1", "custom text")
    update = make_update(chat_id="1")
    await bot_commands.reset_prompt(update, make_context())
    assert prompt_repository.get_custom("1") is None


async def test_show_prompt_truncates_long_text(bot_commands, prompt_repository):
    prompt_repository.save_custom("1", "x" * 900)
    update = make_update(chat_id="1")
    await bot_commands.show_prompt(update, make_context())
    assert update.message.replies[0].endswith("...")


async def test_show_prompt_short_text_not_truncated(bot_commands, prompt_repository):
    prompt_repository.save_custom("1", "short prompt")
    update = make_update(chat_id="1")
    await bot_commands.show_prompt(update, make_context())
    assert "short prompt" in update.message.replies[0]
    assert not update.message.replies[0].strip().endswith("...")


# --------------------------------------------------------------------------
# show_help
# --------------------------------------------------------------------------
async def test_show_help_no_message_is_noop(bot_commands):
    update = make_update(has_message=False)
    await bot_commands.show_help(update, make_context())  # must not raise


async def test_show_help_lists_all_commands(bot_commands):
    update = make_update()
    await bot_commands.show_help(update, make_context())
    text = update.message.replies[0]
    for command in ["/start", "/help", "/runjob", "/news", "/settopic", "/addrss", "/listfeeds", "/setprompt", "/resetprompt", "/prompt"]:
        assert command in text


# --------------------------------------------------------------------------
# Every command handler that requires both effective_chat and message must
# return early (no crash, no side effect) when either is missing, e.g. a
# malformed or channel-post Update. Repeated boilerplate across the class,
# but a future edit accidentally dropping one guard would AttributeError.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "handler_name",
    ["set_topic_id", "add_rss_link", "list_rss_links", "set_prompt", "reset_prompt", "show_prompt"],
)
async def test_handler_no_effective_chat_is_a_safe_noop(bot_commands, handler_name):
    handler = getattr(bot_commands, handler_name)
    update = make_update(has_chat=False)
    await handler(update, make_context())  # must not raise


@pytest.mark.parametrize(
    "handler_name",
    ["set_topic_id", "add_rss_link", "list_rss_links", "set_prompt", "reset_prompt", "show_prompt"],
)
async def test_handler_no_message_is_a_safe_noop(bot_commands, handler_name):
    handler = getattr(bot_commands, handler_name)
    update = make_update(has_message=False)
    await handler(update, make_context())  # must not raise
