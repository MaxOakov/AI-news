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


async def test_set_topic_id_happy_path(bot_commands, telegram_bot, fake_tg_bot):
    fake_tg_bot.make_admin(1)
    update = make_update(chat_id="1", chat_type="group", user_id=1, message_thread_id=7)
    await bot_commands.set_topic_id(update, make_context(bot=fake_tg_bot))
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
    for command in [
        "/start", "/help", "/runjob", "/news", "/settopic", "/addrss", "/removerss",
        "/listfeeds", "/setprompt", "/resetprompt", "/prompt", "/stop", "/gemini_version",
        "/moderation",
    ]:
        assert command in text


# --------------------------------------------------------------------------
# Every command handler that requires both effective_chat and message must
# return early (no crash, no side effect) when either is missing, e.g. a
# malformed or channel-post Update. Repeated boilerplate across the class,
# but a future edit accidentally dropping one guard would AttributeError.
# --------------------------------------------------------------------------
_ALL_GUARDED_HANDLERS = [
    "set_topic_id", "add_rss_link", "remove_rss_link", "list_rss_links",
    "set_prompt", "reset_prompt", "show_prompt", "stop",
]


@pytest.mark.parametrize("handler_name", _ALL_GUARDED_HANDLERS)
async def test_handler_no_effective_chat_is_a_safe_noop(bot_commands, handler_name):
    handler = getattr(bot_commands, handler_name)
    update = make_update(has_chat=False)
    await handler(update, make_context())  # must not raise


@pytest.mark.parametrize("handler_name", _ALL_GUARDED_HANDLERS)
async def test_handler_no_message_is_a_safe_noop(bot_commands, handler_name):
    handler = getattr(bot_commands, handler_name)
    update = make_update(has_message=False)
    await handler(update, make_context())  # must not raise


# --------------------------------------------------------------------------
# _require_admin — the authorization gate itself
# --------------------------------------------------------------------------
async def test_require_admin_false_when_no_effective_chat(bot_commands):
    update = make_update(has_chat=False)
    assert await bot_commands._require_admin(update, make_context()) is False


async def test_require_admin_always_true_in_private_chats(bot_commands):
    update = make_update(chat_type="private")
    assert await bot_commands._require_admin(update, make_context()) is True
    assert update.message.replies == []


async def test_require_admin_true_for_group_admin(bot_commands, fake_tg_bot):
    fake_tg_bot.make_admin(1, status="administrator")
    update = make_update(chat_type="group", user_id=1)
    assert await bot_commands._require_admin(update, make_context(bot=fake_tg_bot)) is True


async def test_require_admin_true_for_group_creator(bot_commands, fake_tg_bot):
    fake_tg_bot.make_admin(1, status="creator")
    update = make_update(chat_type="group", user_id=1)
    assert await bot_commands._require_admin(update, make_context(bot=fake_tg_bot)) is True


async def test_require_admin_false_for_regular_member(bot_commands, fake_tg_bot):
    update = make_update(chat_type="group", user_id=1)  # not made admin
    result = await bot_commands._require_admin(update, make_context(bot=fake_tg_bot))
    assert result is False
    assert "адміністраторам" in update.message.replies[0]


async def test_require_admin_true_for_anonymous_admin_post(bot_commands):
    update = make_update(chat_type="group", chat_id="55", sender_chat_id="55")
    # No context.bot needed at all: the sender_chat-matches-chat shortcut
    # is checked before ever touching the Bot API.
    assert await bot_commands._require_admin(update, make_context()) is True


async def test_require_admin_sender_chat_mismatch_falls_through_to_member_check(bot_commands, fake_tg_bot):
    # sender_chat set but pointing at a DIFFERENT chat (e.g. a message
    # forwarded/linked from elsewhere) must not grant access.
    update = make_update(chat_type="group", chat_id="55", sender_chat_id="99", user_id=1)
    result = await bot_commands._require_admin(update, make_context(bot=fake_tg_bot))
    assert result is False


