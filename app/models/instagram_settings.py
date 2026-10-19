from dataclasses import dataclass, field


def _same_topic(a, b) -> bool:
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class InstagramRoute:
    """Which of a chat's posts go to Instagram: the hashtags that pick them
    and the topic they're taken from. Holds no secrets, so it's what gets
    kept in memory for every chat where Instagram is set up."""

    hashtags: tuple[str, ...]
    # Only this forum topic; None = the topic the chat's news go to.
    topic_id: int | None = None
    # The whole chat, whatever topic.
    all_topics: bool = False

    def watches_topic(self, message_thread_id, news_topic_id) -> bool:
        """Whether a post in `message_thread_id` is taken, given the topic
        the chat's news go to (`news_topic_id`, None = no topic: the whole chat)."""
        if self.all_topics:
            return True
        topic = self.topic_id if self.topic_id is not None else news_topic_id
        return topic is None or _same_topic(message_thread_id, topic)


@dataclass
class InstagramSettings:
    """A chat's Instagram posting setup: the account posts go to, the R2
    bucket their photos pass through, which hashtags and topic pick posts,
    and which hashtags get added to them.

    Secret fields hold decrypted values and are left out of repr(), so
    printing or logging a settings object never shows them.
    """

    chat_id: str
    instagram_user_id: str | None = None
    instagram_username: str | None = None
    # Graph API host the token works with: graph.facebook.com (Facebook
    # Login) or graph.instagram.com (Instagram Login).
    instagram_api_host: str | None = None
    instagram_token: str | None = field(default=None, repr=False)
    r2_account_id: str | None = None
    r2_bucket: str | None = None
    r2_public_base_url: str | None = None
    r2_access_key_id: str | None = field(default=None, repr=False)
    r2_secret_access_key: str | None = field(default=None, repr=False)
    # A post goes to Instagram if it has any of these.
    trigger_hashtags: list[str] = field(default_factory=list)
    extra_hashtags: list[str] = field(default_factory=list)
    # Topic to take posts from (see InstagramRoute); its name, when known, for display.
    instagram_topic_id: int | None = None
    instagram_topic_name: str | None = None
    instagram_all_topics: bool = False
    # The admin who connected the account; gets told about each post.
    admin_user_id: str | None = None
    # Some stored secrets couldn't be decrypted (the encryption key changed
    # or isn't configured); they're None above and must be entered again.
    secrets_unreadable: bool = False

    @property
    def has_account(self) -> bool:
        return bool(self.instagram_user_id and self.instagram_token and self.instagram_api_host)

    @property
    def has_r2(self) -> bool:
        return bool(
            self.r2_account_id and self.r2_bucket and self.r2_public_base_url
            and self.r2_access_key_id and self.r2_secret_access_key
        )

    @property
    def is_ready(self) -> bool:
        """Everything posting needs is there (extra hashtags are optional)."""
        return self.has_account and self.has_r2 and bool(self.trigger_hashtags)

    @property
    def route(self) -> InstagramRoute:
        return InstagramRoute(
            hashtags=tuple(self.trigger_hashtags),
            topic_id=self.instagram_topic_id,
            all_topics=self.instagram_all_topics,
        )
