from app.models import Chat


def test_register_upserts_new_chat(chat_repository, sample_chat_with_topic):
    chat_repository.register(sample_chat_with_topic)
    docs = chat_repository._db.chats.docs
    assert len(docs) == 1
    assert docs[0]["chat_id"] == "123"
    assert docs[0]["message_thread_id"] == 42
    assert "added_at" in docs[0]


def test_register_again_without_topic_id_does_not_clobber_stored_value(
    chat_repository, sample_chat_with_topic
):
    chat_repository.register(sample_chat_with_topic)

    again = Chat(chat_id="123", chat_name="Test chat", chat_type="group", message_thread_id=None)
    chat_repository.register(again)

    doc = chat_repository._db.chats.docs[0]
    assert doc["message_thread_id"] == 42  # untouched by the second call


def test_register_with_new_topic_id_does_override(chat_repository, sample_chat_with_topic):
    chat_repository.register(sample_chat_with_topic)

    updated = Chat(chat_id="123", chat_name="Test chat", chat_type="group", message_thread_id=99)
    chat_repository.register(updated)

    doc = chat_repository._db.chats.docs[0]
    assert doc["message_thread_id"] == 99


def test_get_all_active_filters_and_converts(chat_repository):
    chat_repository._db.chats.docs.extend(
        [
            {"chat_id": "1", "chat_name": "A", "is_active": True},
            {"chat_id": "2", "chat_name": "B", "is_active": False},
        ]
    )
    active = chat_repository.get_all_active()
    assert len(active) == 1
    assert isinstance(active[0], Chat)
    assert active[0].chat_id == "1"


def test_deactivate_sets_is_active_false(chat_repository, sample_chat):
    chat_repository.register(sample_chat)
    chat_repository.deactivate("123")
    doc = chat_repository._db.chats.docs[0]
    assert doc["is_active"] is False