async def test_require_admin_bot_api_error_denies_access(bot_commands, fake_tg_bot):
    fake_tg_bot.fail_admin_check()
    update = make_update(chat_type="group", user_id=1)
    result = await bot_commands._require_admin(update, make_context(bot=fake_tg_bot))
    assert result is False
    assert "адміністраторам" in update.message.replies[0]


async def test_group_command_blocked_for_non_admin_no_side_effect(bot_commands, rss_link_repository, fake_tg_bot):
    update = make_update(chat_type="group", user_id=1)
    await bot_commands.add_rss_link(update, make_context(args=["https://a"], bot=fake_tg_bot))
    assert rss_link_repository._db.rss_links.docs == []
    assert "адміністраторам" in update.message.replies[0]


@pytest.mark.parametrize(
    "handler_name,kwargs",
    [
        ("set_topic_id", {}),
        ("add_rss_link", {"args": ["https://a"]}),
        ("remove_rss_link", {"args": ["https://a"]}),
        ("set_prompt", {"args": ["hi"]}),
        ("reset_prompt", {}),
        ("stop", {}),
    ],
)
async def test_every_admin_gated_handler_blocks_non_admin(bot_commands, fake_tg_bot, handler_name, kwargs):
    handler = getattr(bot_commands, handler_name)
    update = make_update(chat_type="group", user_id=1, message_thread_id=7)
    await handler(update, make_context(bot=fake_tg_bot, **kwargs))
    assert "адміністраторам" in update.message.replies[0]


# --------------------------------------------------------------------------
# remove_rss_link
# --------------------------------------------------------------------------
async def test_remove_rss_link_no_args_shows_usage(bot_commands):
    update = make_update(chat_id="1")
    await bot_commands.remove_rss_link(update, make_context(args=[]))
    assert "Використання" in update.message.replies[0]


async def test_remove_rss_link_removes_matching_url(bot_commands, rss_link_repository):
    rss_link_repository.save("1", "https://a")
    rss_link_repository.save("1", "https://b")
    update = make_update(chat_id="1")

    await bot_commands.remove_rss_link(update, make_context(args=["https://a"]))

    remaining = {link["url"] for link in rss_link_repository.get_for_chat("1")}
    assert remaining == {"https://b"}
    assert "Видалено" in update.message.replies[0]


async def test_remove_rss_link_multiple_comma_separated(bot_commands, rss_link_repository):
    rss_link_repository.save("1", "https://a")
    rss_link_repository.save("1", "https://b")
    update = make_update(chat_id="1")

    await bot_commands.remove_rss_link(update, make_context(args=["https://a,", "https://b"]))

    assert rss_link_repository.get_for_chat("1") == []


async def test_remove_rss_link_partial_failure_reports_both(bot_commands, rss_link_repository, monkeypatch):
    calls = {"n": 0}
    real_remove = rss_link_repository.remove

    def flaky_remove(chat_id, url):
        calls["n"] += 1
        if url == "https://bad":
            raise RuntimeError("down")
        return real_remove(chat_id, url)

    monkeypatch.setattr(rss_link_repository, "remove", flaky_remove)
    update = make_update(chat_id="1")

    await bot_commands.remove_rss_link(update, make_context(args=["https://good,", "https://bad"]))

    assert "Видалено" in update.message.replies[0]
    assert "Не вдалося видалити" in update.message.replies[1]
    assert "https://bad" in update.message.replies[1]


# --------------------------------------------------------------------------
# stop
# --------------------------------------------------------------------------
async def test_stop_deactivates_and_removes_from_cache(bot_commands, telegram_bot, chat_repository):
    await telegram_bot.register_chat_db("1", "Chat")
    update = make_update(chat_id="1")

    await bot_commands.stop(update, make_context())

    assert "1" not in telegram_bot.chats
    assert chat_repository.get_all_active() == []  # deactivated in DB too
    assert "Викличте /start" in update.message.replies[0]


async def test_stop_keeps_rss_links_and_prompt_for_later_restart(
    bot_commands, telegram_bot, rss_link_repository, prompt_repository
):
    await telegram_bot.register_chat_db("1", "Chat")
    rss_link_repository.save("1", "https://a")
    prompt_repository.save_custom("1", "custom {title}")
    update = make_update(chat_id="1")

    await bot_commands.stop(update, make_context())

    remaining_urls = {link["url"] for link in rss_link_repository.get_for_chat("1")}
    assert remaining_urls == {"https://a"}
    assert prompt_repository.get_custom("1") == "custom {title}"


