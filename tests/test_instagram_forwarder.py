import io
from types import SimpleNamespace

import pytest
from PIL import Image

from app.instagram_forwarder import InstagramForwarder
from app.models import Article
from tests.fakes.instagram import ADMIN, EXTRA, TRIGGER, FakePageImageFetcher, configure_instagram
from tests.fakes.telegram import make_context

SOURCE_CHAT = "-1001"
SOURCE_THREAD = 7


def _png(width=600, height=600):
    out = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(out, format="PNG")
    return out.getvalue()


def make_post(
    message_id,
    caption=None,
    text=None,
    photo=True,
    media_group_id=None,
    chat_id=SOURCE_CHAT,
    thread_id=SOURCE_THREAD,
    video=None,
    entities=(),
    link_preview_options=None,
):
    """Duck-typed telegram.Message with only what the forwarder reads."""
    sizes = [SimpleNamespace(file_id=f"small-{message_id}"), SimpleNamespace(file_id=f"big-{message_id}")]
    body = text or ""
    message = SimpleNamespace(
        message_id=message_id,
        chat=SimpleNamespace(id=int(chat_id)),
        message_thread_id=thread_id,
        media_group_id=media_group_id,
        caption=caption,
        text=text,
        photo=sizes if photo else [],
        video=video,
        animation=None,
        video_note=None,
        entities=list(entities),
        link_preview_options=link_preview_options,
        # Plain slicing: tests only use ASCII before a link (real offsets are UTF-16).
        parse_entity=lambda e: body[e.offset:e.offset + e.length],
    )
    return SimpleNamespace(effective_message=message)


def url_entity(text, url):
    return SimpleNamespace(type="url", offset=text.index(url), length=len(url), url=None)


@pytest.fixture
async def configured(telegram_bot, instagram_settings_repository, instagram_settings):
    """SOURCE_CHAT: subscribed, news topic SOURCE_THREAD, Instagram set up."""
    await telegram_bot.register_chat_db(SOURCE_CHAT, "AniKoe", "supergroup", SOURCE_THREAD)
    configure_instagram(instagram_settings_repository, SOURCE_CHAT)
    await instagram_settings.load()


@pytest.fixture
def instagram(fake_connector):
    return fake_connector.instagram


@pytest.fixture
def image_host(fake_connector):
    return fake_connector.image_host_fake


@pytest.fixture
def page_images():
    return FakePageImageFetcher({
        "https://news.example/a": _png(1200, 630),
        "https://img.example/pic.jpg": _png(800, 800),
    })


@pytest.fixture
def forwarder(configured, instagram_settings, instagram_post_repository, fake_connector, page_images, telegram_bot):
    return InstagramForwarder(
        instagram_settings,
        instagram_post_repository,
        fake_connector,
        page_images,
        telegram_bot,
        album_wait=0,
    )


@pytest.fixture
def context(fake_tg_bot):
    for i in range(1, 20):
        fake_tg_bot.files[f"big-{i}"] = _png()
    return make_context(bot=fake_tg_bot)


async def _handle(forwarder, context, *updates):
    for update in updates:
        await forwarder.handle(update, context)
    await forwarder.wait_idle()


# --------------------------------------------------------------------------
# Posts in the chat
# --------------------------------------------------------------------------
async def test_publishes_photo_post_with_trigger_hashtag(
    forwarder, context, instagram, image_host, fake_connector, fake_tg_bot, fake_db_handle
):
    await _handle(forwarder, context, make_post(1, caption=f"Нова серія!\n{TRIGGER}"))

    [post] = instagram.published
    assert post["caption"] == f"Нова серія!\n{TRIGGER}\n\n" + " ".join(EXTRA)
    assert len(post["image_urls"]) == 1
    assert fake_tg_bot.downloaded == ["big-1"]  # the largest size
    # Clients are built from this chat's own (decrypted) settings.
    assert fake_connector.clients_built_for[0].instagram_token == f"token-{SOURCE_CHAT}"
    assert fake_connector.hosts_built_for[0].r2_secret_access_key == "key-secret"
    # Uploaded as a JPEG, then removed once Instagram had it.
    assert image_host.uploaded and image_host.deleted == image_host.uploaded
    [doc] = fake_db_handle.instagram_posts.docs
    assert doc["status"] == "published" and doc["ig_media_id"] == "ig-media-1"
    # The admin who connected the account hears about it, privately.
    [notice] = fake_tg_bot.sent[-1:]
    assert notice["chat_id"] == ADMIN
    assert "«AniKoe»" in notice["text"] and "@anikoe" in notice["text"]


