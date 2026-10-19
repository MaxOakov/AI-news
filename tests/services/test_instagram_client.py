from urllib.parse import parse_qs

import httpx
import pytest

from app.services.instagram_client import InstagramClient, InstagramError, make_http_client

BASE = "https://graph.example/v23.0"


class FakeGraphApi:
    """Just enough of the Graph API's content-publishing endpoints."""

    def __init__(self, statuses=None):
        self.requests: list[tuple[str, str, dict]] = []
        self._next_id = 1
        # Status_code answers per container, consumed one per poll.
        self._statuses = statuses or {}
        self.fail_with: tuple[int, dict] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            fields = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        else:
            fields = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        path = request.url.path.removeprefix("/v23.0/")
        self.requests.append((request.method, path, fields))

        if self.fail_with:
            status, body = self.fail_with
            return httpx.Response(status, json=body)
        if path == "ig-user/media":
            container_id = f"c{self._next_id}"
            self._next_id += 1
            return httpx.Response(200, json={"id": container_id})
        if path == "ig-user/media_publish":
            return httpx.Response(200, json={"id": "media-1"})
        queue = self._statuses.get(path, [])
        return httpx.Response(200, json={"status_code": queue.pop(0) if queue else "FINISHED"})

    def posts(self, path):
        return [fields for method, p, fields in self.requests if method == "POST" and p == path]


def _client(api: FakeGraphApi, **kwargs) -> InstagramClient:
    http = make_http_client(transport=httpx.MockTransport(api.handler))
    return InstagramClient("ig-user", "secret-token", BASE, http_client=http, poll_interval=0, **kwargs)


async def test_publishes_single_photo():
    api = FakeGraphApi()

    media_id = await _client(api).publish_photos(["https://img/1.jpg"], "Підпис #аніме")

    assert media_id == "media-1"
    assert api.posts("ig-user/media") == [
        {"image_url": "https://img/1.jpg", "caption": "Підпис #аніме", "access_token": "secret-token"}
    ]
    assert api.posts("ig-user/media_publish") == [{"creation_id": "c1", "access_token": "secret-token"}]


async def test_publishes_carousel():
    api = FakeGraphApi()

    await _client(api).publish_photos(["https://img/1.jpg", "https://img/2.jpg"], "Підпис")

    children, parent = api.posts("ig-user/media")[:2], api.posts("ig-user/media")[2]
    assert [c["is_carousel_item"] for c in children] == ["true", "true"]
    assert all("caption" not in c for c in children)
    assert parent["media_type"] == "CAROUSEL"
    assert parent["children"] == "c1,c2"
    assert parent["caption"] == "Підпис"
    assert api.posts("ig-user/media_publish")[0]["creation_id"] == "c3"


async def test_waits_until_container_is_finished():
    api = FakeGraphApi(statuses={"c1": ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]})

    await _client(api).publish_photos(["https://img/1.jpg"], "x")

    polls = [r for r in api.requests if r[0] == "GET" and r[1] == "c1"]
    assert len(polls) == 3
    assert api.posts("ig-user/media_publish")


async def test_container_error_raises_and_does_not_publish():
    api = FakeGraphApi(statuses={"c1": ["ERROR"]})

    with pytest.raises(InstagramError, match="ERROR"):
        await _client(api).publish_photos(["https://img/1.jpg"], "x")
    assert not api.posts("ig-user/media_publish")


async def test_container_that_never_finishes_times_out():
    api = FakeGraphApi(statuses={"c1": ["IN_PROGRESS"] * 1000})

    with pytest.raises(InstagramError, match="не оброблено"):
        await _client(api, poll_timeout=-1).publish_photos(["https://img/1.jpg"], "x")


async def test_api_error_message_is_reported_without_token():
    api = FakeGraphApi()
    api.fail_with = (400, {"error": {"message": "Invalid image URL", "code": 9004}})

    with pytest.raises(InstagramError) as info:
        await _client(api).publish_photos(["https://img/1.jpg"], "x")
    assert str(info.value) == "Invalid image URL"
    assert "secret-token" not in str(info.value)


async def test_network_errors_are_retried_then_reported():
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ConnectError("boom https://graph.example/?access_token=secret-token")

    http = make_http_client(transport=httpx.MockTransport(handler))
    client = InstagramClient("ig-user", "secret-token", BASE, http_client=http)

    with pytest.raises(InstagramError) as info:
        await client.publish_photos(["https://img/1.jpg"], "x")
    assert len(attempts) == 3
    assert "secret-token" not in str(info.value)


async def test_rejects_empty_photo_list():
    with pytest.raises(ValueError):
        await _client(FakeGraphApi()).publish_photos([], "x")
