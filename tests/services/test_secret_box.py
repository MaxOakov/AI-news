import pytest

from app.services.secret_box import SecretBox, SecretBoxError, generate_key


def test_round_trip():
    box = SecretBox([generate_key()])

    token = box.encrypt("EAAB-secret-token", "-100:instagram_token")

    assert "EAAB-secret-token" not in token
    assert box.decrypt(token, "-100:instagram_token") == "EAAB-secret-token"


def test_same_value_encrypts_differently_each_time():
    box = SecretBox([generate_key()])

    assert box.encrypt("x", "c") != box.encrypt("x", "c")


def test_value_is_bound_to_its_chat_and_field():
    box = SecretBox([generate_key()])
    token = box.encrypt("secret", "-100:instagram_token")

    with pytest.raises(SecretBoxError):
        box.decrypt(token, "-200:instagram_token")  # copied to another chat
    with pytest.raises(SecretBoxError):
        box.decrypt(token, "-100:r2_secret_access_key")  # or another field


def test_wrong_key_cannot_decrypt():
    token = SecretBox([generate_key()]).encrypt("secret", "c")

    with pytest.raises(SecretBoxError):
        SecretBox([generate_key()]).decrypt(token, "c")


def test_tampered_value_is_rejected():
    box = SecretBox([generate_key()])
    token = box.encrypt("secret", "c")
    tampered = token[:-6] + ("A" if token[-6] != "A" else "B") + token[-5:]

    with pytest.raises(SecretBoxError):
        box.decrypt(tampered, "c")
    with pytest.raises(SecretBoxError):
        box.decrypt("not a token at all", "c")


def test_key_rotation_keeps_old_values_readable():
    old_key, new_key = generate_key(), generate_key()
    old_token = SecretBox([old_key]).encrypt("secret", "c")

    rotated = SecretBox([new_key, old_key])

    assert rotated.decrypt(old_token, "c") == "secret"
    # New values are encrypted with the first (new) key only.
    with pytest.raises(SecretBoxError):
        SecretBox([old_key]).decrypt(rotated.encrypt("fresh", "c"), "c")


def test_from_env():
    key1, key2 = generate_key(), generate_key()

    assert SecretBox.from_env(None) is None
    assert SecretBox.from_env("  ") is None
    box = SecretBox.from_env(f" {key1} , {key2} ")
    assert box.decrypt(SecretBox([key2]).encrypt("v", "c"), "c") == "v"


@pytest.mark.parametrize("value", ["not-a-key", "short", ","])
def test_invalid_keys_raise_value_error(value):
    keys = [k for k in value.split(",") if k]
    with pytest.raises(ValueError):
        SecretBox(keys)