async def test_ignores_posts_without_trigger_hashtag(forwarder, context, instagram, fake_db_handle):
    await _handle(forwarder, context, make_post(1, caption="Просто пост #аніме"))

    assert instagram.published == []
    assert fake_db_handle.instagram_posts.docs == []


@pytest.mark.parametrize("kwargs", [{"thread_id": 8}, {"thread_id": None}])
async def test_ignores_other_topics_of_the_chat(forwarder, context, instagram, kwargs):
    await _handle(forwarder, context, make_post(1, caption=TRIGGER, **kwargs))

    assert instagram.published == []


async def test_ignores_chats_without_instagram(forwarder, context, instagram, telegram_bot):
    await telegram_bot.register_chat_db("-1002", "Other", "supergroup", SOURCE_THREAD)

    await _handle(forwarder, context, make_post(1, caption=TRIGGER, chat_id="-1002"))

    assert instagram.published == []


async def test_ignores_chat_that_stopped_news(forwarder, context, instagram, telegram_bot):
    await telegram_bot.deactivate_chat_db(SOURCE_CHAT)

    await _handle(forwarder, context, make_post(1, caption=TRIGGER))

    assert instagram.published == []


async def test_ignores_chat_whose_setup_is_incomplete(
    forwarder, context, instagram, telegram_bot, instagram_settings_repository, instagram_settings
):
    await telegram_bot.register_chat_db("-1003", "No tag", "supergroup", None)
    configure_instagram(instagram_settings_repository, "-1003", trigger=None)
    await instagram_settings.load()

    await _handle(forwarder, context, make_post(1, caption=TRIGGER, chat_id="-1003", thread_id=None))

    assert instagram.published == []


async def test_chat_without_news_topic_is_watched_whole(
    forwarder, context, instagram, telegram_bot, instagram_settings_repository, instagram_settings
):
    await telegram_bot.register_chat_db("-1004", "Plain group", "supergroup", None)
    configure_instagram(instagram_settings_repository, "-1004")
    await instagram_settings.load()

    await _handle(forwarder, context, make_post(1, caption=TRIGGER, chat_id="-1004", thread_id=99))

    assert len(instagram.published) == 1


async def test_each_chat_uses_its_own_hashtags(
    forwarder, context, instagram, telegram_bot, instagram_settings_repository, instagram_settings
):
    await telegram_bot.register_chat_db("-1005", "Games", "supergroup", None)
    configure_instagram(instagram_settings_repository, "-1005", trigger="#ігри", extra=["#gaming"])
    await instagram_settings.load()

    await _handle(
        forwarder, context,
        make_post(1, caption=f"A {TRIGGER}", chat_id="-1005", thread_id=None),  # not this chat's tag
        make_post(2, caption="B #ігри", chat_id="-1005", thread_id=None),
    )

    [post] = instagram.published
    assert post["caption"] == "B #ігри\n\n#gaming"


async def test_settings_removed_meanwhile_skips_without_claiming(forwarder, context, instagram, fake_db_handle):
    fake_db_handle.instagram_settings.docs.clear()  # gone from the DB, not yet from the index

    await _handle(forwarder, context, make_post(1, caption=TRIGGER))

    assert instagram.published == []
    assert fake_db_handle.instagram_posts.docs == []