async def test_stop_failure_reply(bot_commands, chat_repository, monkeypatch):
    def boom(chat_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(chat_repository, "deactivate", boom)
    update = make_update(chat_id="1")
    await bot_commands.stop(update, make_context())
    assert "❌" in update.message.replies[0]


# --------------------------------------------------------------------------
# set_prompt — invalid template validation
# --------------------------------------------------------------------------
async def test_set_prompt_rejects_invalid_placeholder(bot_commands, prompt_repository):
    update = make_update(chat_id="1")
    await bot_commands.set_prompt(update, make_context(args=["broken", "{oops}"]))
    assert prompt_repository.get_custom("1") is None
    assert "Некоректний prompt" in update.message.replies[0]


async def test_set_prompt_accepts_valid_placeholders(bot_commands, prompt_repository):
    update = make_update(chat_id="1")
    await bot_commands.set_prompt(update, make_context(args=["{title}:", "{summary}", "{url}"]))
    assert prompt_repository.get_custom("1") == "{title}: {summary} {url}"


# --------------------------------------------------------------------------
# add_rss_link — retry-consistent partial failure reporting
# --------------------------------------------------------------------------
async def test_add_rss_link_partial_failure_reports_both(bot_commands, rss_link_repository, monkeypatch):
    real_save = rss_link_repository.save

    def flaky_save(chat_id, url):
        if url == "https://bad":
            raise RuntimeError("down")
        return real_save(chat_id, url)

    monkeypatch.setattr(rss_link_repository, "save", flaky_save)
    update = make_update(chat_id="1")

    await bot_commands.add_rss_link(update, make_context(args=["https://good,", "https://bad"]))

    assert "Збережено" in update.message.replies[0]
    assert "Не вдалося зберегти" in update.message.replies[1]
    assert "https://bad" in update.message.replies[1]


# --------------------------------------------------------------------------
# /gemini_version and the set_model inline-button callback
# --------------------------------------------------------------------------
async def test_gemini_version_no_message_is_noop(bot_commands):
    await bot_commands.gemini_version(make_update(has_message=False), make_context())  # must not raise


async def test_gemini_version_shows_current_model_and_a_button_per_option(bot_commands):
    update = make_update()
    await bot_commands.gemini_version(update, make_context())

    assert "fake-model" in update.message.replies[0]
    keyboard = update.message.reply_markups[0].inline_keyboard
    assert [row[0].callback_data for row in keyboard] == ["set_model:fake-model", "set_model:other-model"]


async def test_set_model_callback_no_callback_query_is_noop(bot_commands):
    await bot_commands.set_model_callback(make_update(), make_context())  # must not raise


async def test_set_model_callback_switches_model(bot_commands, news_generator, env_path, monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    update = make_update(has_message=False, callback_data="set_model:other-model")

    await bot_commands.set_model_callback(update, make_context())

    assert news_generator.model == "other-model"
    assert "GEMINI_MODEL=other-model" in env_path.read_text(encoding="utf-8")
    assert update.callback_query.answers == [{"text": None, "show_alert": False}]
    assert "other-model" in update.callback_query.edits[0]


async def test_set_model_callback_rejects_unknown_model(bot_commands, news_generator, env_path):
    update = make_update(has_message=False, callback_data="set_model:evil-model")

    await bot_commands.set_model_callback(update, make_context())

    assert news_generator.model == "fake-model"
    assert not env_path.exists()
    assert "доступних моделей" in update.callback_query.edits[0]


async def test_set_model_callback_rejects_malformed_data(bot_commands, news_generator):
    update = make_update(has_message=False, callback_data="something_else")

    await bot_commands.set_model_callback(update, make_context())

    assert news_generator.model == "fake-model"
    assert "Невірна команда" in update.callback_query.edits[0]


async def test_set_model_callback_reports_env_write_failure(bot_commands, news_generator, model_settings, monkeypatch):
    def boom(model):
        raise OSError("read-only fs")

    monkeypatch.setattr(model_settings, "set_model", boom)
    update = make_update(has_message=False, callback_data="set_model:other-model")

    await bot_commands.set_model_callback(update, make_context())

    assert news_generator.model == "fake-model"
    assert "Не вдалося оновити" in update.callback_query.edits[0]


async def test_set_model_callback_blocked_for_non_admin_in_group(bot_commands, news_generator, env_path, fake_tg_bot):
    update = make_update(chat_type="supergroup", user_id=7, has_message=False, callback_data="set_model:other-model")

    await bot_commands.set_model_callback(update, make_context(bot=fake_tg_bot))

    assert news_generator.model == "fake-model"
    assert not env_path.exists()
    assert update.callback_query.answers[0]["show_alert"] is True
    assert update.callback_query.edits == []


async def test_set_model_callback_allowed_for_group_admin(bot_commands, news_generator, fake_tg_bot, monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    fake_tg_bot.make_admin(7)
    update = make_update(chat_type="supergroup", user_id=7, has_message=False, callback_data="set_model:other-model")

    await bot_commands.set_model_callback(update, make_context(bot=fake_tg_bot))

    assert news_generator.model == "other-model"


# --------------------------------------------------------------------------
# /moderation
# --------------------------------------------------------------------------
async def _register_group(telegram_bot, chat_id="-100"):
    await telegram_bot.register_chat_db(chat_id, "News group", "supergroup")


async def test_moderation_without_args_shows_status(bot_commands, telegram_bot):
    await _register_group(telegram_bot)
    update = make_update(chat_id="-100", chat_type="supergroup")

    await bot_commands.moderation(update, make_context())
    assert "вимкнена" in update.message.replies[0]

    await telegram_bot.set_reviewer("-100", "7")
    await bot_commands.moderation(update, make_context())
    assert "увімкнена" in update.message.replies[1]


async def test_moderation_on_sets_reviewer_after_reaching_them(bot_commands, telegram_bot, fake_tg_bot):
    await _register_group(telegram_bot)
    fake_tg_bot.make_admin(7)
    update = make_update(chat_id="-100", chat_type="supergroup", user_id=7)

    await bot_commands.moderation(update, make_context(args=["on"], bot=fake_tg_bot))

    assert telegram_bot.chats["-100"].reviewer_chat_id == "7"
    assert fake_tg_bot.sent[0]["chat_id"] == "7"  # confirmation in the admin's private chat
    assert "News group" in fake_tg_bot.sent[0]["text"]
    assert "увімкнено" in update.message.replies[0]


async def test_moderation_on_unreachable_reviewer_leaves_it_off(bot_commands, telegram_bot, fake_tg_bot):
    await _register_group(telegram_bot)
    fake_tg_bot.make_admin(7)
    fake_tg_bot.fail_times(99)  # the admin never started the bot privately
    update = make_update(chat_id="-100", chat_type="supergroup", user_id=7)

    await bot_commands.moderation(update, make_context(args=["on"], bot=fake_tg_bot))

    assert telegram_bot.chats["-100"].reviewer_chat_id is None
    assert "Start" in update.message.replies[0]


async def test_moderation_on_by_anonymous_admin_is_refused(bot_commands, telegram_bot, fake_tg_bot):
    await _register_group(telegram_bot)
    update = make_update(chat_id="-100", chat_type="supergroup", sender_chat_id="-100")

    await bot_commands.moderation(update, make_context(args=["on"], bot=fake_tg_bot))

    assert telegram_bot.chats["-100"].reviewer_chat_id is None
    assert fake_tg_bot.sent == []
    assert "Анонімний" in update.message.replies[0]


async def test_moderation_on_requires_admin(bot_commands, telegram_bot, fake_tg_bot):
    await _register_group(telegram_bot)
    update = make_update(chat_id="-100", chat_type="supergroup", user_id=7)  # not an admin

    await bot_commands.moderation(update, make_context(args=["on"], bot=fake_tg_bot))

    assert telegram_bot.chats["-100"].reviewer_chat_id is None
    assert fake_tg_bot.sent == []


async def test_moderation_on_unregistered_chat(bot_commands, telegram_bot, fake_tg_bot):
    update = make_update(chat_id="-100", chat_type="private")

    await bot_commands.moderation(update, make_context(args=["on"], bot=fake_tg_bot))

    assert "/start" in update.message.replies[0]
    assert fake_tg_bot.sent == []


async def test_moderation_off_clears_reviewer(bot_commands, telegram_bot, chat_repository, fake_tg_bot):
    await _register_group(telegram_bot)
    await telegram_bot.set_reviewer("-100", "7")
    fake_tg_bot.make_admin(7)
    update = make_update(chat_id="-100", chat_type="supergroup", user_id=7)

    await bot_commands.moderation(update, make_context(args=["OFF"], bot=fake_tg_bot))

    assert telegram_bot.chats["-100"].reviewer_chat_id is None
    assert chat_repository.get("-100").reviewer_chat_id is None
    assert "вимкнено" in update.message.replies[0]


async def test_moderation_no_message_is_noop(bot_commands):
    await bot_commands.moderation(make_update(has_message=False), make_context(args=["on"]))


# --------------------------------------------------------------------------
# review_callback: the draft's ✅ / 🔄 / ❌ buttons
# --------------------------------------------------------------------------
async def _drafted_article(telegram_bot, publisher, article_repository):
    from app.models import Article

    await _register_group(telegram_bot)
    await telegram_bot.set_reviewer("-100", "7")
    article = Article(title="T", url="https://example.com/a", chat_id="-100")
    article_repository.create([article])
    await publisher.publish("-100", telegram_bot.chats["-100"], article, "Draft")
    return article


async def test_review_callback_publish_replaces_buttons_with_outcome(
    bot_commands, telegram_bot, publisher, article_repository, fake_tg_bot
):
    article = await _drafted_article(telegram_bot, publisher, article_repository)
    update = make_update(chat_id="7", has_message=False, callback_data=f"review:pub:{article.id}")

    await bot_commands.review_callback(update, make_context())

    query = update.callback_query
    assert query.answers  # answered before the slow part
    [markup] = query.markup_edits
    [[button]] = markup.inline_keyboard
    assert button.text == "✅ Опубліковано"
    assert button.callback_data == "review:done"
    assert fake_tg_bot.sent[-1]["chat_id"] == "-100"


async def test_review_callback_failure_keeps_buttons_and_explains(
    bot_commands, telegram_bot, publisher, article_repository, fake_tg_bot
):
    article = await _drafted_article(telegram_bot, publisher, article_repository)
    fake_tg_bot.fail_times(fake_tg_bot._attempts + 99)
    update = make_update(chat_id="7", has_message=False, callback_data=f"review:pub:{article.id}")

    await bot_commands.review_callback(update, make_context())

    query = update.callback_query
    assert query.markup_edits == []
    assert "Не вдалося опублікувати" in query.message.replies[0]


async def test_review_callback_done_button(bot_commands):
    update = make_update(chat_id="7", has_message=False, callback_data="review:done")

    await bot_commands.review_callback(update, make_context())

    query = update.callback_query
    assert query.answers[0]["text"] == "Цю чернетку вже оброблено."
    assert query.markup_edits == []


async def test_review_callback_no_callback_query_is_noop(bot_commands):
    await bot_commands.review_callback(make_update(), make_context())  # must not raise


@pytest.mark.parametrize("mode, reply", [("on", "Не вдалося увімкнути"), ("off", "Не вдалося вимкнути")])
async def test_moderation_db_failure_is_reported(bot_commands, telegram_bot, chat_repository, fake_tg_bot, monkeypatch, mode, reply):
    await _register_group(telegram_bot)
    fake_tg_bot.make_admin(7)

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(chat_repository, "set_reviewer", boom)
    update = make_update(chat_id="-100", chat_type="supergroup", user_id=7)

    await bot_commands.moderation(update, make_context(args=[mode], bot=fake_tg_bot))

    assert reply in update.message.replies[0]
