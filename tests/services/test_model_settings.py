import os

import pytest

from app.services.model_settings import update_gemini_model_in_env


@pytest.fixture(autouse=True)
def restore_environ(monkeypatch):
    # set_model writes os.environ; monkeypatch undoes it after each test
    monkeypatch.delenv("GEMINI_MODEL", raising=False)


# --------------------------------------------------------------------------
# update_gemini_model_in_env
# --------------------------------------------------------------------------
def test_update_env_creates_missing_file(env_path):
    update_gemini_model_in_env(env_path, "m1")
    assert env_path.read_text(encoding="utf-8") == "GEMINI_MODEL=m1\n"


def test_update_env_replaces_existing_key_and_keeps_other_lines(env_path):
    env_path.write_text("TELEGRAM_TOKEN=abc\nGEMINI_MODEL=old\nMONGODB_URL=x\n", encoding="utf-8")

    update_gemini_model_in_env(env_path, "new")

    assert env_path.read_text(encoding="utf-8").splitlines() == [
        "TELEGRAM_TOKEN=abc", "GEMINI_MODEL=new", "MONGODB_URL=x",
    ]


def test_update_env_appends_key_when_absent(env_path):
    env_path.write_text("TELEGRAM_TOKEN=abc\n", encoding="utf-8")
    update_gemini_model_in_env(env_path, "m1")
    assert env_path.read_text(encoding="utf-8").splitlines() == ["TELEGRAM_TOKEN=abc", "GEMINI_MODEL=m1"]


def test_update_env_collapses_duplicate_keys(env_path):
    env_path.write_text("GEMINI_MODEL=a\nX=1\nGEMINI_MODEL=b\n", encoding="utf-8")
    update_gemini_model_in_env(env_path, "c")
    assert env_path.read_text(encoding="utf-8").splitlines() == ["GEMINI_MODEL=c", "X=1"]


# --------------------------------------------------------------------------
# GeminiModelSettings
# --------------------------------------------------------------------------
def test_current_reflects_generator_model(model_settings):
    assert model_settings.current == "fake-model"


def test_set_model_applies_to_generator_env_and_file(model_settings, news_generator, env_path):
    model_settings.set_model("other-model")

    assert news_generator.model == "other-model"
    assert model_settings.current == "other-model"
    assert os.environ["GEMINI_MODEL"] == "other-model"
    assert "GEMINI_MODEL=other-model" in env_path.read_text(encoding="utf-8")


def test_set_model_rejects_unknown_model(model_settings, news_generator, env_path):
    with pytest.raises(ValueError):
        model_settings.set_model("nope")
    assert news_generator.model == "fake-model"
    assert not env_path.exists()


def test_set_model_io_failure_leaves_running_model_unchanged(model_settings, news_generator, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("read-only fs")

    monkeypatch.setattr("app.services.model_settings.update_gemini_model_in_env", boom)

    with pytest.raises(OSError):
        model_settings.set_model("other-model")
    assert news_generator.model == "fake-model"
    assert "GEMINI_MODEL" not in os.environ


async def test_generator_uses_switched_model(
    model_settings, news_generator, fake_genai_client, sample_article, prompt_repository
):
    prompt_repository.save_custom("1", "{title} {summary} {url}")
    fake_genai_client.set_response("ok")
    model_settings.set_model("other-model")

    await news_generator.generate(sample_article, chat_id="1")

    model, _ = fake_genai_client.calls[0]
    assert model == "other-model"
