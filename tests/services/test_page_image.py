import httpx
import pytest

from app.services import page_image
from app.services.page_image import PageImageError, PageImageFetcher, find_page_image, make_http_client

JPEG = b"\xff\xd8fake-jpeg"


def _fetcher(routes: dict) -> PageImageFetcher:
    """`routes[url] = (content type, body)`, or an int status code."""
    def handler(request):
        route = routes.get(str(request.url))
        if route is None:
            return httpx.Response(404)
        if isinstance(route, int):
            return httpx.Response(route)
        content_type, body = route
        return httpx.Response(200, headers={"content-type": content_type}, content=body)

    return PageImageFetcher(make_http_client(transport=httpx.MockTransport(handler)))


def test_find_page_image_prefers_og_image():
    html = """<html><head>
      <meta name="twitter:image" content="/tw.jpg">
      <meta content="/og.jpg" property="og:image">
    </head><body><img src="/first.jpg"></body></html>"""

    assert find_page_image(html, "https://site.example/news/1") == "https://site.example/og.jpg"


def test_find_page_image_falls_back_to_twitter_then_first_img():
    assert find_page_image('<meta name="twitter:image" content="t.jpg">', "https://s.example/a/") == "https://s.example/a/t.jpg"
    assert find_page_image('<p><img src="//cdn.example/1.png"><img src="2.png"></p>', "https://s.example/") == "https://cdn.example/1.png"


def test_find_page_image_none_or_non_http():
    assert find_page_image("<p>нічого</p>", "https://s.example/") is None
    assert find_page_image('<img src="data:image/png;base64,AAA">', "https://s.example/") is None


async def test_direct_image_link():
    fetcher = _fetcher({"https://img.example/a.jpg": ("image/jpeg", JPEG)})

    assert await fetcher.fetch_image("https://img.example/a.jpg") == JPEG


async def test_page_link_downloads_its_og_image():
    fetcher = _fetcher({
        "https://news.example/a": ("text/html; charset=utf-8", b'<meta property="og:image" content="/pic.jpg">'),
        "https://news.example/pic.jpg": ("image/jpeg", JPEG),
    })

    assert await fetcher.fetch_image("https://news.example/a") == JPEG


async def test_page_without_image_fails():
    fetcher = _fetcher({"https://news.example/a": ("text/html", b"<p>text</p>")})

    with pytest.raises(PageImageError, match="немає картинки"):
        await fetcher.fetch_image("https://news.example/a")


async def test_page_image_that_is_not_an_image_fails():
    fetcher = _fetcher({
        "https://news.example/a": ("text/html", b'<meta property="og:image" content="/pic">'),
        "https://news.example/pic": ("text/html", b"<p>"),
    })

    with pytest.raises(PageImageError, match="не є зображенням"):
        await fetcher.fetch_image("https://news.example/a")


async def test_other_content_types_fail():
    fetcher = _fetcher({"https://f.example/a.pdf": ("application/pdf", b"%PDF")})

    with pytest.raises(PageImageError, match="ні на картинку"):
        await fetcher.fetch_image("https://f.example/a.pdf")


async def test_http_error_fails():
    fetcher = _fetcher({"https://news.example/a": 500})

    with pytest.raises(PageImageError, match="HTTP 500"):
        await fetcher.fetch_image("https://news.example/a")


async def test_non_http_link_is_rejected():
    with pytest.raises(PageImageError):
        await _fetcher({}).fetch_image("ftp://x.example/a.jpg")


async def test_oversized_image_fails(monkeypatch):
    monkeypatch.setattr(page_image, "_MAX_IMAGE_BYTES", 4)
    fetcher = _fetcher({"https://img.example/a.jpg": ("image/jpeg", JPEG)})

    with pytest.raises(PageImageError, match="більша"):
        await fetcher.fetch_image("https://img.example/a.jpg")


async def test_large_page_is_cut_not_rejected(monkeypatch):
    monkeypatch.setattr(page_image, "_MAX_PAGE_BYTES", 60)
    head = b'<meta property="og:image" content="/pic.jpg">'
    fetcher = _fetcher({
        "https://news.example/a": ("text/html", head + b"x" * 1000),
        "https://news.example/pic.jpg": ("image/jpeg", JPEG),
    })

    assert await fetcher.fetch_image("https://news.example/a") == JPEG


async def test_network_error_fails():
    def handler(request):
        raise httpx.ConnectError("boom")

    fetcher = PageImageFetcher(make_http_client(transport=httpx.MockTransport(handler)))

    with pytest.raises(PageImageError, match="ConnectError"):
        await fetcher.fetch_image("https://news.example/a")
