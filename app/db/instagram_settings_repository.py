from datetime import datetime, timezone

from pymongo import ASCENDING

from app.db.database import Database
from app.models import InstagramSettings
from app.services.secret_box import SecretBox, SecretBoxError

# Stored encrypted, as `<name>_encrypted`; everything else is plain text.
_SECRET_FIELDS = ("instagram_token", "r2_access_key_id", "r2_secret_access_key")


class SecretsUnavailableError(Exception):
    """No encryption key is configured, so secrets can't be stored."""


class InstagramSettingsRepository:
    """Per-chat Instagram settings, backed by the `instagram_settings`
    collection (one document per chat).

    Kept apart from `chats` so chat documents, which get printed and
    cached, never carry secrets. Secrets are encrypted with `secret_box`
    before they're written and decrypted on read; without a box, settings
    with secrets can't be saved, and ones saved earlier read back as
    `secrets_unreadable`.
    """

    def __init__(self, database: Database, secret_box: SecretBox | None):
        self._db = database
        self._secret_box = secret_box

    @property
    def can_store_secrets(self) -> bool:
        return self._secret_box is not None

    def ensure_indexes(self):
        self._db.instagram_settings.create_index([("chat_id", ASCENDING)], unique=True)

    def get(self, chat_id) -> InstagramSettings | None:
        doc = self._db.instagram_settings.find_one({"chat_id": str(chat_id)})
        return self._from_doc(doc) if doc else None

    def get_all(self) -> list[InstagramSettings]:
        return [self._from_doc(doc) for doc in self._db.instagram_settings.find({})]

    def save_account(self, chat_id, user_id: str, username: str, api_host: str, token: str, admin_user_id: str):
        self._upsert(chat_id, {
            "instagram_user_id": user_id,
            "instagram_username": username,
            "instagram_api_host": api_host,
            "instagram_token_encrypted": self._encrypt(chat_id, "instagram_token", token),
            "admin_user_id": str(admin_user_id),
        })

    def save_r2(self, chat_id, account_id: str, bucket: str, public_base_url: str, access_key_id: str, secret_access_key: str):
        self._upsert(chat_id, {
            "r2_account_id": account_id,
            "r2_bucket": bucket,
            "r2_public_base_url": public_base_url,
            "r2_access_key_id_encrypted": self._encrypt(chat_id, "r2_access_key_id", access_key_id),
            "r2_secret_access_key_encrypted": self._encrypt(chat_id, "r2_secret_access_key", secret_access_key),
        })

    def save_trigger_hashtags(self, chat_id, hashtags: list[str]):
        self._upsert(chat_id, {"trigger_hashtags": list(hashtags)})

    def save_extra_hashtags(self, chat_id, hashtags: list[str]):
        self._upsert(chat_id, {"extra_hashtags": list(hashtags)})

    def save_topic(self, chat_id, topic_id: int | None, topic_name: str | None, all_topics: bool):
        """Where posts are taken from: one topic (`topic_id`), the whole chat
        (`all_topics`), or neither: the topic the chat's news go to."""
        self._upsert(chat_id, {
            "instagram_topic_id": topic_id,
            "instagram_topic_name": topic_name,
            "instagram_all_topics": bool(all_topics),
        })

    def delete(self, chat_id) -> bool:
        return self._db.instagram_settings.delete_one({"chat_id": str(chat_id)}).deleted_count > 0

    def _upsert(self, chat_id, fields: dict):
        self._db.instagram_settings.update_one(
            {"chat_id": str(chat_id)},
            {
                "$set": {**fields, "updated_at": datetime.now(timezone.utc)},
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

    @staticmethod
    def _context(chat_id, name: str) -> str:
        return f"{chat_id}:{name}"

    def _encrypt(self, chat_id, name: str, value: str) -> str:
        if self._secret_box is None:
            raise SecretsUnavailableError("на сервері не задано SECRETS_ENCRYPTION_KEY")
        return self._secret_box.encrypt(value, self._context(str(chat_id), name))

    def _from_doc(self, doc: dict) -> InstagramSettings:
        chat_id = str(doc["chat_id"])
        secrets, unreadable = {}, False
        for name in _SECRET_FIELDS:
            encrypted = doc.get(f"{name}_encrypted")
            if not encrypted:
                continue
            if self._secret_box is None:
                unreadable = True
                continue
            try:
                secrets[name] = self._secret_box.decrypt(encrypted, self._context(chat_id, name))
            except SecretBoxError:
                unreadable = True

        return InstagramSettings(
            chat_id=chat_id,
            instagram_user_id=doc.get("instagram_user_id"),
            instagram_username=doc.get("instagram_username"),
            instagram_api_host=doc.get("instagram_api_host"),
            r2_account_id=doc.get("r2_account_id"),
            r2_bucket=doc.get("r2_bucket"),
            r2_public_base_url=doc.get("r2_public_base_url"),
            # Before several hashtags could be tracked, a single one was
            # stored as `trigger_hashtag`.
            trigger_hashtags=list(
                doc.get("trigger_hashtags") or ([doc["trigger_hashtag"]] if doc.get("trigger_hashtag") else [])
            ),
            extra_hashtags=list(doc.get("extra_hashtags") or []),
            instagram_topic_id=doc.get("instagram_topic_id"),
            instagram_topic_name=doc.get("instagram_topic_name"),
            instagram_all_topics=bool(doc.get("instagram_all_topics", False)),
            admin_user_id=doc.get("admin_user_id"),
            secrets_unreadable=unreadable,
            **secrets,
        )
