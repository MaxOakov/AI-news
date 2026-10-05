from datetime import datetime, timezone

import pytest

from app.models import Article
from app.services.publisher import (
    ACTION_PUBLISH,
    ACTION_REGENERATE,
    ACTION_SKIP,
    REVIEW_CALLBACK_PREFIX,
)

REVIEWER = "999"


@pytest.fixture
async def chat(telegram_bot):
    await telegram_bot.register_chat_db("123", "Ігри & <аніме>", "group", message_thread_id=7)
    return telegram_bot.chats["123"]


@pytest.fixture
async def moderated_chat(telegram_bot, chat):
    await telegram_bot.set_reviewer("123", REVIEWER)
    return chat


def _stored_article(article_repository, image_url=None):
    article = Article(
        title="Title",
        url="https://example.com/a",
        summary="Summary",
        published=datetime(2026, 1, 1, tzinfo=timezone.utc),
        chat_id="123",
        image_url=image_url,
    )
    article_repository.create([article])
    return article


def _doc(article_repository, article):
    return article_repository._db.articles.find_one({"_id": article.id})


# --------------------------------------------------------------------------
# Direct publishing (moderation off)
# --------------------------------------------------------------------------
async def test_publish_sends_to_chat_with_image_preview_and_marks_sent(
    publisher, chat, article_repository, fake_tg_bot
):
    article = _stored_article(article_repository, image_url="https://img.example/x.jpg")

    assert await publisher.publish("123", chat, article, "Post text") is True

    [message] = fake_tg_bot.sent
    assert message["chat_id"] == "123"
    assert message["text"] == "Post text"
    assert message["message_thread_id"] == 7
    preview = message["link_preview_options"]
    assert preview.url == "https://img.example/x.jpg"
    assert preview.prefer_large_media is True
    assert preview.show_above_text is True
    assert "reply_markup" not in message
    assert _doc(article_repository, article)["is_sent"] is True


async def test_publish_without_image_previews_the_article_page(
    publisher, chat, article_repository, fake_tg_bot
):
    article = _stored_article(article_repository)

    await publisher.publish("123", chat, article, "Post text")

    assert fake_tg_bot.sent[0]["link_preview_options"].url == "https://example.com/a"


async def test_publish_failure_records_failure(publisher, chat, article_repository, fake_tg_bot):
    article = _stored_article(article_repository)
    fake_tg_bot.fail_times(99)

    assert await publisher.publish("123", chat, article, "Post text") is False

    doc = _doc(article_repository, article)
    assert doc["is_sent"] is False
    assert doc["fail_count"] == 1


# --------------------------------------------------------------------------
# Moderation on: drafts go to the reviewer instead of the chat
# --------------------------------------------------------------------------
async def test_moderated_publish_sends_draft_to_reviewer(
    publisher, moderated_chat, article_repository, fake_tg_bot
):
    article = _stored_article(article_repository, image_url="https://img.example/x.jpg")

    assert await publisher.publish("123", moderated_chat, article, "Draft text") is True

    [message] = fake_tg_bot.sent
    assert message["chat_id"] == REVIEWER
    # Chat name is HTML-escaped, since the draft is sent with parse_mode=HTML.
    assert message["text"] == "📝 Чернетка для «Ігри &amp; &lt;аніме&gt;»:\n\nDraft text"
    assert message["link_preview_options"].url == "https://img.example/x.jpg"
    callbacks = [b.callback_data for row in message["reply_markup"].inline_keyboard for b in row]
    assert callbacks == [
        f"{REVIEW_CALLBACK_PREFIX}{action}:{article.id}"
        for action in (ACTION_PUBLISH, ACTION_REGENERATE, ACTION_SKIP)
    ]
    assert all(len(c.encode()) <= 64 for c in callbacks)  # Telegram's callback_data limit

    doc = _doc(article_repository, article)
    assert doc["is_sent"] is False
    assert doc["review_chat_id"] == REVIEWER
    assert doc["draft_text"] == "Draft text"
    # Waiting on the reviewer, so the next run moves on to another article.
    assert article_repository.get_next_unsent("123") is None


async def test_moderated_publish_failure_records_failure_and_stays_queued(
    publisher, moderated_chat, article_repository, fake_tg_bot
):
    article = _stored_article(article_repository)
    fake_tg_bot.fail_times(99)

    assert await publisher.publish("123", moderated_chat, article, "Draft text") is False

    queued = article_repository.get_next_unsent("123")
    assert queued.id == article.id
    assert queued.fail_count == 1


# --------------------------------------------------------------------------
# handle_review: the reviewer's ✅ / 🔄 / ❌ buttons
# --------------------------------------------------------------------------
@pytest.fixture
async def drafted(publisher, moderated_chat, article_repository, fake_tg_bot):
    article = _stored_article(article_repository, image_url="https://img.example/x.jpg")
    await publisher.publish("123", moderated_chat, article, "Draft text")
    fake_tg_bot.sent.clear()
    return article


