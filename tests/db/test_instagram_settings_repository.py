import pytest

from app.db.instagram_settings_repository import InstagramSettingsRepository, SecretsUnavailableError
from app.services.secret_box import SecretBox, generate_key

CHAT = "-1001"
TOKEN = "EAAB-very-secret-token"
KEY_ID = "r2-access-key-id-123"
SECRET = "r2-secret-access-key-456"


def _configure(repository, chat_id=CHAT):
    repository.save_account(chat_id, "17841400000", "anikoe", "graph.facebook.com", TOKEN, "555")
    repository.save_r2(chat_id, "acc123", "bucket", "https://pub.example", KEY_ID, SECRET)
    repository.save_trigger_hashtags(chat_id, ["#Команда_AniKoe", "#anikoe_ig"])
    repository.save_extra_hashtags(chat_id, ["#аніме", "#анімеукраїна"])


def test_saves_and_reads_back_full_settings(instagram_settings_repository):
    _configure(instagram_settings_repository)

    settings = instagram_settings_repository.get(CHAT)

    assert settings.instagram_user_id == "17841400000"
    assert settings.instagram_username == "anikoe"
    assert settings.instagram_api_host == "graph.facebook.com"
    assert settings.instagram_token == TOKEN
    assert (settings.r2_account_id, settings.r2_bucket, settings.r2_public_base_url) == (
        "acc123", "bucket", "https://pub.example"
    )
    assert (settings.r2_access_key_id, settings.r2_secret_access_key) == (KEY_ID, SECRET)
    assert settings.trigger_hashtags == ["#Команда_AniKoe", "#anikoe_ig"]
    assert settings.extra_hashtags == ["#аніме", "#анімеукраїна"]
    assert settings.admin_user_id == "555"
    assert settings.is_ready and not settings.secrets_unreadable


def test_secrets_are_never_stored_in_plain_text(instagram_settings_repository, fake_db_handle):
    _configure(instagram_settings_repository)

    [doc] = fake_db_handle.instagram_settings.docs
    stored = repr(doc)
    for secret in (TOKEN, KEY_ID, SECRET):
        assert secret not in stored
    assert {"instagram_token", "r2_access_key_id", "r2_secret_access_key"}.isdisjoint(doc)
    assert doc["instagram_token_encrypted"].startswith("gAAAA")  # a Fernet token


def test_repr_of_settings_hides_secrets(instagram_settings_repository):
    _configure(instagram_settings_repository)

    shown = repr(instagram_settings_repository.get(CHAT))

    for secret in (TOKEN, KEY_ID, SECRET):
        assert secret not in shown
    assert "anikoe" in shown  # non-secret fields still help debugging


def test_ciphertext_moved_to_another_chat_is_unreadable(instagram_settings_repository, fake_db_handle):
    _configure(instagram_settings_repository, "-1001")
    _configure(instagram_settings_repository, "-1002")
    docs = {d["chat_id"]: d for d in fake_db_handle.instagram_settings.docs}
    docs["-1002"]["instagram_token_encrypted"] = docs["-1001"]["instagram_token_encrypted"]

    settings = instagram_settings_repository.get("-1002")

    assert settings.instagram_token is None
    assert settings.secrets_unreadable
    assert not settings.is_ready


def test_other_key_reads_secrets_as_unreadable(database, instagram_settings_repository):
    _configure(instagram_settings_repository)

    settings = InstagramSettingsRepository(database, SecretBox([generate_key()])).get(CHAT)

    assert settings.secrets_unreadable
    assert settings.instagram_token is None and settings.r2_secret_access_key is None
    assert settings.r2_bucket == "bucket"  # plain fields are still there
    assert not settings.is_ready


def test_without_a_key_secrets_cannot_be_saved_or_read(database, instagram_settings_repository):
    _configure(instagram_settings_repository)
    keyless = InstagramSettingsRepository(database, None)

    assert keyless.can_store_secrets is False
    with pytest.raises(SecretsUnavailableError):
        keyless.save_account("-1002", "1", "u", "graph.facebook.com", "t", "1")
    assert keyless.get(CHAT).secrets_unreadable
    # Non-secret settings still work.
    keyless.save_trigger_hashtags("-1002", ["#tag"])
    assert keyless.get("-1002").trigger_hashtags == ["#tag"]


def test_partial_settings_are_not_ready(instagram_settings_repository):
    instagram_settings_repository.save_trigger_hashtags(CHAT, ["#tag"])

    settings = instagram_settings_repository.get(CHAT)

    assert not settings.has_account and not settings.has_r2
    assert not settings.is_ready
    assert settings.extra_hashtags == []


def test_saving_again_updates_in_place(instagram_settings_repository, fake_db_handle):
    _configure(instagram_settings_repository)
    instagram_settings_repository.save_account(CHAT, "999", "other", "graph.instagram.com", "IGAA-new", "777")

    settings = instagram_settings_repository.get(CHAT)

    assert len(fake_db_handle.instagram_settings.docs) == 1
    assert (settings.instagram_user_id, settings.instagram_token, settings.admin_user_id) == ("999", "IGAA-new", "777")
    assert settings.r2_bucket == "bucket"  # untouched


def test_get_all_and_delete(instagram_settings_repository):
    _configure(instagram_settings_repository, "-1001")
    _configure(instagram_settings_repository, "-1002")

    assert {s.chat_id for s in instagram_settings_repository.get_all()} == {"-1001", "-1002"}
    assert instagram_settings_repository.delete("-1001") is True
    assert instagram_settings_repository.delete("-1001") is False
    assert instagram_settings_repository.get("-1001") is None


def test_ensure_indexes(instagram_settings_repository, fake_db_handle):
    instagram_settings_repository.ensure_indexes()

    assert fake_db_handle.instagram_settings.indexes == [[("chat_id", 1)]]


def test_topic_settings(instagram_settings_repository):
    instagram_settings_repository.save_topic(CHAT, 9, "Інстаграм", all_topics=False)
    settings = instagram_settings_repository.get(CHAT)
    assert (settings.instagram_topic_id, settings.instagram_topic_name, settings.instagram_all_topics) == (
        9, "Інстаграм", False
    )

    instagram_settings_repository.save_topic(CHAT, None, None, all_topics=True)
    settings = instagram_settings_repository.get(CHAT)
    assert (settings.instagram_topic_id, settings.instagram_topic_name, settings.instagram_all_topics) == (
        None, None, True
    )


def test_defaults_follow_the_news_topic(instagram_settings_repository):
    _configure(instagram_settings_repository)

    settings = instagram_settings_repository.get(CHAT)

    assert settings.instagram_topic_id is None and settings.instagram_all_topics is False


def test_reads_a_single_legacy_trigger_hashtag(instagram_settings_repository, fake_db_handle):
    fake_db_handle.instagram_settings.insert_one({"chat_id": CHAT, "trigger_hashtag": "#Команда_AniKoe"})

    assert instagram_settings_repository.get(CHAT).trigger_hashtags == ["#Команда_AniKoe"]
