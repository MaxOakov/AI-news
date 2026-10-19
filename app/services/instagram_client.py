"""Publishing photos through the Instagram Graph API (Content Publishing).

A post is published in two steps: create a media container from a public
image URL (Instagram downloads the image itself), wait until Instagram has
processed it, then publish the container. A carousel is one container per
photo plus a CAROUSEL container listing them as children.
"""
import asyncio
import time

import httpx

from app.retry import retry_async

MAX_CAROUSEL_ITEMS = 10
_REQUEST_TIMEOUT_SECONDS = 30


class InstagramError(Exception):
    """The Graph API refused a request, or a container failed processing."""


def make_http_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """The HTTP client the Graph API is called with. `transport` is for tests."""
    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS, transport=transport)


class InstagramClient:
    def __init__(
        self,
        user_id: str,
        access_token: str,
        base_url: str,
        http_client: httpx.AsyncClient | None = None,
        poll_interval: float = 3,
        poll_timeout: float = 120,
    ):
        self._user_id = user_id
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")
        self._http = http_client or make_http_client()
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    async def get_username(self) -> str:
        """The account's username; doubles as a check that the token works
        for this account."""
        result = await self._request("GET", None, {"fields": "username"})
        if not result.get("username"):
            raise InstagramError("Instagram не повернув ім'я акаунта")
        return result["username"]

    async def publish_photos(self, image_urls: list[str], caption: str) -> str:
        """Publish one photo, or a carousel of 2–10, and return the new
        post's Instagram media id."""
        if not image_urls:
            raise ValueError("немає фото для публікації")
        image_urls = image_urls[:MAX_CAROUSEL_ITEMS]

        if len(image_urls) == 1:
            container_id = await self._create_container(image_url=image_urls[0], caption=caption)
        else:
            children = []
            for url in image_urls:
                child_id = await self._create_container(image_url=url, is_carousel_item="true")
                await self._wait_until_ready(child_id)
                children.append(child_id)
            container_id = await self._create_container(
                media_type="CAROUSEL", children=",".join(children), caption=caption
            )

        await self._wait_until_ready(container_id)
        result = await self._request("POST", "media_publish", {"creation_id": container_id})
        return result["id"]

    async def _create_container(self, **fields) -> str:
        result = await self._request("POST", "media", fields)
        return result["id"]

    async def _wait_until_ready(self, container_id: str):
        deadline = time.monotonic() + self._poll_timeout
        while True:
            result = await self._request("GET", None, {"fields": "status_code,status"}, node=container_id)
            status = result.get("status_code")
            if status in ("FINISHED", "PUBLISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"контейнер {container_id}: {status} {result.get('status', '')}".strip())
            if time.monotonic() > deadline:
                raise InstagramError(f"контейнер {container_id} не оброблено за {self._poll_timeout} с")
            await asyncio.sleep(self._poll_interval)

    @retry_async(
        max_retries=3,
        delay=2,
        exceptions=(httpx.TransportError,),
        on_retry=lambda exc, attempt, total, *a, **kw: print(
            f"⚠️ Помилка зв'язку з Instagram (спроба {attempt}/{total}): {type(exc).__name__}"
        ),
    )
    async def _send(self, method: str, url: str, fields: dict) -> httpx.Response:
        # The token travels in the body/query, never in a log line: errors
        # are reported from the API's JSON, not from httpx (whose messages
        # include the full URL).
        fields = {**fields, "access_token": self._access_token}
        if method == "GET":
            return await self._http.get(url, params=fields)
        return await self._http.post(url, data=fields)

    async def _request(self, method: str, edge: str | None, fields: dict, node: str | None = None) -> dict:
        url = f"{self._base_url}/{node or self._user_id}"
        if edge:
            url = f"{url}/{edge}"
        try:
            response = await self._send(method, url, fields)
        except httpx.TransportError as exc:
            raise InstagramError(f"немає зв'язку з Instagram: {type(exc).__name__}") from None

        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.is_error or "error" in body:
            error = body.get("error") or {}
            message = error.get("message") or f"HTTP {response.status_code}"
            raise InstagramError(message)
        return body
