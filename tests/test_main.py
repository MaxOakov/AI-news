import pytest

from app.bot_commands import BotCommands
from app.instagram_forwarder import InstagramForwarder
from app.scheduler import SchedulerService
from app.services.secret_box import generate_key
from app.setup_commands import SetupCommands
from app.telegram_bot import TelegramBot


@pytest.fixture
def main_module(monkeypatch):
    monkeypatch.setattr("main.TELEGRAM_TOKEN", "")
    monkeypatch.setattr("main.MONGODB_URL", None)
    monkeypatch.setattr("main.GEMINI_MODEL", "fake-model")
    monkeypatch.setattr("main.SECRETS_ENCRYPTION_KEY", generate_key())
    monkeypatch.setattr("app.services.news_generator.genai.Client", lambda: object())

    import main

    return main


def test_build_app_returns_wired_object_graph(main_module):
    app = main_module.build_app()
    telegram_bot, scheduler_service, bot_commands = app.telegram_bot, app.scheduler_service, app.bot_commands

    assert isinstance(telegram_bot, TelegramBot)
    assert isinstance(scheduler_service, SchedulerService)
    assert isinstance(bot_commands, BotCommands)
    assert isinstance(app.setup_commands, SetupCommands)
    assert isinstance(app.instagram_forwarder, InstagramForwarder)

    # composition-root wiring: everyone shares the exact same instances
    assert scheduler_service._pipeline._telegram_bot is telegram_bot
    assert bot_commands._telegram_bot is telegram_bot
    assert bot_commands._scheduler_service is scheduler_service
    assert scheduler_service._pipeline._articles is app.article_repository
    assert scheduler_service._pipeline._publisher is bot_commands._publisher
    assert app.article_repository._max_article_age is not None  # queue age limit is wired in
    # The per-chat model the commands change is the one generation reads.
    assert scheduler_service._pipeline._news_generator._models is bot_commands._model_settings
    assert bot_commands._model_settings.default == "fake-model"

    # Instagram: one settings service shared by the commands that change it
    # and the forwarder that reads it; the publisher hands posts to the forwarder.
    assert bot_commands._setup_commands is app.setup_commands
    assert app.setup_commands._settings is app.instagram_settings
    assert app.instagram_forwarder._settings is app.instagram_settings
    assert app.setup_commands._connector is app.instagram_forwarder._connector
    assert bot_commands._publisher._instagram_forwarder is app.instagram_forwarder
    assert app.instagram_forwarder._telegram_bot is telegram_bot
    assert app.instagram_settings.can_store_secrets is True


def test_build_app_does_not_connect_to_mongo_when_url_missing(main_module):
    # Must not raise: Database.get_db() is lazy and never called during
    # construction, only when a repository method actually runs.
    main_module.build_app()


@pytest.mark.parametrize("key", [None, "", "not-a-fernet-key"])
def test_missing_or_bad_encryption_key_leaves_the_bot_working(main_module, monkeypatch, key):
    monkeypatch.setattr("main.SECRETS_ENCRYPTION_KEY", key)

    app = main_module.build_app()

    assert app.instagram_settings.can_store_secrets is False
    assert isinstance(app.bot_commands, BotCommands)


def test_secret_box_accepts_several_keys_for_rotation(main_module):
    assert main_module.build_secret_box(f"{generate_key()}, {generate_key()}") is not None
