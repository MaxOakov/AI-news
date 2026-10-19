"""Who may change a chat's settings: its creator and administrators."""
from telegram import Update
from telegram.ext import ContextTypes

ADMIN_STATUSES = {"creator", "administrator"}


async def is_chat_admin(bot, chat_id, user_id) -> bool:
    """Whether `user_id` is the creator or an administrator of `chat_id`
    (False if the Bot API can't tell, e.g. the bot isn't in that chat)."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception as e:
        print(f"⚠️ Не вдалося перевірити права адміністратора: {e}")
        return False
    return member.status in ADMIN_STATUSES


async def require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if the sender may run a state-changing command here.

    Always True in private chats (the sender is the only member).
    In groups/supergroups, only the chat's creator/administrators (or
    an anonymous-admin post, which Telegram sends with no
    effective_user but a message.sender_chat matching the chat itself)
    may proceed; anyone else gets a warning reply and False.
    """
    chat = update.effective_chat
    if chat is None:
        return False
    if chat.type == "private":
        return True

    message = update.message
    sender_chat = getattr(message, "sender_chat", None) if message is not None else None
    if sender_chat is not None and sender_chat.id == chat.id:
        return True  # anonymous admin post

    user = update.effective_user
    if user is not None and await is_chat_admin(context.bot, chat.id, user.id):
        return True

    if message is not None:
        await message.reply_text("⛔ Ця команда доступна лише адміністраторам чату.")
    return False
