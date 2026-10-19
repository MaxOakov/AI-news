"""Public hosting for images on their way to Instagram (Cloudflare R2).

The Graph API only takes an image by public URL, and a Telegram file URL
can't be used for that: it contains the bot token.
"""
import asyncio
import uuid

import boto3
import httpx

_CHECK_BODY = b"ai-news-bot check"


class ImageHostError(Exception):
    """The bucket can't be used: bad credentials, or no public access."""


def make_r2_client(account_id: str, access_key_id: str, secret_access_key: str):
    """An S3 client pointed at an account's R2 endpoint (R2 speaks the S3 API)."""
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


def describe_storage_error(exc: Exception) -> str:
    """What went wrong, from the S3 error code and message when there is
    one (never the request itself, which carries the credentials' signature)."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict) and "Error" in response:
        error = response["Error"]
        return f"{error.get('Code', 'Error')}: {error.get('Message', '')}".strip()
    return type(exc).__name__


class R2ImageHost:
    """Uploads images to an R2 bucket served publicly at `public_base_url`
    (its r2.dev subdomain or a custom domain). Synchronous (boto3); async
    callers wrap it in asyncio.to_thread."""

    def __init__(self, client, bucket: str, public_base_url: str):
        self._client = client
        self._bucket = bucket
        self._public_base_url = public_base_url.rstrip("/")

    def upload(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        """Store `data` under `key` and return its public URL."""
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return f"{self._public_base_url}/{key}"

    def delete(self, key: str):
        self._client.delete_object(Bucket=self._bucket, Key=key)

    async def check_public_access(self, http_client: httpx.AsyncClient):
        """Upload a small file, fetch it back through the public URL the way
        Instagram will, and delete it. Raises ImageHostError if any step fails."""
        key = f"instagram/_check-{uuid.uuid4().hex}.txt"
        try:
            url = await asyncio.to_thread(self.upload, key, _CHECK_BODY, "text/plain")
        except Exception as exc:
            raise ImageHostError(f"не вдалося записати файл у бакет ({describe_storage_error(exc)})") from None

        try:
            try:
                response = await http_client.get(url, follow_redirects=True)
            except httpx.HTTPError as exc:
                raise ImageHostError(f"публічний URL бакета недоступний ({type(exc).__name__})") from None
            if response.status_code != 200 or response.content != _CHECK_BODY:
                raise ImageHostError(
                    f"файл не відкривається за публічним URL (HTTP {response.status_code}) — "
                    "увімкніть публічний доступ до бакета і перевірте URL"
                )
        finally:
            try:
                await asyncio.to_thread(self.delete, key)
            except Exception as exc:
                print(f"⚠️ Не вдалося видалити перевірочний файл {key} з R2: {describe_storage_error(exc)}")
