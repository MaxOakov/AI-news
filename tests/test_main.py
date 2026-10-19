from app.bot_commands import BotCommands
from app.instagram_forwarder import InstagramForwarder
from app.scheduler import SchedulerService
from app.telegram_bot import TelegramBot


def test_build_app_returns_wired_object_graph(monkeypatch):
    monkeypatch.setattr("main.TELEGRAM_TOKEN", "")
    monkeypatch.setattr("main.MONGODB_URL", None)
    monkeypatch.setattr("main.GEMINI_MODEL", "fake-model")
    monkeypatch.setattr("app.services.news_generator.genai.Client", lambda: object())

    import main

    telegram_bot, scheduler_service, bot_commands, article_repository, instagram_forwarder = main.build_app()

    assert isinstance(telegram_bot, TelegramBot)
    assert isinstance(scheduler_service, SchedulerService)
    assert isinstance(bot_commands, BotCommands)

    # composition-root wiring: everyone shares the exact same instances
    assert scheduler_service._pipeline._telegram_bot is telegram_bot
    assert bot_commands._telegram_bot is telegram_bot
    assert bot_commands._scheduler_service is scheduler_service
    assert scheduler_service._pipeline._articles is article_repository
    assert scheduler_service._pipeline._publisher is bot_commands._publisher
    assert article_repository._max_article_age is not None  # queue age limit is wired in


def test_build_app_does_not_connect_to_mongo_when_url_missing(monkeypatch):
    monkeypatch.setattr("main.TELEGRAM_TOKEN", "")
    monkeypatch.setattr("main.MONGODB_URL", None)
    monkeypatch.setattr("main.GEMINI_MODEL", "fake-model")
    monkeypatch.setattr("app.services.news_generator.genai.Client", lambda: object())

    import main

    # Must not raise: Database.get_db() is lazy and never called during
    # construction, only when a repository method actually runs.
    main.build_app()


def test_build_app_without_instagram_settings_has_no_forwarder(monkeypatch):
    monkeypatch.setattr("main.TELEGRAM_TOKEN", "")
    monkeypatch.setattr("main.MONGODB_URL", None)
    monkeypatch.setattr("main.GEMINI_MODEL", "fake-model")
    monkeypatch.setattr("app.services.news_generator.genai.Client", lambda: object())
    monkeypatch.setattr("app.config.INSTAGRAM_ACCESS_TOKEN", None)

    import main

    assert main.build_app()[4] is None


def test_build_app_wires_instagram_forwarder_when_configured(monkeypatch):
    monkeypatch.setattr("main.TELEGRAM_TOKEN", "")
    monkeypatch.setattr("main.MONGODB_URL", None)
    monkeypatch.setattr("main.GEMINI_MODEL", "fake-model")
    monkeypatch.setattr("app.services.news_generator.genai.Client", lambda: object())
    for name in (
        "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY", "R2_BUCKET",
    ):
        monkeypatch.setattr(f"app.config.{name}", "x")
    monkeypatch.setattr("app.config.INSTAGRAM_SOURCE_CHAT_ID", "-1001")
    monkeypatch.setattr("app.config.INSTAGRAM_SOURCE_THREAD_ID", 7)
    monkeypatch.setattr("app.config.R2_PUBLIC_BASE_URL", "https://pub.example")

    import main

    telegram_bot, _, bot_commands, _, instagram_forwarder = main.build_app()

    assert isinstance(instagram_forwarder, InstagramForwarder)
    assert instagram_forwarder._telegram_bot is telegram_bot
    assert instagram_forwarder._source_chat_id == "-1001"
    assert instagram_forwarder._source_thread_id == 7
    assert bot_commands._publisher._instagram_forwarder is instagram_forwarder