async def test_skips_text_post_without_link(forwarder, context, instagram, fake_db_handle):
    await _handle(forwarder, context, make_post(1, text=f"Анонс {TRIGGER}", photo=False))

    assert instagram.published == []
    assert fake_db_handle.instagram_posts.docs == []


async def test_text_post_uses_picture_of_its_first_link(forwarder, context, instagram, page_images):
    text = f"News https://news.example/a and https://other.example {TRIGGER}"
    entities = [url_entity(text, "https://other.example"), url_entity(text, "https://news.example/a")]

    await _handle(forwarder, context, make_post(1, text=text, photo=False, entities=entities))

    assert page_images.fetched == ["https://news.example/a"]
    [post] = instagram.published
    assert len(post["image_urls"]) == 1
    assert post["caption"].startswith(text)


async def test_text_link_entity_counts_as_link(forwarder, context, instagram, page_images):
    text = f"Read more {TRIGGER}"
    entity = SimpleNamespace(type="text_link", offset=0, length=4, url="https://img.example/pic.jpg")

    await _handle(forwarder, context, make_post(1, text=text, photo=False, entities=[entity]))

    assert page_images.fetched == ["https://img.example/pic.jpg"]
    assert len(instagram.published) == 1


async def test_explicit_link_preview_url_wins(forwarder, context, page_images):
    text = f"News https://news.example/a {TRIGGER}"
    options = SimpleNamespace(is_disabled=False, url="https://img.example/pic.jpg")

    await _handle(forwarder, context, make_post(
        1, text=text, photo=False, entities=[url_entity(text, "https://news.example/a")], link_preview_options=options,
    ))

    assert page_images.fetched == ["https://img.example/pic.jpg"]


async def test_disabled_link_preview_means_no_picture(forwarder, context, instagram, page_images):
    text = f"News https://news.example/a {TRIGGER}"
    options = SimpleNamespace(is_disabled=True, url=None)

    await _handle(forwarder, context, make_post(
        1, text=text, photo=False, entities=[url_entity(text, "https://news.example/a")], link_preview_options=options,
    ))

    assert page_images.fetched == []
    assert instagram.published == []


async def test_link_without_picture_is_recorded_as_failed(forwarder, context, instagram, fake_db_handle, fake_tg_bot):
    text = f"News https://nopic.example {TRIGGER}"

    await _handle(forwarder, context, make_post(
        1, text=text, photo=False, entities=[url_entity(text, "https://nopic.example")]
    ))

    assert instagram.published == []
    [doc] = fake_db_handle.instagram_posts.docs
    assert doc["status"] == "failed"
    assert fake_tg_bot.sent[-1]["chat_id"] == ADMIN
    assert "немає картинки" in fake_tg_bot.sent[-1]["text"]


async def test_skips_video_post(forwarder, context, instagram):
    await _handle(forwarder, context, make_post(1, caption=TRIGGER, photo=False, video=object()))

    assert instagram.published == []


async def test_album_becomes_one_carousel(forwarder, context, instagram, fake_tg_bot):
    await _handle(
        forwarder,
        context,
        make_post(3, media_group_id="g1"),
        make_post(1, media_group_id="g1", caption=f"Альбом {TRIGGER}"),
        make_post(2, media_group_id="g1"),
    )

    [post] = instagram.published
    assert len(post["image_urls"]) == 3
    # In the album's order, not the order the updates arrived in.
    assert fake_tg_bot.downloaded == ["big-1", "big-2", "big-3"]
    assert post["caption"].startswith(f"Альбом {TRIGGER}")


async def test_album_with_video_is_skipped(forwarder, context, instagram):
    await _handle(
        forwarder,
        context,
        make_post(1, media_group_id="g1", caption=TRIGGER),
        make_post(2, media_group_id="g1", photo=False, video=object()),
    )

    assert instagram.published == []


