from urllib.parse import parse_qs

import httpx
import pytest

from app.models import InstagramSettings
from app.services.image_host import ImageHostError
from app.services.instagram_client import InstagramError, make_http_client
from app.services.instagram_connector import InstagramConnector
from tests.services.test_image_host import FakeS3


def _connector(handler, r2_client_factory=None):
    http = make_http_client(transport=httpx.MockTransport(handler))
    kwargs = {"r2_client_factory": r2_client_factory} if r2_client_factory else {}
    return InstagramConnector("v23.0", http_client=http, **kwargs)


def _graph(valid_on: str, username="anikoe"):
    """A Graph API that accepts the token only on host `valid_on`."""
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host != valid_on:
            return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token", "code": 190}})
        assert request.url.path == "/v23.0/1784"
        assert parse_qs(request.url.query.decode())["fields"] == ["username"]
        return httpx.Response(200, json={"username": username, "id": "1784"})

    return handler, calls


async def test_facebook_login_token_works_on_graph_facebook():
    handler, calls = _graph("graph.facebook.com")

    check = await _connector(handler).check_account("1784", "EAAB-token")

    assert (check.username, check.api_host) == ("anikoe", "graph.facebook.com")
    assert calls == ["graph.facebook.com"]


async def test_instagram_login_token_tries_graph_instagram_first():
    handler, calls = _graph("graph.instagram.com")

    check = await _connector(handler).check_account("1784", "IGAA-token")

    assert check.api_host == "graph.instagram.com"
    assert calls == ["graph.instagram.com"]


async def test_falls_back_to_the_other_host():
    handler, calls = _graph("graph.instagram.com")

    check = await _connector(handler).check_account("1784", "EAAB-token")

    assert check.api_host == "graph.instagram.com"
    assert calls == ["graph.facebook.com", "graph.instagram.com"]


async def test_reports_the_first_hosts_error_when_neither_works():
    handler, _ = _graph("nowhere.example")

    with pytest.raises(InstagramError, match="Invalid OAuth access token"):
        await _connector(handler).check_account("1784", "EAAB-token")


def test_clients_are_built_from_the_chats_settings():
    built = []

    def r2_factory(account_id, key_id, secret):
        built.append((account_id, key_id, secret))
        return FakeS3()

    connector = _connector(lambda request: httpx.Response(500), r2_factory)
    settings = InstagramSettings(
        chat_id="-1001", instagram_user_id="1784", instagram_api_host="graph.instagram.com",
        instagram_token="IGAA", r2_account_id="acc", r2_bucket="bucket",
        r2_public_base_url="https://pub.example", r2_access_key_id="id", r2_secret_access_key="secret",
    )

    client = connector.instagram_client(settings)
    host = connector.image_host(settings)

    assert client._base_url == "https://graph.instagram.com/v23.0"
    assert (client._user_id, client._access_token) == ("1784", "IGAA")
    assert built == [("acc", "id", "secret")]
    assert host.upload("k.jpg", b"x") == "https://pub.example/k.jpg"


async def test_check_r2_uploads_fetches_publicly_and_cleans_up():
    s3 = FakeS3()
    fetched = []

    def handler(request):
        fetched.append(str(request.url))
        key = request.url.path.lstrip("/")
        return httpx.Response(200, content=s3.objects[key])

    connector = _connector(handler, lambda *creds: s3)

    await connector.check_r2("acc", "id", "secret", "bucket", "https://pub.example")

    assert len(fetched) == 1 and fetched[0].startswith("https://pub.example/instagram/_check-")
    assert s3.objects == {}  # the check file was deleted


async def test_check_r2_reports_bad_client_settings():
    def broken_factory(*creds):
        raise ValueError("Invalid endpoint")

    with pytest.raises(ImageHostError, match="некоректні дані R2"):
        await _connector(lambda r: httpx.Response(200), broken_factory).check_r2("a b", "id", "s", "b", "https://p")
