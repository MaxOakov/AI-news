from tests.fakes.instagram import configure_instagram


async def test_load_indexes_only_fully_configured_chats(instagram_settings_repository, instagram_settings):
    configure_instagram(instagram_settings_repository, "-1001")
    configure_instagram(instagram_settings_repository, "-1002", trigger=None)

    await instagram_settings.load()

    assert instagram_settings.route_for("-1001").hashtags == ("#Команда_AniKoe",)
    assert instagram_settings.route_for(-1001) is not None  # ids are normalized to str
    assert instagram_settings.route_for("-1002") is None
    assert instagram_settings.route_for("-1003") is None


async def test_saving_the_last_missing_piece_enables_the_chat(instagram_settings_repository, instagram_settings):
    configure_instagram(instagram_settings_repository, "-1001", trigger=None)
    await instagram_settings.load()
    assert instagram_settings.route_for("-1001") is None

    await instagram_settings.save_trigger_hashtags("-1001", ["#новий"])

    assert instagram_settings.route_for("-1001").hashtags == ("#новий",)


async def test_every_save_keeps_the_index_current(instagram_settings):
    await instagram_settings.save_account("-1001", "1784", "anikoe", "graph.facebook.com", "token", "555")
    await instagram_settings.save_r2("-1001", "acc", "bucket", "https://pub.example", "id", "secret")
    assert instagram_settings.route_for("-1001") is None

    await instagram_settings.save_trigger_hashtags("-1001", ["#tag"])
    await instagram_settings.save_extra_hashtags("-1001", ["#a"])

    assert instagram_settings.route_for("-1001").hashtags == ("#tag",)
    settings = await instagram_settings.get("-1001")
    assert settings.extra_hashtags == ["#a"] and settings.instagram_token == "token"


async def test_reset_disables_the_chat(instagram_settings_repository, instagram_settings):
    configure_instagram(instagram_settings_repository, "-1001")
    await instagram_settings.load()

    assert await instagram_settings.reset("-1001") is True

    assert instagram_settings.route_for("-1001") is None
    assert await instagram_settings.get("-1001") is None
    assert await instagram_settings.reset("-1001") is False


def test_can_store_secrets_follows_the_repository(instagram_settings, database):
    from app.db.instagram_settings_repository import InstagramSettingsRepository
    from app.services.instagram_settings import InstagramSettingsService

    assert instagram_settings.can_store_secrets is True
    assert InstagramSettingsService(InstagramSettingsRepository(database, None)).can_store_secrets is False


async def test_route_follows_topic_changes(instagram_settings_repository, instagram_settings):
    configure_instagram(instagram_settings_repository, "-1001", trigger=["#a", "#b"])
    await instagram_settings.load()
    assert instagram_settings.route_for("-1001").hashtags == ("#a", "#b")
    assert instagram_settings.route_for("-1001").topic_id is None

    await instagram_settings.save_topic("-1001", 9, "Інстаграм", all_topics=False)
    assert instagram_settings.route_for("-1001").topic_id == 9

    await instagram_settings.save_topic("-1001", None, None, all_topics=True)
    assert instagram_settings.route_for("-1001").all_topics is True


async def test_clearing_tracked_hashtags_disables_the_chat(instagram_settings_repository, instagram_settings):
    configure_instagram(instagram_settings_repository, "-1001")
    await instagram_settings.load()

    await instagram_settings.save_trigger_hashtags("-1001", [])

    assert instagram_settings.route_for("-1001") is None
