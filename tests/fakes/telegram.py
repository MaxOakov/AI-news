"""Fakes for the Telegram side: a stand-in bot for TelegramBot.send_message,
and duck-typed Update/Context doubles for BotCommands handler tests.

Real python-telegram-bot Update/Chat/Message objects are effectively-frozen
and awkward to construct directly, so these are plain duck-typed objects
exposing only the attributes the app actually reads.
"""
from types import SimpleNamespace


class FakeTGBot:
    """Stand-in for telegram.Bot, as assigned to TelegramBot.bot in tests."""

    def __init__(self):
        self.sent: list[dict] = []
        self._attempts = 0
        self._fail_times = 0
        self._exception_factory = lambda: RuntimeError("simulated Telegram failure")

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


class FakeMessage:
    """Stand-in for telegram.Message, recording every reply_text call."""

    def __init__(self, message_thread_id=None):
        self.message_thread_id = message_thread_id
        self.replies: list[str] = []

    async def reply_text(self, text, *args, **kwargs):
        self.replies.append(text)


def make_update(
    chat_id="123",
    chat_type="private",
    title=None,
    first_name="Test User",
    message_thread_id=None,
    has_chat=True,
    has_message=True,
):
    """Build a duck-typed stand-in for telegram.Update.

    Covers what BotCommands actually reads: update.effective_chat.{id,title,type},
    update.effective_user.first_name, update.message.{message_thread_id,reply_text}.
    """
    effective_chat = (
        SimpleNamespace(id=chat_id, title=title, type=chat_type) if has_chat else None
    )
    effective_user = SimpleNamespace(first_name=first_name) if first_name is not None else None
    message = FakeMessage(message_thread_id=message_thread_id) if has_message else None
    return SimpleNamespace(
        effective_chat=effective_chat,
        effective_user=effective_user,
        message=message,
    )


def make_context(args=None):
    """Build a duck-typed stand-in for telegram.ext.ContextTypes.DEFAULT_TYPE."""
    return SimpleNamespace(args=args or [])
