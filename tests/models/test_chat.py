from app.models import Chat


def test_to_dict_omits_message_thread_id_when_unset():
    chat = Chat(chat_id="123", chat_name="Room", chat_type="group")
    data = chat.to_dict()
    assert "message_thread_id" not in data
    assert data == {
        "chat_id": "123",
        "chat_name": "Room",
        "chat_type": "group",
        "is_active": True,
    }


def test_to_dict_includes_message_thread_id_as_int_when_set():
    chat = Chat(chat_id=123, chat_name="Room", message_thread_id="42")
    data = chat.to_dict()
    assert data["chat_id"] == "123"  # coerced to str
    assert data["message_thread_id"] == 42  # coerced to int
    assert isinstance(data["message_thread_id"], int)


def test_from_dict_defaults():
    chat = Chat.from_dict({"chat_id": 123})
    assert chat.chat_id == "123"
    assert chat.chat_name == "Unknown chat"
    assert chat.chat_type == "private"
    assert chat.message_thread_id is None
    assert chat.is_active is True


def test_from_dict_blank_chat_name_falls_back_to_default():
    chat = Chat.from_dict({"chat_id": "1", "chat_name": ""})
    assert chat.chat_name == "Unknown chat"


def test_round_trip_without_topic():
    original = Chat(chat_id="1", chat_name="Room", chat_type="group")
    restored = Chat.from_dict(original.to_dict())
    assert restored == original


def test_round_trip_with_topic():
    original = Chat(chat_id="1", chat_name="Room", chat_type="group", message_thread_id=7)
    restored = Chat.from_dict(original.to_dict())
    assert restored == original
