import httpx
import pytest

from app.services.image_host import ImageHostError, R2ImageHost, describe_storage_error


class FakeS3:
    """Just the boto3 S3 client calls R2ImageHost makes, over a dict."""

    def __init__(self, fail_put_with=None):
        self.calls = []
        self.objects: dict[str, bytes] = {}
        self._fail_put_with = fail_put_with

    def put_object(self, **kwargs):
        self.calls.append(("put", kwargs))
        if self._fail_put_with is not None:
            raise self._fail_put_with
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs))
        self.objects.pop(kwargs["Key"], None)


class FakeClientError(Exception):
    """Shaped like botocore's ClientError."""

    def __init__(self, code, message):
        super().__init__(f"An error occurred ({code})")
        self.response = {"Error": {"Code": code, "Message": message}}


def _http(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_upload_returns_public_url_and_delete_removes_object():
    s3 = FakeS3()
    host = R2ImageHost(s3, "bucket", "https://pub.example/")

    url = host.upload("instagram/a.jpg", b"jpeg")
    host.delete("instagram/a.jpg")

    assert url == "https://pub.example/instagram/a.jpg"
    assert s3.calls == [
        ("put", {"Bucket": "bucket", "Key": "instagram/a.jpg", "Body": b"jpeg", "ContentType": "image/jpeg"}),
        ("delete", {"Bucket": "bucket", "Key": "instagram/a.jpg"}),
    ]


async def test_check_public_access_passes_when_the_file_is_served():
    s3 = FakeS3()
    host = R2ImageHost(s3, "bucket", "https://pub.example")

    await host.check_public_access(_http(lambda r: httpx.Response(200, content=s3.objects[r.url.path.lstrip("/")])))

    assert [c[0] for c in s3.calls] == ["put", "delete"]


async def test_check_public_access_fails_without_public_access():
    s3 = FakeS3()
    host = R2ImageHost(s3, "bucket", "https://pub.example")

    with pytest.raises(ImageHostError, match="HTTP 404"):
        await host.check_public_access(_http(lambda r: httpx.Response(404)))
    assert s3.objects == {}  # still cleaned up


async def test_check_public_access_fails_when_url_serves_something_else():
    host = R2ImageHost(FakeS3(), "bucket", "https://pub.example")

    with pytest.raises(ImageHostError, match="публічним URL"):
        await host.check_public_access(_http(lambda r: httpx.Response(200, content=b"<html>parked domain</html>")))


async def test_check_public_access_reports_storage_error_code():
    s3 = FakeS3(fail_put_with=FakeClientError("InvalidAccessKeyId", "The key does not exist"))
    host = R2ImageHost(s3, "bucket", "https://pub.example")

    with pytest.raises(ImageHostError, match="InvalidAccessKeyId: The key does not exist"):
        await host.check_public_access(_http(lambda r: httpx.Response(200)))


async def test_check_public_access_reports_unreachable_url():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(ImageHostError, match="ConnectError"):
        await R2ImageHost(FakeS3(), "bucket", "https://pub.example").check_public_access(_http(handler))


def test_describe_storage_error_never_uses_the_exception_text():
    class Leaky(Exception):
        pass

    assert describe_storage_error(Leaky("signature=abc secret")) == "Leaky"
