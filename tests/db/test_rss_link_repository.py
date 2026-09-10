def test_save_normalizes_and_upserts(rss_link_repository):
    rss_link_repository.save("1", "  https://feed.example/rss  ")
    docs = rss_link_repository._db.rss_links.docs
    assert len(docs) == 1
    assert docs[0]["url"] == "https://feed.example/rss"
    assert docs[0]["is_active"] is True


def test_save_same_url_twice_does_not_duplicate(rss_link_repository):
    rss_link_repository.save("1", "https://feed.example/rss")
    rss_link_repository.save("1", "https://feed.example/rss")
    assert len(rss_link_repository._db.rss_links.docs) == 1


def test_get_for_chat_filters_by_chat_and_active(rss_link_repository):
    rss_link_repository.save("1", "https://a")
    rss_link_repository.save("2", "https://b")
    links = rss_link_repository.get_for_chat("1")
    assert [link["url"] for link in links] == ["https://a"]


def test_get_all_returns_every_active_link(rss_link_repository):
    rss_link_repository.save("1", "https://a")
    rss_link_repository.save("2", "https://b")
    links = rss_link_repository.get_all()
    assert {link["url"] for link in links} == {"https://a", "https://b"}


def test_remove_deletes_matching_link(rss_link_repository):
    rss_link_repository.save("1", "https://a")
    rss_link_repository.remove("1", "https://a")
    assert rss_link_repository.get_for_chat("1") == []


def test_remove_nonexistent_link_does_not_raise(rss_link_repository):
    rss_link_repository.remove("1", "https://does-not-exist")
