import pytest

from app.db.instagram_settings_repository import InstagramSettingsRepository
from app.services.instagram_settings import InstagramSettingsService
from app.setup_commands import SESSION_TTL_SECONDS, SetupCommands
from tests.fakes.instagram import configure_instagram
from tests.fakes.telegram import make_context, make_update

GROUP = "-1001"
ADMIN_ID = 42
TOKEN = "EAAB-very-secret-token"
R2_ARGS = ["acc123", "r2-key-id", "r2-secret-key", "bucket", "https://pub.example/"]


@pytest.fixture
async def group(telegram_bot, fake_tg_bot):
    await telegram_bot.register_chat_db(GROUP, "AniKoe", "supergroup", 7)
    fake_tg_bot.make_admin(ADMIN_ID, chat_id=GROUP)


def group_update(user_id=ADMIN_ID):
    return make_update(chat_id=int(GROUP), chat_type="supergroup", title="AniKoe", user_id=user_id)


def private_update(user_id=ADMIN_ID):
    return make_update(chat_id=user_id, chat_type="private", title=None, user_id=user_id)


async def open_private_setup(setup_commands, fake_tg_bot, user_id=ADMIN_ID):
    """Press the group's «🔐 Налаштувати Instagram» button."""
    update = private_update(user_id)
    await setup_commands.start_from_link(update, make_context(args=[f"setup_{GROUP}"], bot=fake_tg_bot))
    return update


async def run(command, update, fake_tg_bot, *args):
    await command(update, make_context(args=list(args), bot=fake_tg_bot))
    return update


# --------------------------------------------------------------------------
# /setup in a group
# --------------------------------------------------------------------------
async def test_setup_in_group_shows_checklist_with_private_setup_button(setup_commands, group, fake_tg_bot):
    update = await run(setup_commands.setup, group_update(), fake_tg_bot)

    [text] = update.message.replies
    assert "Налаштування чату «AniKoe»" in text
    assert "✅ Розсилку новин увімкнено" in text
    assert "❌ Немає жодної RSS-стрічки" in text
    assert "✅ Гілка для новин: 7" in text
    assert "❌ Акаунт Instagram" in text
    assert "Instagram вимкнено" in text
    assert "/ig_account <" not in text  # secret commands are only listed in private
    [[button]] = update.message.reply_markups[0].inline_keyboard
    assert button.url == f"https://t.me/{fake_tg_bot.username}?start=setup_{GROUP}"


async def test_setup_in_group_is_for_admins_only(setup_commands, group, fake_tg_bot):
    update = await run(setup_commands.setup, group_update(user_id=7), fake_tg_bot)

    assert update.message.replies == ["⛔ Ця команда доступна лише адміністраторам чату."]


async def test_setup_counts_feeds(setup_commands, group, fake_tg_bot, rss_link_repository):
    rss_link_repository.save(GROUP, "https://a.example/rss")
    rss_link_repository.save(GROUP, "https://b.example/rss")

    update = await run(setup_commands.setup, group_update(), fake_tg_bot)

    assert "✅ RSS-стрічок: 2" in update.message.replies[0]
    assert "→ Новини працюють." in update.message.replies[0]


async def test_setup_checks_the_stored_token_live(
    setup_commands, group, fake_tg_bot, fake_connector, instagram_settings_repository, instagram_settings
):
    configure_instagram(instagram_settings_repository, GROUP)
    await instagram_settings.load()
    fake_connector.instagram.fail("Error validating access token: The session is invalid because the user logged out.")

    update = await run(setup_commands.setup, group_update(), fake_tg_bot)

    text = update.message.replies[0]
    assert "❌ Акаунт Instagram @anikoe: Error validating access token" in text
    assert "Instagram вимкнено" in text


