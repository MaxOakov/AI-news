from app.db.instagram_post_repository import STATUS_FAILED, STATUS_PENDING, STATUS_PUBLISHED


def test_claim_succeeds_once_per_post(instagram_post_repository, fake_db_handle):
    assert instagram_post_repository.claim("-100", "42") is True
    assert instagram_post_repository.claim("-100", "42") is False

    [doc] = fake_db_handle.instagram_posts.docs
    assert doc["status"] == STATUS_PENDING


def test_same_post_key_in_another_chat_is_a_different_post(instagram_post_repository):
    assert instagram_post_repository.claim("-100", "42") is True
    assert instagram_post_repository.claim("-200", "42") is True


def test_mark_published_and_failed(instagram_post_repository, fake_db_handle):
    instagram_post_repository.claim("-100", "1")
    instagram_post_repository.claim("-100", "2")

    instagram_post_repository.mark_published("-100", "1", "ig-1")
    instagram_post_repository.mark_failed("-100", "2", "boom")

    docs = {d["post_key"]: d for d in fake_db_handle.instagram_posts.docs}
    assert docs["1"]["status"] == STATUS_PUBLISHED and docs["1"]["ig_media_id"] == "ig-1"
    assert docs["2"]["status"] == STATUS_FAILED and docs["2"]["error"] == "boom"
    # A failed post stays claimed, so it isn't retried behind the admin's back.
    assert instagram_post_repository.claim("-100", "2") is False


def test_ensure_indexes(instagram_post_repository, fake_db_handle):
    instagram_post_repository.ensure_indexes()

    assert fake_db_handle.instagram_posts.indexes == [[("chat_id", 1), ("post_key", 1)]]
