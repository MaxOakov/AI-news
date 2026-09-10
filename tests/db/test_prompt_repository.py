import app.db.prompt_repository as prompt_repository_module


def test_get_default_text_reads_prompt_txt(prompt_repository, tmp_path, monkeypatch):
    (tmp_path / "prompt.txt").write_text("Hello {title}", encoding="utf-8")
    monkeypatch.setattr(prompt_repository_module, "_PROJECT_ROOT", tmp_path)

    assert prompt_repository.get_default_text() == "Hello {title}"


def test_get_default_text_falls_back_to_legacy_file(prompt_repository, tmp_path, monkeypatch):
    (tmp_path / "prompt_anikoe.txt").write_text("Legacy {title}", encoding="utf-8")
    monkeypatch.setattr(prompt_repository_module, "_PROJECT_ROOT", tmp_path)

    assert prompt_repository.get_default_text() == "Legacy {title}"


def test_get_default_text_falls_back_to_hardcoded_default(prompt_repository, tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_repository_module, "_PROJECT_ROOT", tmp_path)

    text = prompt_repository.get_default_text()
    assert "{title}" in text and "{summary}" in text and "{url}" in text


def test_save_custom_strips_and_stores(prompt_repository):
    prompt_repository.save_custom("1", "  my custom prompt {title}  ")
    doc = prompt_repository._db.chat_prompts.docs[0]
    assert doc["custom_prompt"] == "my custom prompt {title}"


def test_save_custom_blank_prompt_is_a_no_op(prompt_repository):
    result = prompt_repository.save_custom("1", "   ")
    assert result is None
    assert prompt_repository._db.chat_prompts.docs == []


def test_get_custom_returns_none_when_not_set(prompt_repository):
    assert prompt_repository.get_custom("1") is None


def test_get_custom_returns_stripped_value(prompt_repository):
    prompt_repository.save_custom("1", "custom text")
    assert prompt_repository.get_custom("1") == "custom text"


def test_reset_custom_removes_stored_prompt(prompt_repository):
    prompt_repository.save_custom("1", "custom text")
    prompt_repository.reset_custom("1")
    assert prompt_repository.get_custom("1") is None


def test_get_for_chat_prefers_custom_over_default(prompt_repository, tmp_path, monkeypatch):
    (tmp_path / "prompt.txt").write_text("Default {title}", encoding="utf-8")
    monkeypatch.setattr(prompt_repository_module, "_PROJECT_ROOT", tmp_path)

    prompt_repository.save_custom("1", "Custom {title}")
    assert prompt_repository.get_for_chat("1") == "Custom {title}"


def test_get_for_chat_falls_back_to_default_when_no_custom(prompt_repository, tmp_path, monkeypatch):
    (tmp_path / "prompt.txt").write_text("Default {title}", encoding="utf-8")
    monkeypatch.setattr(prompt_repository_module, "_PROJECT_ROOT", tmp_path)

    assert prompt_repository.get_for_chat("1") == "Default {title}"