async def test_setup_of_a_fully_configured_chat(
    setup_commands, group, fake_tg_bot, instagram_settings_repository, instagram_settings
):
    configure_instagram(instagram_settings_repository, GROUP)
    await instagram_settings.load()

    text = (await run(setup_commands.setup, group_update(), fake_tg_bot)).message.replies[0]

    assert "✅ Акаунт Instagram: @anikoe" in text
    assert "✅ Сховище Cloudflare R2: бакет bucket" in text
    assert "✅ Хештеги для відбору постів: #Команда_AniKoe" in text
    assert "✅ Додаткові хештеги в підпис: #аніме" in text
    assert "→ Пости з гілки новин з #Команда_AniKoe публікуються в Instagram @anikoe." in text
    # No secret ever appears in a checklist.
    assert "token-" not in text and "key-secret" not in text


# --------------------------------------------------------------------------
# The private setup link
# --------------------------------------------------------------------------
async def test_setup_link_opens_private_setup_for_the_group(setup_commands, group, fake_tg_bot, telegram_bot):
    update = await open_private_setup(setup_commands, fake_tg_bot)

    [text] = update.message.replies
    assert "Налаштування чату «AniKoe»" in text
    assert "/ig_account <ID акаунта Instagram> <токен доступу>" in text
    assert update.message.reply_markups == [None]
    assert str(ADMIN_ID) not in telegram_bot.chats  # the private chat isn't subscribed to news


async def test_setup_link_refuses_non_admins(setup_commands, group, fake_tg_bot):
    update = await open_private_setup(setup_commands, fake_tg_bot, user_id=7)

    assert update.message.replies == ["⛔ Налаштовувати чат можуть лише його адміністратори."]
    # And nothing is set up for them afterwards.
    after = await run(setup_commands.ig_track, private_update(7), fake_tg_bot, "#tag")
    assert "викличте в ній /setup" in after.message.replies[0]


@pytest.mark.parametrize("args", [[], ["setup_"], ["setup_abc"], ["other"]])
async def test_setup_link_with_bad_payload(setup_commands, group, fake_tg_bot, args):
    update = private_update()
    await setup_commands.start_from_link(update, make_context(args=args, bot=fake_tg_bot))

    assert "Некоректне посилання" in update.message.replies[0]


# --------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------
async def test_account_saved_encrypted_and_message_deleted(
    setup_commands, group, fake_tg_bot, fake_connector, instagram_settings, fake_db_handle
):
    await open_private_setup(setup_commands, fake_tg_bot)

    update = await run(setup_commands.ig_account, private_update(), fake_tg_bot, "17841400000", TOKEN)

    assert update.message.deleted
    assert fake_connector.account_checks == [("17841400000", TOKEN)]
    text = update.message.replies[-1]
    assert text.startswith("✅ Акаунт Instagram @anikoe підключено.")
    assert "✅ Акаунт Instagram: @anikoe" in text and TOKEN not in text
    settings = await instagram_settings.get(GROUP)
    assert settings.instagram_token == TOKEN
    assert settings.admin_user_id == str(ADMIN_ID)
    assert settings.instagram_api_host == "graph.facebook.com"
    assert TOKEN not in repr(fake_db_handle.instagram_settings.docs)


async def test_rejected_token_is_not_saved(setup_commands, group, fake_tg_bot, fake_connector, instagram_settings):
    await open_private_setup(setup_commands, fake_tg_bot)
    fake_connector.account_error = "Invalid OAuth access token"

    update = await run(setup_commands.ig_account, private_update(), fake_tg_bot, "17841400000", TOKEN)

    assert update.message.deleted
    assert update.message.replies == ["❌ Instagram не прийняв токен: Invalid OAuth access token"]
    assert await instagram_settings.get(GROUP) is None


@pytest.mark.parametrize("args", [["17841400000"], ["not-a-number", TOKEN], ["1", TOKEN, "extra"]])
async def test_account_usage(setup_commands, group, fake_tg_bot, fake_connector, args):
    await open_private_setup(setup_commands, fake_tg_bot)

    update = await run(setup_commands.ig_account, private_update(), fake_tg_bot, *args)

    assert update.message.deleted  # it may still have carried a secret
    assert update.message.replies[0].startswith("Використання: /ig_account")
    assert fake_connector.account_checks == []