async def test_review_publish_posts_the_draft_to_the_chat(
    publisher, drafted, article_repository, fake_tg_bot
):
    result = await publisher.handle_review(ACTION_PUBLISH, str(drafted.id), REVIEWER)

    assert result.done is True
    assert result.message == "✅ Опубліковано"
    [message] = fake_tg_bot.sent
    assert message["chat_id"] == "123"
    assert message["text"] == "Draft text"  # exactly what the reviewer saw, without the header
    assert message["message_thread_id"] == 7
    assert message["link_preview_options"].url == "https://img.example/x.jpg"
    assert _doc(article_repository, drafted)["is_sent"] is True


async def test_review_publish_twice_posts_once(publisher, drafted, fake_tg_bot):
    await publisher.handle_review(ACTION_PUBLISH, str(drafted.id), REVIEWER)
    result = await publisher.handle_review(ACTION_PUBLISH, str(drafted.id), REVIEWER)

    assert result.done is True
    assert result.message == "✅ Вже опубліковано"
    assert len(fake_tg_bot.sent) == 1


async def test_review_skip(publisher, drafted, article_repository, fake_tg_bot):
    result = await publisher.handle_review(ACTION_SKIP, str(drafted.id), REVIEWER)

    assert result.done is True
    assert result.message == "❌ Пропущено"
    assert _doc(article_repository, drafted)["skipped"] is True
    assert fake_tg_bot.sent == []

    again = await publisher.handle_review(ACTION_PUBLISH, str(drafted.id), REVIEWER)
    assert again.message == "❌ Вже пропущено"
    assert fake_tg_bot.sent == []


async def test_review_regenerate_sends_a_new_draft(
    publisher, drafted, article_repository, fake_genai_client, fake_tg_bot
):
    fake_genai_client.set_response("Second version")

    result = await publisher.handle_review(ACTION_REGENERATE, str(drafted.id), REVIEWER)

    assert result.done is True
    [message] = fake_tg_bot.sent
    assert message["chat_id"] == REVIEWER
    assert message["text"].endswith("Second version")
    assert message["reply_markup"] is not None
    assert _doc(article_repository, drafted)["draft_text"] == "Second version"

    # Publishing now posts the regenerated text.
    await publisher.handle_review(ACTION_PUBLISH, str(drafted.id), REVIEWER)
    assert fake_tg_bot.sent[-1]["text"] == "Second version"


async def test_review_regenerate_gemini_failure_keeps_the_draft(
    publisher, drafted, article_repository, fake_genai_client, fake_tg_bot
):
    fake_genai_client.fail_times(99)

    result = await publisher.handle_review(ACTION_REGENERATE, str(drafted.id), REVIEWER)

    assert result.done is False
    assert fake_tg_bot.sent == []
    assert _doc(article_repository, drafted)["draft_text"] == "Draft text"


async def test_review_publish_send_failure_can_be_retried(
    publisher, drafted, article_repository, fake_tg_bot
):
    fake_tg_bot.fail_times(99)
    result = await publisher.handle_review(ACTION_PUBLISH, str(drafted.id), REVIEWER)

    assert result.done is False
    assert _doc(article_repository, drafted)["is_sent"] is False


async def test_review_by_someone_else_is_rejected(publisher, drafted, article_repository, fake_tg_bot):
    result = await publisher.handle_review(ACTION_PUBLISH, str(drafted.id), "555")

    assert result.message == "⚠️ Чернетку не знайдено"
    assert fake_tg_bot.sent == []
    assert _doc(article_repository, drafted)["is_sent"] is False


async def test_review_unknown_article(publisher):
    result = await publisher.handle_review(ACTION_PUBLISH, "does-not-exist", REVIEWER)
    assert result.message == "⚠️ Чернетку не знайдено"


async def test_review_publish_for_stopped_chat_is_refused(
    publisher, drafted, telegram_bot, fake_tg_bot
):
    await telegram_bot.deactivate_chat_db("123")

    result = await publisher.handle_review(ACTION_PUBLISH, str(drafted.id), REVIEWER)

    assert result.done is False
    assert "/start" in result.message
    assert fake_tg_bot.sent == []


async def test_review_unknown_action(publisher, drafted):
    result = await publisher.handle_review("bogus", str(drafted.id), REVIEWER)
    assert result.done is False


async def test_review_regenerate_send_failure_keeps_buttons(
    publisher, drafted, article_repository, fake_genai_client, fake_tg_bot
):
    fake_genai_client.set_response("Second version")
    fake_tg_bot.fail_times(fake_tg_bot._attempts + 99)

    result = await publisher.handle_review(ACTION_REGENERATE, str(drafted.id), REVIEWER)

    assert result.done is False
    assert _doc(article_repository, drafted)["draft_text"] == "Draft text"
