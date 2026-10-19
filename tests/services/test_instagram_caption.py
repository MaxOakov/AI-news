from app.services.instagram_caption import MAX_CAPTION_LENGTH, MAX_HASHTAGS, build_caption, find_hashtags, has_hashtag

EXTRA = ["#аніме", "#анімеукраїнською", "#анімеукраїна", "#українаніме", "#анімеоналайн"]


def test_has_hashtag_matches_case_insensitively():
    assert has_hashtag("Новий реліз #команда_anikoe!", "#Команда_AniKoe")


def test_has_hashtag_ignores_longer_tags_and_glued_hashes():
    assert not has_hashtag("#Команда_AniKoe2", "#Команда_AniKoe")
    assert not has_hashtag("abc#Команда_AniKoe", "#Команда_AniKoe")
    assert not has_hashtag(None, "#Команда_AniKoe")


def test_find_hashtags_handles_cyrillic():
    assert find_hashtags("Текст #аніме, #Команда_AniKoe.") == ["#аніме", "#Команда_AniKoe"]


def test_build_caption_keeps_trigger_tag_and_appends_extras_after_text():
    caption = build_caption("Нова серія!\n#Команда_AniKoe", EXTRA)

    assert caption == "Нова серія!\n#Команда_AniKoe\n\n" + " ".join(EXTRA)


def test_build_caption_skips_tags_already_in_text():
    caption = build_caption("Пост #Аніме", EXTRA)

    assert [t.casefold() for t in find_hashtags(caption)].count("#аніме") == 1
    assert caption.endswith("#анімеукраїнською #анімеукраїна #українаніме #анімеоналайн")


def test_build_caption_respects_hashtag_limit():
    text = " ".join(f"#tag{i}" for i in range(MAX_HASHTAGS - 2))

    caption = build_caption(text, EXTRA)

    assert len(find_hashtags(caption)) == MAX_HASHTAGS
    assert caption.endswith("#аніме #анімеукраїнською")


def test_build_caption_truncates_long_text_but_keeps_extras():
    caption = build_caption("а" * 5000, EXTRA)

    assert len(caption) == MAX_CAPTION_LENGTH
    assert caption.endswith(" ".join(EXTRA))
    assert "…\n\n" in caption


def test_build_caption_without_text_is_just_the_tags():
    assert build_caption("", EXTRA) == " ".join(EXTRA)
