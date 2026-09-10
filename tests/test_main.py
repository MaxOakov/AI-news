from app.bot_commands import BotCommands
from app.scheduler import SchedulerService
from app.telegram_bot import TelegramBot


def test_build_app_returns_wired_object_graph(monkeypatch):
    monkeypatch.setattr("main.TELEGRAM_TOKEN", "")
    monkeypatch.setattr("main.MONGODB_URL", None)
    monkeypatch.setattr("main.GEMINI_MODEL", "fake-model")
    monkeypatch.setattr("app.services.news_generator.genai.Client", lambda: object())

    import main

    telegram_bot, scheduler_service, bot_commands = main.build_app()

    assert isinstance(telegram_bot, TelegramBot)
    assert isinstance(scheduler_service, SchedulerService)
    assert isinstance(bot_commands, BotCommands)

    # composition-root wiring: everyone shares the exact same instances
    assert scheduler_service._pipeline._telegram_bot is telegram_bot
    assert bot_commands._telegram_bot is telegram_bot
    assert bot_commands._scheduler_service is scheduler_service


def test_build_app_does_not_connect_to_mongo_when_url_missing(monkeypatch):
    monkeypatch.setattr("main.TELEGRAM_TOKEN", "")
    monkeypatch.setattr("main.MONGODB_URL", None)
    monkeypatch.setattr("main.GEMINI_MODEL", "fake-model")
    monkeypatch.setattr("app.services.news_generator.genai.Client", lambda: object())

    import main

    # Must not raise: Database.get_db() is lazy and never called during
    # construction, only when a repository method actually runs.
    main.build_app()
