"""Encryption at rest for the secrets kept in MongoDB (Instagram access
tokens, R2 API keys).

Values are encrypted with Fernet (AES-128-CBC + HMAC-SHA256, from the
`cryptography` package) under a key that lives only in the environment
(SECRETS_ENCRYPTION_KEY), never in the database, so a leaked database
dump or backup alone reveals nothing. Each value is bound to where it's
stored (chat id + field name, inside the authenticated plaintext): a
ciphertext copied into another chat's or field's slot fails to decrypt
instead of being used there.

SECRETS_ENCRYPTION_KEY may list several comma-separated keys, for
rotation: the first one encrypts, any of them decrypts.
"""
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class SecretBoxError(Exception):
    """A value couldn't be decrypted: a key that's no longer configured,
    or data that was tampered with or moved."""


def generate_key() -> str:
    """A fresh key for SECRETS_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode()


class SecretBox:
    def __init__(self, keys: list[str]):
        """Raises ValueError if there's no key or one isn't a valid Fernet key."""
        if not keys:
            raise ValueError("не задано жодного ключа")
        self._fernet = MultiFernet([Fernet(key.encode()) for key in keys])

    @classmethod
    def from_env(cls, value: str | None) -> "SecretBox | None":
        """The box for a SECRETS_ENCRYPTION_KEY value, or None if it's unset."""
        keys = [key.strip() for key in (value or "").split(",") if key.strip()]
        return cls(keys) if keys else None

    def encrypt(self, value: str, context: str) -> str:
        payload = json.dumps({"c": context, "v": value}, ensure_ascii=False).encode()
        return self._fernet.encrypt(payload).decode()

    def decrypt(self, token: str, context: str) -> str:
        try:
            payload = json.loads(self._fernet.decrypt(token.encode()))
            stored_context, value = payload["c"], payload["v"]
        except (InvalidToken, ValueError, TypeError, KeyError, AttributeError):
            raise SecretBoxError("не вдалося розшифрувати") from None
        if stored_context != context:
            raise SecretBoxError("значення збережене для іншого чату чи поля")
        return value
