import pytest

from app.models import InstagramRoute, InstagramSettings


@pytest.mark.parametrize(
    "route, news_topic, thread, watched",
    [
        # Default: the topic the chat's news go to…
        (InstagramRoute(("#a",)), 7, 7, True),
        (InstagramRoute(("#a",)), 7, 8, False),
        (InstagramRoute(("#a",)), 7, None, False),
        (InstagramRoute(("#a",)), 7, "7", True),
        # …or the whole chat if they have none.
        (InstagramRoute(("#a",)), None, 8, True),
        (InstagramRoute(("#a",)), None, None, True),
        # One chosen topic, whatever the news topic.
        (InstagramRoute(("#a",), topic_id=9), 7, 9, True),
        (InstagramRoute(("#a",), topic_id=9), 7, 7, False),
        (InstagramRoute(("#a",), topic_id=9), None, None, False),
        # The whole chat.
        (InstagramRoute(("#a",), all_topics=True), 7, 8, True),
        (InstagramRoute(("#a",), all_topics=True), 7, None, True),
    ],
)
def test_watches_topic(route, news_topic, thread, watched):
    assert route.watches_topic(thread, news_topic) is watched


def _ready(**kwargs):
    defaults = dict(
        chat_id="-1001", instagram_user_id="1", instagram_api_host="graph.facebook.com", instagram_token="t",
        r2_account_id="a", r2_bucket="b", r2_public_base_url="https://p", r2_access_key_id="i",
        r2_secret_access_key="s", trigger_hashtags=["#a", "#b"],
    )
    return InstagramSettings(**{**defaults, **kwargs})


def test_ready_needs_at_least_one_tracked_hashtag():
    assert _ready().is_ready
    assert not _ready(trigger_hashtags=[]).is_ready


def test_route_carries_hashtags_and_topic_but_no_secrets():
    route = _ready(instagram_topic_id=9, instagram_all_topics=False).route

    assert route == InstagramRoute(hashtags=("#a", "#b"), topic_id=9, all_topics=False)
    assert "t" not in vars(route).values()