async def test_secret_sent_to_group_is_deleted_and_refused(setup_commands, group, fake_tg_bot, fake_connector):
    update = await run(setup_commands.ig_account, group_update(), fake_tg_bot, "17841400000", TOKEN)

    assert update.message.deleted
    assert update.message.replies == []  # can't reply to a deleted message in a group
    [warning] = fake_tg_bot.sent
    assert warning["chat_id"] == int(GROUP)
    assert "Я видалив повідомлення" in warning["text"] and "перевипустіть" in warning["text"]
    assert TOKEN not in warning["text"]
    assert fake_connector.account_checks == []


async def test_secret_in_group_when_bot_cannot_delete(setup_commands, group, fake_tg_bot, fake_connector):
    update = group_update()
    update.message.delete_fails = True

    await run(setup_commands.ig_r2, update, fake_tg_bot, *R2_ARGS)

    assert not update.message.deleted
    assert "Видаліть це повідомлення" in fake_tg_bot.sent[0]["text"]
    assert fake_connector.r2_checks == []


async def test_secret_command_without_args_in_group_just_points_to_private(setup_commands, group, fake_tg_bot):
    update = await run(setup_commands.ig_account, group_update(), fake_tg_bot)

    assert not update.message.deleted
    assert "лише в особистих повідомленнях" in update.message.replies[0]


async def test_without_encryption_key_secrets_are_refused(
    telegram_bot, rss_link_repository, database, fake_connector, group, fake_tg_bot
):
    keyless = SetupCommands(
        telegram_bot, rss_link_repository, InstagramSettingsService(InstagramSettingsRepository(database, None)),
        fake_connector,
    )
    await open_private_setup(keyless, fake_tg_bot)

    update = await run(keyless.ig_account, private_update(), fake_tg_bot, "17841400000", TOKEN)

    assert update.message.deleted
    assert "SECRETS_ENCRYPTION_KEY" in update.message.replies[0]
    assert fake_connector.account_checks == []
    checklist = (await run(keyless.setup, group_update(), fake_tg_bot)).message.replies[0]
    assert "❌ На сервері не задано ключ шифрування" in checklist


async def test_r2_saved_after_check(setup_commands, group, fake_tg_bot, fake_connector, instagram_settings, fake_db_handle):
    await open_private_setup(setup_commands, fake_tg_bot)

    update = await run(setup_commands.ig_r2, private_update(), fake_tg_bot, *R2_ARGS)

    assert update.message.deleted
    assert fake_connector.r2_checks == [("acc123", "r2-key-id", "r2-secret-key", "bucket", "https://pub.example")]
    assert "✅ Сховище Cloudflare R2: бакет bucket" in update.message.replies[-1]
    settings = await instagram_settings.get(GROUP)
    assert (settings.r2_access_key_id, settings.r2_secret_access_key) == ("r2-key-id", "r2-secret-key")
    assert settings.r2_public_base_url == "https://pub.example"
    stored = repr(fake_db_handle.instagram_settings.docs)
    assert "r2-key-id" not in stored and "r2-secret-key" not in stored


async def test_r2_failed_check_is_not_saved(setup_commands, group, fake_tg_bot, fake_connector, instagram_settings):
    await open_private_setup(setup_commands, fake_tg_bot)
    fake_connector.r2_error = "файл не відкривається за публічним URL (HTTP 404)"

    update = await run(setup_commands.ig_r2, private_update(), fake_tg_bot, *R2_ARGS)

    assert update.message.replies[-1] == "❌ Бакет не підходить: файл не відкривається за публічним URL (HTTP 404)"
    assert await instagram_settings.get(GROUP) is None


