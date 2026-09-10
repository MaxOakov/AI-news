import pytest

from app.db.database import Database


def test_get_db_raises_when_url_not_configured():
    db = Database(url=None)
    with pytest.raises(RuntimeError, match="MONGODB_URL is not configured"):
        db.get_db()


def test_construction_does_not_touch_mongo_client(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("MongoClient should not be constructed eagerly")

    monkeypatch.setattr("app.db.database.MongoClient", boom)
    Database(url="mongodb://example")  # should not raise


def test_get_db_returns_preset_db_without_connecting(monkeypatch, fake_db_handle):
    def boom(*a, **k):
        raise AssertionError("MongoClient should not be constructed when _db is preset")

    monkeypatch.setattr("app.db.database.MongoClient", boom)
    db = Database(url="mongodb://example")
    db._db = fake_db_handle

    assert db.get_db() is fake_db_handle


def test_connection_failure_raises_runtime_error(monkeypatch):
    class FailingAdmin:
        def command(self, cmd):
            raise RuntimeError("no server")

    class FailingClient:
        def __init__(self, *a, **k):
            self.admin = FailingAdmin()

    monkeypatch.setattr("app.db.database.MongoClient", FailingClient)
    db = Database(url="mongodb://example")
    with pytest.raises(RuntimeError, match="MongoDB connection failed"):
        db.get_db()


def test_successful_connection_pings_and_caches_db(monkeypatch):
    pinged = []

    class SuccessfulAdmin:
        def command(self, cmd):
            pinged.append(cmd)

    class SuccessfulClient:
        def __init__(self, *a, **k):
            self.admin = SuccessfulAdmin()

        def __getitem__(self, name):
            return f"db-handle-for-{name}"

    monkeypatch.setattr("app.db.database.MongoClient", SuccessfulClient)
    db = Database(url="mongodb://example")

    result = db.get_db()

    assert pinged == ["ping"]
    assert result == "db-handle-for-news"
    assert db.get_db() is result  # second call reuses the cached handle


def test_collection_properties_proxy_to_db_handle(database, fake_db_handle):
    assert database.articles is fake_db_handle.articles
    assert database.chats is fake_db_handle.chats
    assert database.rss_links is fake_db_handle.rss_links
    assert database.chat_prompts is fake_db_handle.chat_prompts
