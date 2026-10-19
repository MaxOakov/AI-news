"""Fakes for the Telegram side: a stand-in bot for TelegramBot.send_message
(and, doubling as context.bot, for admin-status checks), and duck-typed
Update/Context doubles for BotCommands handler tests.

Real python-telegram-bot Update/Chat/Message objects are effectively-frozen
and awkward to construct directly, so these are plain duck-typed objects
exposing only the attributes the app actually reads.
"""
from types import SimpleNamespace


class FakeTGBot:
    """Stand-in for telegram.Bot.

    Used two ways in tests: as TelegramBot.bot (send_message), and as
    context.bot for BotCommands' admin-status checks (get_chat_member).
    """

    username = "test_news_bot"

    def __init__(self):
        self.sent: list[dict] = []
        self.chat_titles: dict[str, str] = {}
        self._attempts = 0
        self._fail_times = 0
        self._exception_factory = lambda: RuntimeError("simulated Telegram failure")
        self._admins: set = set()
        self._admin_check_fails = False
        self.files: dict[str, bytes] = {}
        self.downloaded: list[str] = []

    def fail_times(self, n: int, exc: Exception | None = None):
        """Make the next `n` send_message attempts raise before any later one succeeds."""
        self._fail_times = n
        if exc is not None:
            self._exception_factory = lambda: exc

    async def send_message(self, **payload):
        self._attempts += 1
        if self._attempts <= self._fail_times:
            raise self._exception_factory()
        self.sent.append(payload)

    def make_admin(self, user_id, status="administrator", chat_id=None):
        """Mark a user id as an admin (or "creator") for get_chat_member:
        of every chat, or only of `chat_id` if given."""
        self._admins.add((user_id, status, None if chat_id is None else str(chat_id)))

    def fail_admin_check(self):
        """Make get_chat_member raise, simulating a Bot API error."""
        self._admin_check_fails = True

    async def get_chat_member(self, chat_id, user_id):
        if self._admin_check_fails:
            raise RuntimeError("simulated get_chat_member failure")
        for admin_id, status, admin_chat_id in self._admins:
            if admin_id == user_id and admin_chat_id in (None, str(chat_id)):
                return SimpleNamespace(status=status)
        return SimpleNamespace(status="member")

    async def get_chat(self, chat_id):
        """A chat titled `chat_titles[chat_id]`; an unknown one fails like the Bot API."""
        if str(chat_id) not in self.chat_titles:
            raise RuntimeError("chat not found")
        return SimpleNamespace(id=chat_id, title=self.chat_titles[str(chat_id)], first_name=None)


    async def get_file(self, file_id):
        """Return a stand-in telegram.File; its contents are `files[file_id]`."""
        self.downloaded.append(file_id)
        return FakeFile(self.files[file_id])


class FakeFile:
    def __init__(self, data: bytes):
        self._data = data

    async def download_as_bytearray(self):
        return bytearray(self._data)


class FakeMessage:
    """Stand-in for telegram.Message, recording every reply_text call
    (and whether it was deleted)."""

    def __init__(self, message_thread_id=None, sender_chat_id=None, is_topic_message=None, topic_name=None):
        self.message_thread_id = message_thread_id
        # Like Telegram: sent in a forum topic iff it has a thread id, unless
        # told otherwise (a reply thread in a non-forum group also has one).
        self.is_topic_message = message_thread_id is not None if is_topic_message is None else is_topic_message
        # A message sent straight into a topic replies to the topic's creation message.
        self.reply_to_message = (
            SimpleNamespace(forum_topic_created=SimpleNamespace(name=topic_name)) if topic_name else None
        )
        self.sender_chat = SimpleNamespace(id=sender_chat_id) if sender_chat_id is not None else None
        self.replies: list[str] = []
        self.reply_markups: list = []
        self.deleted = False
        self.delete_fails = False

    async def reply_text(self, text, *args, **kwargs):
        self.replies.append(text)
        self.reply_markups.append(kwargs.get("reply_markup"))

    async def delete(self):
        if self.delete_fails:
            raise RuntimeError("simulated: not enough rights to delete")
        self.deleted = True


class FakeCallbackQuery:
    """Stand-in for telegram.CallbackQuery, recording answer/edit calls.

    `message` is the message the pressed button belongs to; replies to it
    land in `message.replies`.
    """

    def __init__(self, data):
        self.data = data
        self.answers: list[dict] = []
        self.edits: list[str] = []
        self.markup_edits: list = []
        self.message = FakeMessage()

    async def answer(self, text=None, show_alert=False, **kwargs):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text, *args, **kwargs):
        self.edits.append(text)

    async def edit_message_reply_markup(self, reply_markup=None, **kwargs):
        self.markup_edits.append(reply_markup)


def make_update(
    chat_id="123",
    chat_type="private",
    title=None,
    first_name="Test User",
    user_id=1,
    message_thread_id=None,
    has_chat=True,
    has_message=True,
    sender_chat_id=None,
    callback_data=None,
    is_topic_message=None,
    topic_name=None,
):
    """Build a duck-typed stand-in for telegram.Update.

    Covers what BotCommands actually reads: update.effective_chat.{id,title,type},
    update.effective_user.{id,first_name}, update.message.{message_thread_id,
    sender_chat,reply_text}, update.callback_query (only when callback_data
    is given; a real callback Update has message=None, so pass
    has_message=False alongside it).
    """
    effective_chat = (
        SimpleNamespace(id=chat_id, title=title, type=chat_type) if has_chat else None
    )
    effective_user = (
        SimpleNamespace(id=user_id, first_name=first_name) if first_name is not None else None
    )
    message = (
        FakeMessage(
            message_thread_id=message_thread_id,
            sender_chat_id=sender_chat_id,
            is_topic_message=is_topic_message,
            topic_name=topic_name,
        )
        if has_message
        else None
    )
    callback_query = FakeCallbackQuery(callback_data) if callback_data is not None else None
    return SimpleNamespace(
        effective_chat=effective_chat,
        effective_user=effective_user,
        message=message,
        callback_query=callback_query,
    )


def make_context(args=None, bot=None):
    """Build a duck-typed stand-in for telegram.ext.ContextTypes.DEFAULT_TYPE."""
    return SimpleNamespace(args=args or [], bot=bot)
