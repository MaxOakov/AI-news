import pytest


def test_chats_without_a_choice_use_the_default(model_settings):
    assert model_settings.default == "fake-model"
    assert model_settings.chat_choice("1") is None
    assert model_settings.model_for_chat("1") == "fake-model"
    assert model_settings.model_for_chat(None) == "fake-model"


def test_each_chat_keeps_its_own_model(model_settings, fake_db_handle):
    model_settings.set_for_chat("1", "other-model")

    assert model_settings.model_for_chat("1") == "other-model"
    assert model_settings.model_for_chat(1) == "other-model"  # ids are normalized to str
    assert model_settings.model_for_chat("2") == "fake-model"
    [doc] = fake_db_handle.chat_models.docs
    assert (doc["chat_id"], doc["model"]) == ("1", "other-model")


def test_changing_the_model_again_updates_in_place(model_settings, fake_db_handle):
    model_settings.set_for_chat("1", "other-model")
    model_settings.set_for_chat("1", "fake-model")

    assert len(fake_db_handle.chat_models.docs) == 1
    assert model_settings.chat_choice("1") == "fake-model"


def test_reset_goes_back_to_the_default(model_settings):
    model_settings.set_for_chat("1", "other-model")

    model_settings.reset_for_chat("1")

    assert model_settings.chat_choice("1") is None
    assert model_settings.model_for_chat("1") == "fake-model"


def test_unknown_model_is_rejected(model_settings, fake_db_handle):
    with pytest.raises(ValueError):
        model_settings.set_for_chat("1", "nope")
    assert fake_db_handle.chat_models.docs == []


def test_stored_model_that_is_no_longer_an_option_falls_back(model_settings, chat_model_repository):
    chat_model_repository.save("1", "retired-model")

    assert model_settings.chat_choice("1") is None
    assert model_settings.model_for_chat("1") == "fake-model"


def test_db_error_falls_back_to_the_default(model_settings, chat_model_repository, monkeypatch):
    def boom(chat_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(chat_model_repository, "get", boom)

    assert model_settings.model_for_chat("1") == "fake-model"


async def test_generator_uses_the_chats_model(
    model_settings, news_generator, fake_genai_client, sample_article, prompt_repository
):
    fake_genai_client.set_response("ok")
    model_settings.set_for_chat("1", "other-model")

    await news_generator.generate(sample_article, chat_id="1")
    await news_generator.generate(sample_article, chat_id="2")

    assert [model for model, _ in fake_genai_client.calls] == ["other-model", "fake-model"]