async def test_same_post_is_not_published_twice(forwarder, context, instagram):
    await _handle(forwarder, context, make_post(1, caption=TRIGGER))
    await _handle(forwarder, context, make_post(1, caption=TRIGGER))

    assert len(instagram.published) == 1


async def test_failure_is_recorded_and_reported(forwarder, context, instagram, image_host, fake_tg_bot, fake_db_handle):
    instagram.fail("Error validating access token")

    await _handle(forwarder, context, make_post(1, caption=TRIGGER))

    [doc] = fake_db_handle.instagram_posts.docs
    assert doc["status"] == "failed" and doc["error"] == "Error validating access token"
    assert fake_tg_bot.sent[-1]["chat_id"] == ADMIN
    assert "Error validating access token" in fake_tg_bot.sent[-1]["text"]
    assert image_host.deleted == image_host.uploaded  # cleaned up even on failure


async def test_no_notification_without_admin(forwarder, context, instagram, fake_tg_bot, fake_db_handle):
    fake_db_handle.instagram_settings.docs[0]["admin_user_id"] = None

    await _handle(forwarder, context, make_post(1, caption=TRIGGER))

    assert len(instagram.published) == 1
    assert fake_tg_bot.sent == []


async def test_ignores_updates_without_message(forwarder, context, instagram):
    await _handle(forwarder, context, SimpleNamespace(effective_message=None))

    assert instagram.published == []


# --------------------------------------------------------------------------
# The bot's own news posts (handed over by ArticlePublisher)
# --------------------------------------------------------------------------
def _article(**kwargs):
    defaults = dict(title="T", url="https://news.example/a", image_url=None, id="art-1")
    return Article(**{**defaults, **kwargs})


async def test_forward_article_publishes_with_preview_picture(forwarder, instagram, page_images, fake_db_handle):
    html_text = f"<b>Привіт!</b> Новина &amp; <a href='https://news.example/a'>джерело</a>\n{TRIGGER}"

    forwarder.forward_article(SOURCE_CHAT, SOURCE_THREAD, _article(image_url="https://img.example/pic.jpg"), html_text)
    await forwarder.wait_idle()

    assert page_images.fetched == ["https://img.example/pic.jpg"]
    [post] = instagram.published
    assert post["caption"] == (
        f"Привіт! Новина & джерело (https://news.example/a)\n{TRIGGER}\n\n" + " ".join(EXTRA)
    )
    [doc] = fake_db_handle.instagram_posts.docs
    assert doc["post_key"] == "article:art-1" and doc["status"] == "published"


async def test_forward_article_falls_back_to_article_page(forwarder, instagram, page_images):
    forwarder.forward_article(SOURCE_CHAT, SOURCE_THREAD, _article(), f"Текст {TRIGGER}")
    await forwarder.wait_idle()

    assert page_images.fetched == ["https://news.example/a"]
    assert len(instagram.published) == 1


@pytest.mark.parametrize(
    "chat_id, text",
    [
        ("-1002", f"Текст {TRIGGER}"),        # Instagram not set up there
        (SOURCE_CHAT, "Текст без тегу"),
    ],
)
async def test_forward_article_ignores_unconfigured_chats_and_untagged_posts(
    forwarder, instagram, page_images, chat_id, text
):
    forwarder.forward_article(chat_id, SOURCE_THREAD, _article(), text)
    await forwarder.wait_idle()

    assert page_images.fetched == []
    assert instagram.published == []


async def test_forward_article_without_any_url_is_skipped(forwarder, instagram, page_images):
    forwarder.forward_article(SOURCE_CHAT, SOURCE_THREAD, _article(url=""), f"Текст {TRIGGER}")
    await forwarder.wait_idle()

    assert page_images.fetched == []
    assert instagram.published == []


async def test_same_article_is_not_forwarded_twice(forwarder, instagram):
    for _ in range(2):
        forwarder.forward_article(SOURCE_CHAT, SOURCE_THREAD, _article(), f"Текст {TRIGGER}")
        await forwarder.wait_idle()

    assert len(instagram.published) == 1


