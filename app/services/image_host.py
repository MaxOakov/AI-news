"""Public hosting for images on their way to Instagram (Cloudflare R2).

The Graph API only takes an image by public URL, and a Telegram file URL
can't be used for that: it contains the bot token.
"""
import boto3


def make_r2_client(account_id: str, access_key_id: str, secret_access_key: str):
    """An S3 client pointed at an account's R2 endpoint (R2 speaks the S3 API)."""
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


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