@pytest.mark.parametrize(
    "args, error",
    [
        (["acc123", "id", "secret", "bucket", "http://pub.example"], "https://"),
        (["acc-123/x", "id", "secret", "bucket", "https://pub.example"], "Account ID"),
        (["acc123", "id", "secret", "bucket"], "Використання"),
    ],
)
async def test_r2_validation(setup_commands, group, fake_tg_bot, fake_connector, args, error):
    await open_private_setup(setup_commands, fake_tg_bot)

    update = await run(setup_commands.ig_r2, private_update(), fake_tg_bot, *args)

    assert error in update.message.replies[0]
    assert fake_connector.r2_checks == []


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------
async def test_session_expires(telegram_bot, rss_link_repository, instagram_settings, fake_connector, group, fake_tg_bot):
    now = [1000.0]
    commands = SetupCommands(telegram_bot, rss_link_repository, instagram_settings, fake_connector, clock=lambda: now[0])
    await open_private_setup(commands, fake_tg_bot)

    now[0] += SESSION_TTL_SECONDS + 1
    update = await run(commands.ig_track, private_update(), fake_tg_bot, "#tag")

    assert "викличте в ній /setup" in update.message.replies[0]
    assert await instagram_settings.get(GROUP) is None


async def test_session_ends_when_user_is_no_longer_admin(setup_commands, group, fake_tg_bot, instagram_settings):
    await open_private_setup(setup_commands, fake_tg_bot)
    fake_tg_bot._admins.clear()

    update = await run(setup_commands.ig_track, private_update(), fake_tg_bot, "#tag")

    assert update.message.replies == ["⛔ Ви більше не адміністратор чату, який налаштовували."]
    assert await instagram_settings.get(GROUP) is None


async def test_private_chat_that_gets_news_is_set_up_directly(setup_commands, fake_tg_bot, telegram_bot, instagram_settings):
    await telegram_bot.register_chat_db(str(ADMIN_ID), "Max", "private")

    update = await run(setup_commands.ig_account, private_update(), fake_tg_bot, "17841400000", TOKEN)

    assert (await instagram_settings.get(str(ADMIN_ID))).instagram_token == TOKEN
    assert "Налаштування чату «Max»" in update.message.replies[-1]


# --------------------------------------------------------------------------
# Hashtags and reset
# --------------------------------------------------------------------------
async def test_hashtag_can_be_set_in_the_group(setup_commands, group, fake_tg_bot, instagram_settings):
    update = await run(setup_commands.ig_track, group_update(), fake_tg_bot, "Команда_AniKoe")

    assert update.message.replies[0].startswith("✅ В Instagram підуть пости з #Команда_AniKoe.")
    assert (await instagram_settings.get(GROUP)).trigger_hashtags == ["#Команда_AniKoe"]
    assert update.message.reply_markups[0] is not None  # the group checklist keeps its button


async def test_hashtag_commands_are_for_admins(setup_commands, group, fake_tg_bot, instagram_settings):
    await run(setup_commands.ig_track, group_update(user_id=7), fake_tg_bot, "#tag")
    await run(setup_commands.ig_tags, group_update(user_id=7), fake_tg_bot, "#a")
    await run(setup_commands.ig_reset, group_update(user_id=7), fake_tg_bot)

    assert await instagram_settings.get(GROUP) is None


@pytest.mark.parametrize("args", [[], ["#тег!"], ["#ok", "погано!"], [f"#t{i}" for i in range(31)]])
async def test_hashtag_validation(setup_commands, group, fake_tg_bot, instagram_settings, args):
    update = await run(setup_commands.ig_track, group_update(), fake_tg_bot, *args)

    assert update.message.replies[0].startswith(("Використання", "❌"))
    assert await instagram_settings.get(GROUP) is None


async def test_extra_hashtags_are_normalized_and_deduplicated(setup_commands, group, fake_tg_bot, instagram_settings):
    await run(setup_commands.ig_tags, group_update(), fake_tg_bot, "#аніме", "анімеукраїна", "#Аніме")

    assert (await instagram_settings.get(GROUP)).extra_hashtags == ["#аніме", "#анімеукраїна"]


