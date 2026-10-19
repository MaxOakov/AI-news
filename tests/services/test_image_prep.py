import io

import pytest
from PIL import Image

from app.services.image_prep import MAX_ASPECT_RATIO, MAX_WIDTH, MIN_ASPECT_RATIO, prepare_for_instagram


def _image_bytes(width, height, mode="RGB", fmt="PNG"):
    out = io.BytesIO()
    Image.new(mode, (width, height), "red" if mode == "RGB" else None).save(out, format=fmt)
    return out.getvalue()


def _open(data):
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_output_is_jpeg():
    assert _open(prepare_for_instagram(_image_bytes(800, 800))).format == "JPEG"


def test_converts_transparent_png():
    assert _open(prepare_for_instagram(_image_bytes(500, 500, mode="RGBA"))).mode == "RGB"


def test_square_image_keeps_its_size():
    assert _open(prepare_for_instagram(_image_bytes(1000, 1000))).size == (1000, 1000)


def test_too_tall_image_is_padded_to_4_5():
    image = _open(prepare_for_instagram(_image_bytes(400, 1000)))

    assert image.size == (800, 1000)
    assert image.width / image.height == pytest.approx(MIN_ASPECT_RATIO)
    assert image.getpixel((10, 500)) == (0, 0, 0)  # padding, not stretched picture


def test_too_wide_image_is_padded_to_1_91():
    image = _open(prepare_for_instagram(_image_bytes(1000, 200)))

    assert image.width == 1000
    assert image.width / image.height == pytest.approx(MAX_ASPECT_RATIO, rel=0.01)


def test_large_image_is_scaled_down():
    image = _open(prepare_for_instagram(_image_bytes(2880, 2880)))

    assert image.size == (MAX_WIDTH, MAX_WIDTH)
