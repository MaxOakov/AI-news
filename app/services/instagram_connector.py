"""Turning a chat's stored settings into working Instagram/R2 clients, and
checking credentials before they're stored."""
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.models import InstagramSettings
from app.services.image_host import ImageHostError, R2ImageHost, describe_storage_error, make_r2_client
from app.services.instagram_client import InstagramClient, InstagramError, make_http_client

# A token from Facebook Login works on graph.facebook.com, one from
# Instagram Login (they start with "IG") on graph.instagram.com.
FACEBOOK_GRAPH_HOST = "graph.facebook.com"
INSTAGRAM_GRAPH_HOST = "graph.instagram.com"


@dataclass(frozen=True)
class AccountCheck:
    username: str
    api_host: str


class InstagramConnector:
    def __init__(
        self,
        graph_api_version: str,
        http_client: httpx.AsyncClient | None = None,
        r2_client_factory: Callable = make_r2_client,
    ):
        self._graph_api_version = graph_api_version
        self._http = http_client or make_http_client()
        self._r2_client_factory = r2_client_factory

    def _base_url(self, host: str) -> str:
        return f"https://{host}/{self._graph_api_version}"

    def instagram_client(self, settings: InstagramSettings) -> InstagramClient:
        return InstagramClient(
            settings.instagram_user_id,
            settings.instagram_token,
            self._base_url(settings.instagram_api_host),
            http_client=self._http,
        )

    def image_host(self, settings: InstagramSettings) -> R2ImageHost:
        client = self._r2_client_factory(
            settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key
        )
        return R2ImageHost(client, settings.r2_bucket, settings.r2_public_base_url)

    async def check_account(self, user_id: str, token: str) -> AccountCheck:
        """Which Graph API host the token works on, and the account's
        username. Raises InstagramError (the first host's) if neither works."""
        hosts = [FACEBOOK_GRAPH_HOST, INSTAGRAM_GRAPH_HOST]
        if token.startswith("IG"):
            hosts.reverse()

        first_error = None
        for host in hosts:
            client = InstagramClient(user_id, token, self._base_url(host), http_client=self._http)
            try:
                return AccountCheck(username=await client.get_username(), api_host=host)
            except InstagramError as exc:
                first_error = first_error or exc
        raise first_error

    async def check_r2(self, account_id, access_key_id, secret_access_key, bucket, public_base_url):
        """Raises ImageHostError unless the bucket accepts uploads and
        serves them at `public_base_url`."""
        try:
            client = self._r2_client_factory(account_id, access_key_id, secret_access_key)
        except Exception as exc:
            raise ImageHostError(f"некоректні дані R2 ({describe_storage_error(exc)})") from None
        await R2ImageHost(client, bucket, public_base_url).check_public_access(self._http)