async def test_extra_hashtags_off(setup_commands, group, fake_tg_bot, instagram_settings):
    await run(setup_commands.ig_tags, group_update(), fake_tg_bot, "#аніме")
    update = await run(setup_commands.ig_tags, group_update(), fake_tg_bot, "off")

    assert (await instagram_settings.get(GROUP)).extra_hashtags == []
    assert "більше не додаються" in update.message.replies[0]


@pytest.mark.parametrize("args", [[], ["#ok", "bad!"], [f"#t{i}" for i in range(31)]])
async def test_extra_hashtags_validation(setup_commands, group, fake_tg_bot, instagram_settings, args):
    update = await run(setup_commands.ig_tags, group_update(), fake_tg_bot, *args)

    assert update.message.replies[0].startswith(("Використання", "❌"))
    assert await instagram_settings.get(GROUP) is None


async def test_reset_removes_everything(
    setup_commands, group, fake_tg_bot, instagram_settings_repository, instagram_settings, fake_db_handle
):
    configure_instagram(instagram_settings_repository, GROUP)
    await instagram_settings.load()

    update = await run(setup_commands.ig_reset, group_update(), fake_tg_bot)

    assert update.message.replies[0].startswith("🗑 Налаштування Instagram цього чату видалено")
    assert fake_db_handle.instagram_settings.docs == []
    assert instagram_settings.route_for(GROUP) is None


async def test_reset_when_nothing_is_set(setup_commands, group, fake_tg_bot):
    update = await run(setup_commands.ig_reset, group_update(), fake_tg_bot)

    assert update.message.replies[0].startswith("ℹ️ Instagram для цього чату й так не налаштовано.")


# --------------------------------------------------------------------------
# The whole flow
# --------------------------------------------------------------------------
async def test_full_setup_enables_instagram_for_the_chat(setup_commands, group, fake_tg_bot, instagram_settings):
    await open_private_setup(setup_commands, fake_tg_bot)
    await run(setup_commands.ig_account, private_update(), fake_tg_bot, "17841400000", TOKEN)
    await run(setup_commands.ig_r2, private_update(), fake_tg_bot, *R2_ARGS)
    assert instagram_settings.route_for(GROUP) is None  # no hashtag yet

    update = await run(setup_commands.ig_track, private_update(), fake_tg_bot, "#Команда_AniKoe")

    assert instagram_settings.route_for(GROUP).hashtags == ("#Команда_AniKoe",)
    assert "→ Пости з гілки новин з #Команда_AniKoe публікуються в Instagram @anikoe." in update.message.replies[-1]


# --------------------------------------------------------------------------
# Checklist edge cases
# --------------------------------------------------------------------------
async def test_setup_in_a_group_that_never_ran_start(setup_commands, fake_tg_bot):
    fake_tg_bot.make_admin(ADMIN_ID, chat_id="-1009")
    fake_tg_bot.chat_titles["-1009"] = "New group"

    update = make_update(chat_id=-1009, chat_type="supergroup", title="New group", user_id=ADMIN_ID)
    await run(setup_commands.setup, update, fake_tg_bot)

    text = update.message.replies[0]
    assert "Налаштування чату «New group»" in text
    assert "❌ Розсилку новин вимкнено — /start" in text


async def test_setup_when_stored_secrets_cannot_be_decrypted(
    setup_commands, group, fake_tg_bot, fake_db_handle, instagram_settings_repository, instagram_settings
):
    configure_instagram(instagram_settings_repository, GROUP)
    fake_db_handle.instagram_settings.docs[0]["instagram_token_encrypted"] = "gAAAA-garbage"
    await instagram_settings.load()

    text = (await run(setup_commands.setup, group_update(), fake_tg_bot)).message.replies[0]

    assert "❌ Збережені ключі не вдається розшифрувати" in text
    assert "❌ Акаунт Instagram — /ig_account" in text
    assert instagram_settings.route_for(GROUP) is None


