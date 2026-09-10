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

    def __init__(self):
        self.sent: list[dict] = []
        self._attempts = 0
        self._fail_times = 0
        self._exception_factory = lambda: RuntimeError("simulated Telegram failure")
        self._admins: set = set()
        self._admin_check_fails = False

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

    def make_admin(self, user_id, status="administrator"):
        """Mark a user id as an admin (or "creator") for get_chat_member."""
        self._admins.add((user_id, status))

    def fail_admin_check(self):
        """Make get_chat_member raise, simulating a Bot API error."""
        self._admin_check_fails = True

    async def get_chat_member(self, chat_id, user_id):
        if self._admin_check_fails:
            raise RuntimeError("simulated get_chat_member failure")
        for admin_id, status in self._admins:
            if admin_id == user_id:
                return SimpleNamespace(status=status)
        return SimpleNamespace(status="member")


class FakeMessage:
    """Stand-in for telegram.Message, recording every reply_text call."""

    def __init__(self, message_thread_id=None, sender_chat_id=None):
        self.message_thread_id = message_thread_id
        self.sender_chat = SimpleNamespace(id=sender_chat_id) if sender_chat_id is not None else None
        self.replies: list[str] = []

    async def reply_text(self, text, *args, **kwargs):
        self.replies.append(text)


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
):
    """Build a duck-typed stand-in for telegram.Update.

    Covers what BotCommands actually reads: update.effective_chat.{id,title,type},
    update.effective_user.{id,first_name}, update.message.{message_thread_id,
    sender_chat,reply_text}.
    """
    effective_chat = (
        SimpleNamespace(id=chat_id, title=title, type=chat_type) if has_chat else None
    )
    effective_user = (
        SimpleNamespace(id=user_id, first_name=first_name) if first_name is not None else None
    )
    message = (
        FakeMessage(message_thread_id=message_thread_id, sender_chat_id=sender_chat_id)
        if has_message
        else None
    )
    return SimpleNamespace(
        effective_chat=effective_chat,
        effective_user=effective_user,
        message=message,
    )


def make_context(args=None, bot=None):
    """Build a duck-typed stand-in for telegram.ext.ContextTypes.DEFAULT_TYPE."""
    return SimpleNamespace(args=args or [], bot=bot)
