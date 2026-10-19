"""Getting the picture behind a link, the way a Telegram link preview does.

A link either points straight at an image, or at a page: then it's the
page's og:image (what Telegram shows in the preview), else twitter:image,
else the page's first <img>.
"""
import time
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

_TIMEOUT_SECONDS = 20
_MAX_IMAGE_BYTES = 15 * 1024 * 1024
_MAX_PAGE_BYTES = 2 * 1024 * 1024
_USER_AGENT = "Mozilla/5.0 (compatible; AI-news-bot/1.0)"


class PageImageError(Exception):
    """No usable image behind the link."""


def make_http_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """The HTTP client pages and images are downloaded with. `transport` is for tests."""
    return httpx.AsyncClient(
        timeout=_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
        transport=transport,
    )


class _ImageFinder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.og_image = None
        self.twitter_image = None
        self.first_img = None

    def handle_starttag(self, tag, attrs):
        attrs = {name.lower(): value for name, value in attrs if value}
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            content = attrs.get("content")
            if key in ("og:image", "og:image:url", "og:image:secure_url") and not self.og_image:
                self.og_image = content
            elif key in ("twitter:image", "twitter:image:src") and not self.twitter_image:
                self.twitter_image = content
        elif tag == "img" and not self.first_img:
            self.first_img = attrs.get("src")


def find_page_image(html_text: str, base_url: str) -> str | None:
    """The URL of the image a page offers for previews, made absolute."""
    finder = _ImageFinder()
    finder.feed(html_text)
    url = finder.og_image or finder.twitter_image or finder.first_img
    if not url:
        return None
    url = urljoin(base_url, url.strip())
    return url if url.startswith(("http://", "https://")) else None


class PageImageFetcher:
    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._http = http_client or make_http_client()

    async def fetch_image(self, url: str) -> bytes:
        """Download the image `url` points at, or the preview image of the
        page it points at."""
        if not url.startswith(("http://", "https://")):
            raise PageImageError(f"непідтримуване посилання: {url}")

        content_type, body, final_url = await self._download(url)
        if content_type.startswith("image/"):
            return body
        if "html" not in content_type:
            raise PageImageError(f"посилання не веде ні на картинку, ні на сторінку ({content_type or 'без типу'})")

        image_url = find_page_image(body.decode("utf-8", errors="replace"), final_url)
        if image_url is None:
            raise PageImageError("на сторінці немає картинки")
        content_type, body, _ = await self._download(image_url)
        if not content_type.startswith("image/"):
            raise PageImageError(f"картинка сторінки не є зображенням ({content_type or 'без типу'})")
        return body

    async def _download(self, url: str):
        """(content type, body, final URL after redirects). An image larger
        than _MAX_IMAGE_BYTES is an error; anything else is just cut at
        _MAX_PAGE_BYTES (a page's <head>, where og:image lives, comes first)."""
        deadline = time.monotonic() + _TIMEOUT_SECONDS
        chunks, size = [], 0
        try:
            async with self._http.stream("GET", url) as response:
                if response.is_error:
                    raise PageImageError(f"HTTP {response.status_code} для {url}")
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                is_image = content_type.startswith("image/")
                max_bytes = _MAX_IMAGE_BYTES if is_image else _MAX_PAGE_BYTES
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        if not is_image:
                            chunks.append(chunk[: len(chunk) - (size - max_bytes)])
                            break
                        raise PageImageError(f"картинка більша за {max_bytes} байт")
                    if time.monotonic() > deadline:
                        raise PageImageError(f"завантаження довше за {_TIMEOUT_SECONDS} с")
                    chunks.append(chunk)
                final_url = str(response.url)
        except httpx.HTTPError as exc:
            raise PageImageError(f"не вдалося завантажити {url}: {type(exc).__name__}") from None
        return content_type, b"".join(chunks), final_url