async def test_setup_of_configured_chat_that_stopped_news(
    setup_commands, group, fake_tg_bot, telegram_bot, instagram_settings_repository, instagram_settings
):
    configure_instagram(instagram_settings_repository, GROUP)
    await instagram_settings.load()
    await telegram_bot.deactivate_chat_db(GROUP)

    text = (await run(setup_commands.setup, group_update(), fake_tg_bot)).message.replies[0]

    assert "❌ Розсилку новин вимкнено" in text
    assert "працює, лише поки чат підписаний на новини" in text


async def test_news_status_line_says_what_is_missing(setup_commands, group, fake_tg_bot, telegram_bot):
    text = (await run(setup_commands.setup, group_update(), fake_tg_bot)).message.replies[0]
    assert "→ Щоб бот публікував новини, додайте хоча б одну RSS-стрічку." in text

    await telegram_bot.deactivate_chat_db(GROUP)
    text = (await run(setup_commands.setup, group_update(), fake_tg_bot)).message.replies[0]
    assert "→ Щоб бот публікував новини, увімкніть розсилку: /start." in text


# --------------------------------------------------------------------------
# /ig_track: several hashtags
# --------------------------------------------------------------------------
async def test_track_several_hashtags(setup_commands, group, fake_tg_bot, instagram_settings):
    update = await run(setup_commands.ig_track, group_update(), fake_tg_bot, "#Команда_AniKoe", "в_інсту")

    assert (await instagram_settings.get(GROUP)).trigger_hashtags == ["#Команда_AniKoe", "#в_інсту"]
    text = update.message.replies[0]
    assert text.startswith("✅ В Instagram підуть пости з #Команда_AniKoe або #в_інсту.")
    assert "✅ Хештеги для відбору постів: #Команда_AniKoe #в_інсту" in text


async def test_track_accepts_commas_and_drops_duplicates(setup_commands, group, fake_tg_bot, instagram_settings):
    await run(setup_commands.ig_track, group_update(), fake_tg_bot, "#a,", "#b,#A")

    assert (await instagram_settings.get(GROUP)).trigger_hashtags == ["#a", "#b"]


async def test_track_off_disables_instagram(
    setup_commands, group, fake_tg_bot, instagram_settings_repository, instagram_settings
):
    configure_instagram(instagram_settings_repository, GROUP)
    await instagram_settings.load()

    update = await run(setup_commands.ig_track, group_update(), fake_tg_bot, "off")

    assert instagram_settings.route_for(GROUP) is None
    assert "Хештеги для відбору очищено" in update.message.replies[0]
    assert "❌ Хештеги для відбору постів — /ig_track" in update.message.replies[0]


async def test_ready_status_lists_every_tracked_hashtag(
    setup_commands, group, fake_tg_bot, instagram_settings_repository, instagram_settings
):
    configure_instagram(instagram_settings_repository, GROUP, trigger=["#a", "#b"])
    await instagram_settings.load()

    text = (await run(setup_commands.setup, group_update(), fake_tg_bot)).message.replies[0]

    assert "→ Пости з гілки новин з #a або #b публікуються в Instagram @anikoe." in text


# --------------------------------------------------------------------------
# /ig_topic
# --------------------------------------------------------------------------
def topic_update(thread_id=9, topic_name="Інстаграм", user_id=ADMIN_ID, is_topic_message=None):
    return make_update(
        chat_id=int(GROUP), chat_type="supergroup", title="AniKoe", user_id=user_id,
        message_thread_id=thread_id, topic_name=topic_name, is_topic_message=is_topic_message,
    )


async def test_topic_picked_from_inside_it(
    setup_commands, group, fake_tg_bot, instagram_settings_repository, instagram_settings
):
    configure_instagram(instagram_settings_repository, GROUP)
    await instagram_settings.load()

    update = await run(setup_commands.ig_topic, topic_update(), fake_tg_bot)

    settings = await instagram_settings.get(GROUP)
    assert (settings.instagram_topic_id, settings.instagram_topic_name, settings.instagram_all_topics) == (
        9, "Інстаграм", False
    )
    assert instagram_settings.route_for(GROUP).topic_id == 9
    text = update.message.replies[0]
    assert text.startswith("✅ В Instagram підуть пости з гілки «Інстаграм».")
    assert "✅ Гілка для Instagram: «Інстаграм»" in text
    # News go to topic 7, so the bot's own posts won't reach Instagram: say so.
    assert "ℹ️ Новини бота йдуть в іншу гілку" in text
    assert "→ Пости з гілки «Інстаграм» з #Команда_AniKoe публікуються" in text