# --------------------------------------------------------------------------
# Several tracked hashtags
# --------------------------------------------------------------------------
async def test_any_tracked_hashtag_picks_the_post(
    forwarder, context, instagram, instagram_settings_repository, instagram_settings
):
    instagram_settings_repository.save_trigger_hashtags(SOURCE_CHAT, [TRIGGER, "#в_інсту"])
    await instagram_settings.load()

    await _handle(
        forwarder, context,
        make_post(1, caption="Перший #в_інсту"),
        make_post(2, caption=f"Другий {TRIGGER}"),
        make_post(3, caption="Третій #аніме"),  # tracked by neither
    )

    # Each post is its own background task, so they may finish in any order.
    assert sorted(p["caption"].split("\n")[0] for p in instagram.published) == sorted(
        ["Перший #в_інсту", f"Другий {TRIGGER}"]
    )


async def test_any_tracked_hashtag_picks_the_bots_own_post(
    forwarder, instagram, instagram_settings_repository, instagram_settings
):
    instagram_settings_repository.save_trigger_hashtags(SOURCE_CHAT, [TRIGGER, "#в_інсту"])
    await instagram_settings.load()

    forwarder.forward_article(SOURCE_CHAT, SOURCE_THREAD, _article(), "Новина #в_інсту")
    await forwarder.wait_idle()

    assert len(instagram.published) == 1


# --------------------------------------------------------------------------
# The Instagram topic
# --------------------------------------------------------------------------
async def test_chosen_topic_is_watched_instead_of_the_news_topic(
    forwarder, context, instagram, instagram_settings_repository, instagram_settings
):
    instagram_settings_repository.save_topic(SOURCE_CHAT, 9, "Інстаграм", all_topics=False)
    await instagram_settings.load()

    await _handle(
        forwarder, context,
        make_post(1, caption=f"У гілці Instagram {TRIGGER}", thread_id=9),
        make_post(2, caption=f"У гілці новин {TRIGGER}", thread_id=SOURCE_THREAD),
    )

    [post] = instagram.published
    assert post["caption"].startswith("У гілці Instagram")


async def test_bots_news_are_skipped_when_instagram_watches_another_topic(
    forwarder, instagram, page_images, instagram_settings_repository, instagram_settings
):
    instagram_settings_repository.save_topic(SOURCE_CHAT, 9, None, all_topics=False)
    await instagram_settings.load()

    forwarder.forward_article(SOURCE_CHAT, SOURCE_THREAD, _article(), f"Новина {TRIGGER}")
    await forwarder.wait_idle()

    assert page_images.fetched == []
    assert instagram.published == []


async def test_whole_chat_mode_takes_every_topic(
    forwarder, context, instagram, instagram_settings_repository, instagram_settings
):
    instagram_settings_repository.save_topic(SOURCE_CHAT, None, None, all_topics=True)
    await instagram_settings.load()

    await _handle(
        forwarder, context,
        make_post(1, caption=f"A {TRIGGER}", thread_id=9),
        make_post(2, caption=f"B {TRIGGER}", thread_id=None),
    )
    forwarder.forward_article(SOURCE_CHAT, SOURCE_THREAD, _article(), f"C {TRIGGER}")
    await forwarder.wait_idle()

    assert len(instagram.published) == 3


async def test_default_mode_follows_settopic(forwarder, context, instagram, telegram_bot):
    await telegram_bot.register_chat_db(SOURCE_CHAT, "AniKoe", "supergroup", 8)  # /settopic in topic 8

    await _handle(
        forwarder, context,
        make_post(1, caption=f"Нова гілка {TRIGGER}", thread_id=8),
        make_post(2, caption=f"Стара гілка {TRIGGER}", thread_id=SOURCE_THREAD),
    )

    [post] = instagram.published
    assert post["caption"].startswith("Нова гілка")
