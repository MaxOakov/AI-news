"""The setup checklist (/setup, and after a chat's first /start): what's
configured for a chat's Telegram news, and for its optional Instagram
posting. Rendering only; SetupCommands gathers the data."""
from dataclasses import dataclass

from app.models import InstagramSettings

OK = "✅"
MISSING = "❌"

PRIVATE_SETUP_COMMANDS = (
    "Команди налаштування (надсилайте сюди — повідомлення з ключами я одразу видаляю):\n"
    "/ig_account <ID акаунта Instagram> <токен доступу>\n"
    "/ig_r2 <Account ID> <Access Key ID> <Secret Access Key> <бакет> <публічний URL бакета>\n"
    "/ig_track <хештеги через пробіл> — пости з будь-яким із них підуть в Instagram\n"
    "/ig_tags <хештеги через пробіл> — додаються в кінець підпису (/ig_tags off — прибрати)\n"
    "/ig_topic all | news — брати пости з усього чату або з гілки новин "
    "(щоб вибрати іншу гілку, надішліть /ig_topic у ній, у групі)\n"
    "/ig_reset — видалити всі налаштування Instagram цього чату"
)


@dataclass
class ChecklistData:
    chat_name: str
    is_group: bool
    is_active: bool
    feed_count: int
    topic_id: int | None
    settings: InstagramSettings | None
    can_store_secrets: bool
    # A live check of the stored Instagram token failed with this error.
    account_error: str | None = None


def render_checklist(data: ChecklistData, in_private: bool) -> str:
    """The checklist text. `in_private`: shown in a private chat with the
    bot, where secrets may be entered (else: a group, pointed there)."""
    lines = [f"⚙️ Налаштування чату «{data.chat_name}»", "", "📰 Новини в Telegram"]
    lines.append(f"{OK} Розсилку новин увімкнено" if data.is_active else f"{MISSING} Розсилку новин вимкнено — /start")
    lines.append(
        f"{OK} RSS-стрічок: {data.feed_count}" if data.feed_count
        else f"{MISSING} Немає жодної RSS-стрічки — /addrss <посилання>"
    )
    if data.is_group:
        lines.append(
            f"{OK} Гілка для новин: {data.topic_id}" if data.topic_id is not None
            else f"{MISSING} Гілку не вибрано, новини йдуть у загальний чат (необов'язково) — /settopic у потрібній гілці"
        )
    if not data.is_active:
        lines.append("→ Щоб бот публікував новини, увімкніть розсилку: /start.")
    elif not data.feed_count:
        lines.append("→ Щоб бот публікував новини, додайте хоча б одну RSS-стрічку.")
    else:
        lines.append("→ Новини працюють.")

    lines += ["", "📸 Instagram (необов'язково)"]
    lines += _instagram_lines(data)
    lines.append("")
    if in_private:
        lines.append(PRIVATE_SETUP_COMMANDS)
    else:
        lines.append(
            "🔐 Токен Instagram і ключі R2 вводяться лише в особистих повідомленнях боту — "
            "натисніть кнопку нижче. Хештеги й гілку можна задати й тут: /ig_track, /ig_tags, "
            "/ig_topic (у потрібній гілці)."
        )
    return "\n".join(lines)


def _instagram_lines(data: ChecklistData) -> list[str]:
    s = data.settings or InstagramSettings(chat_id="")
    lines = []
    if not data.can_store_secrets:
        lines.append(
            f"{MISSING} На сервері не задано ключ шифрування SECRETS_ENCRYPTION_KEY — без нього токен "
            "і ключі не можна зберегти. Зверніться до власника бота."
        )
    if s.secrets_unreadable:
        lines.append(f"{MISSING} Збережені ключі не вдається розшифрувати (змінився ключ шифрування?) — введіть їх знову.")

    if data.account_error:
        lines.append(f"{MISSING} Акаунт Instagram @{s.instagram_username}: {data.account_error} — /ig_account")
    elif s.has_account:
        lines.append(f"{OK} Акаунт Instagram: @{s.instagram_username}")
    else:
        lines.append(f"{MISSING} Акаунт Instagram — /ig_account")

    lines.append(f"{OK} Сховище Cloudflare R2: бакет {s.r2_bucket}" if s.has_r2 else f"{MISSING} Сховище Cloudflare R2 — /ig_r2")
    lines.append(
        f"{OK} Хештеги для відбору постів: {' '.join(s.trigger_hashtags)}" if s.trigger_hashtags
        else f"{MISSING} Хештеги для відбору постів — /ig_track"
    )
    topic_label, source = _instagram_topic(s, data.topic_id)
    if data.is_group:
        lines.append(f"{OK} Гілка для Instagram: {topic_label}")
    lines.append(
        f"{OK} Додаткові хештеги в підпис: {' '.join(s.extra_hashtags)}" if s.extra_hashtags
        else f"{MISSING} Додаткові хештеги в підпис (необов'язково) — /ig_tags"
    )
    if data.is_group and s.instagram_topic_id is not None and s.instagram_topic_id != data.topic_id:
        lines.append(
            f"ℹ️ Новини бота йдуть в іншу гілку, тож в Instagram потраплять лише пости, написані в гілці {topic_label}."
        )

    if not s.is_ready or data.account_error:
        lines.append("→ Instagram вимкнено. Новини в Telegram працюють і без нього.")
    elif not data.is_active:
        lines.append("→ Instagram налаштовано, але він працює, лише поки чат підписаний на новини — /start.")
    else:
        hashtags = " або ".join(s.trigger_hashtags)
        lines.append(f"→ Пости {source} з {hashtags} публікуються в Instagram @{s.instagram_username}.")
    return lines


def _instagram_topic(s: InstagramSettings, news_topic_id: int | None) -> tuple[str, str]:
    """Where posts are taken from: (label for the checklist line, "з …" for the status line)."""
    if s.instagram_all_topics:
        return "увесь чат", "з усього чату"
    if s.instagram_topic_id is not None:
        label = f"«{s.instagram_topic_name}»" if s.instagram_topic_name else str(s.instagram_topic_id)
        return label, f"з гілки {label}"
    if news_topic_id is not None:
        return f"та сама, що й для новин ({news_topic_id})", "з гілки новин"
    return "увесь чат (гілку для новин не вибрано)", "з чату"