async def test_topic_without_a_known_name_is_shown_by_id(setup_commands, group, fake_tg_bot, instagram_settings):
    update = await run(setup_commands.ig_topic, topic_update(thread_id=9, topic_name=None), fake_tg_bot)

    assert update.message.replies[0].startswith("✅ В Instagram підуть пости з цієї гілки.")
    assert "✅ Гілка для Instagram: 9" in update.message.replies[0]


async def test_choosing_the_news_topic_itself_needs_no_warning(setup_commands, group, fake_tg_bot):
    update = await run(setup_commands.ig_topic, topic_update(thread_id=7, topic_name="Новини"), fake_tg_bot)

    assert "ℹ️ Новини бота йдуть в іншу гілку" not in update.message.replies[0]


async def test_topic_all_and_back_to_news(setup_commands, group, fake_tg_bot, instagram_settings):
    update = await run(setup_commands.ig_topic, group_update(), fake_tg_bot, "all")
    assert (await instagram_settings.get(GROUP)).instagram_all_topics is True
    assert "✅ Гілка для Instagram: увесь чат" in update.message.replies[0]

    update = await run(setup_commands.ig_topic, group_update(), fake_tg_bot, "news")
    settings = await instagram_settings.get(GROUP)
    assert settings.instagram_all_topics is False and settings.instagram_topic_id is None
    assert "✅ Гілка для Instagram: та сама, що й для новин (7)" in update.message.replies[0]


async def test_topic_modes_can_be_set_privately(setup_commands, group, fake_tg_bot, instagram_settings):
    await open_private_setup(setup_commands, fake_tg_bot)

    await run(setup_commands.ig_topic, private_update(), fake_tg_bot, "all")

    assert (await instagram_settings.get(GROUP)).instagram_all_topics is True


@pytest.mark.parametrize(
    "make, args",
    [
        (lambda: group_update(), []),                                   # General / not in a topic
        (lambda: topic_update(thread_id=55, is_topic_message=False), []),  # a reply thread, not a forum topic
        (lambda: private_update(), []),                                 # no topic to take in private
        (lambda: group_update(), ["somewhere"]),
    ],
)
async def test_topic_usage(setup_commands, group, fake_tg_bot, instagram_settings, make, args):
    if make().effective_chat.type == "private":
        await open_private_setup(setup_commands, fake_tg_bot)

    update = await run(setup_commands.ig_topic, make(), fake_tg_bot, *args)

    assert update.message.replies[-1].startswith("Звідки брати пости для Instagram:")
    assert await instagram_settings.get(GROUP) is None


async def test_topic_is_for_admins(setup_commands, group, fake_tg_bot, instagram_settings):
    update = await run(setup_commands.ig_topic, topic_update(user_id=7), fake_tg_bot)

    assert update.message.replies == ["⛔ Ця команда доступна лише адміністраторам чату."]
    assert await instagram_settings.get(GROUP) is None


async def test_default_topic_line_without_a_news_topic(setup_commands, fake_tg_bot, telegram_bot):
    await telegram_bot.register_chat_db("-1002", "Plain", "supergroup")
    fake_tg_bot.make_admin(ADMIN_ID, chat_id="-1002")

    update = make_update(chat_id=-1002, chat_type="supergroup", title="Plain", user_id=ADMIN_ID)
    await run(setup_commands.setup, update, fake_tg_bot)

    assert "✅ Гілка для Instagram: увесь чат (гілку для новин не вибрано)" in update.message.replies[0]
