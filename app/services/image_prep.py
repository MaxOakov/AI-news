"""Converting a Telegram photo into an image Instagram will accept."""
import io

from PIL import Image

# Instagram feed photos must be JPEG with a width/height ratio between
# 4:5 (portrait) and 1.91:1 (landscape); it rejects anything outside that.
MIN_ASPECT_RATIO = 4 / 5
MAX_ASPECT_RATIO = 1.91
MAX_WIDTH = 1440
_PAD_COLOR = (0, 0, 0)
_JPEG_QUALITY = 90


def prepare_for_instagram(data: bytes) -> bytes:
    """Return `data` as a JPEG, padded (not cropped, so nothing on the
    picture is lost) to fit Instagram's aspect-ratio range and scaled down
    to at most MAX_WIDTH pixels wide."""
    with Image.open(io.BytesIO(data)) as source:
        image = source.convert("RGB")

    width, height = image.size
    ratio = width / height
    if ratio < MIN_ASPECT_RATIO:
        image = _pad(image, round(height * MIN_ASPECT_RATIO), height)
    elif ratio > MAX_ASPECT_RATIO:
        image = _pad(image, width, round(width / MAX_ASPECT_RATIO))

    if image.width > MAX_WIDTH:
        new_height = round(image.height * MAX_WIDTH / image.width)
        image = image.resize((MAX_WIDTH, new_height), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=_JPEG_QUALITY)
    return out.getvalue()


def _pad(image: Image.Image, width: int, height: int) -> Image.Image:
    canvas = Image.new("RGB", (width, height), _PAD_COLOR)
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return canvas
