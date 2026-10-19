import io
from types import SimpleNamespace

import pytest
from PIL import Image

from app.instagram_forwarder import InstagramForwarder
from tests.fakes.instagram import FakeImageHost, FakeInstagramClient
from tests.fakes.telegram import make_context

SOURCE_CHAT = "-1001"
SOURCE_THREAD = 7
TRIGGER = "#Команда_AniKoe"
EXTRA = ["#аніме", "#анімеукраїнською", "#анімеукраїна", "#українаніме", "#анімеоналайн"]


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
):
    """Duck-typed telegram.Message with only what the forwarder reads."""
    sizes = [SimpleNamespace(file_id=f"small-{message_id}"), SimpleNamespace(file_id=f"big-{message_id}")]
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
    )
    return SimpleNamespace(effective_message=message)


@pytest.fixture
def image_host():
    return FakeImageHost()


@pytest.fixture
def instagram():
    return FakeInstagramClient()


@pytest.fixture
def forwarder(instagram_post_repository, image_host, instagram, telegram_bot):
    return InstagramForwarder(
        source_chat_id=SOURCE_CHAT,
        source_thread_id=SOURCE_THREAD,
        trigger_hashtag=TRIGGER,
        extra_hashtags=EXTRA,
        post_repository=instagram_post_repository,
        image_host=image_host,
        instagram_client=instagram,
        telegram_bot=telegram_bot,
        notify_chat_id="555",
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


async def test_publishes_photo_post_with_trigger_hashtag(forwarder, context, instagram, image_host, fake_tg_bot, fake_db_handle):
    await _handle(forwarder, context, make_post(1, caption="Нова серія!\n#Команда_AniKoe"))

    [post] = instagram.published
    assert post["caption"] == "Нова серія!\n#Команда_AniKoe\n\n" + " ".join(EXTRA)
    assert len(post["image_urls"]) == 1
    assert fake_tg_bot.downloaded == ["big-1"]  # the largest size
    # Uploaded as a JPEG, then removed once Instagram had it.
    assert image_host.uploaded and image_host.deleted == image_host.uploaded
    [doc] = fake_db_handle.instagram_posts.docs
    assert doc["status"] == "published" and doc["ig_media_id"] == "ig-media-1"
    assert fake_tg_bot.sent[-1]["chat_id"] == "555"


async def test_ignores_posts_without_trigger_hashtag(forwarder, context, instagram, fake_db_handle):
    await _handle(forwarder, context, make_post(1, caption="Просто пост #аніме"))

    assert instagram.published == []
    assert fake_db_handle.instagram_posts.docs == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chat_id": "-1002"},
        {"thread_id": 8},
        {"thread_id": None},
    ],
)
async def test_ignores_other_chats_and_topics(forwarder, context, instagram, kwargs):
    await _handle(forwarder, context, make_post(1, caption=TRIGGER, **kwargs))

    assert instagram.published == []


async def test_any_topic_when_thread_not_configured(forwarder, context, instagram):
    forwarder._source_thread_id = None

    await _handle(forwarder, context, make_post(1, caption=TRIGGER, thread_id=99))

    assert len(instagram.published) == 1


async def test_skips_text_only_post(forwarder, context, instagram, fake_db_handle):
    await _handle(forwarder, context, make_post(1, text=f"Анонс {TRIGGER}", photo=False))

    assert instagram.published == []
    assert fake_db_handle.instagram_posts.docs == []


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
    instagram.fail("Invalid image URL")

    await _handle(forwarder, context, make_post(1, caption=TRIGGER))

    [doc] = fake_db_handle.instagram_posts.docs
    assert doc["status"] == "failed" and doc["error"] == "Invalid image URL"
    assert "Invalid image URL" in fake_tg_bot.sent[-1]["text"]
    assert image_host.deleted == image_host.uploaded  # cleaned up even on failure


async def test_works_without_notify_chat(forwarder, context, instagram, fake_tg_bot):
    forwarder._notify_chat_id = None

    await _handle(forwarder, context, make_post(1, caption=TRIGGER))

    assert len(instagram.published) == 1
    assert fake_tg_bot.sent == []


async def test_ignores_updates_without_message(forwarder, context, instagram):
    await _handle(forwarder, context, SimpleNamespace(effective_message=None))

    assert instagram.published == []
