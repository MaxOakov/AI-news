"""Building an Instagram caption from a Telegram post's text."""
import re

# Instagram's own limits for a post caption.
MAX_CAPTION_LENGTH = 2200
MAX_HASHTAGS = 30

# A hashtag as Telegram and Instagram see it: `#` not glued to a preceding
# word character, then letters/digits/underscores (Cyrillic included).
_HASHTAG_RE = re.compile(r"(?<!\w)#\w+")


_SINGLE_HASHTAG_RE = re.compile(r"#\w+")


def normalize_hashtag(value: str) -> str | None:
    """`value` as a hashtag (adding the `#` if it's missing), or None if
    it isn't one (e.g. contains spaces or punctuation)."""
    value = value.strip()
    if not value.startswith("#"):
        value = f"#{value}"
    return value if _SINGLE_HASHTAG_RE.fullmatch(value) else None


def find_hashtags(text: str | None) -> list[str]:
    return _HASHTAG_RE.findall(text or "")


def has_hashtag(text: str | None, hashtag: str) -> bool:
    """Whether `text` contains exactly `hashtag` (case-insensitive), not
    just a longer tag that starts with it."""
    wanted = hashtag.casefold()
    return any(tag.casefold() == wanted for tag in find_hashtags(text))


def has_any_hashtag(text: str | None, hashtags) -> bool:
    """Whether `text` contains any of `hashtags` (each matched as has_hashtag does)."""
    wanted = {hashtag.casefold() for hashtag in hashtags}
    return any(tag.casefold() in wanted for tag in find_hashtags(text))


def build_caption(text: str | None, extra_hashtags: list[str]) -> str:
    """The post's text with `extra_hashtags` appended after it.

    Tags already in the text aren't repeated, and no more are added than
    Instagram's 30-hashtag limit allows. A text too long for Instagram is
    cut (with "…") so the appended tags still fit.
    """
    text = (text or "").strip()
    present = {tag.casefold() for tag in find_hashtags(text)}
    room = MAX_HASHTAGS - len(present)

    extras = []
    for tag in extra_hashtags:
        if room <= 0:
            break
        if tag.casefold() not in present:
            extras.append(tag)
            present.add(tag.casefold())
            room -= 1

    tail = " ".join(extras)
    if not tail:
        return text[:MAX_CAPTION_LENGTH]
    if not text:
        return tail

    separator = "\n\n"
    max_text = MAX_CAPTION_LENGTH - len(separator) - len(tail)
    if len(text) > max_text:
        text = text[: max_text - 1].rstrip() + "…"
    return f"{text}{separator}{tail}"
