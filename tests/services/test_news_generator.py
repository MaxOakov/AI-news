def test_generate_happy_path(news_generator, fake_genai_client, sample_article, prompt_repository):
    prompt_repository.save_custom(str(sample_article.chat_id or "1"), "T:{title} S:{summary} U:{url}")
    fake_genai_client.set_response("Rewritten article")

    result = news_generator.generate(sample_article, chat_id="1")

    assert result == "Rewritten article"
    model, prompt = fake_genai_client.calls[0]
    assert model == "fake-model"
    assert sample_article.title in prompt
    assert sample_article.summary in prompt
    assert sample_article.url in prompt


def test_generate_with_no_chat_id_uses_default_prompt(
    news_generator, fake_genai_client, sample_article, prompt_repository, tmp_path, monkeypatch
):
    import app.db.prompt_repository as prompt_repository_module

    (tmp_path / "prompt.txt").write_text("Default: {title}|{summary}|{url}", encoding="utf-8")
    monkeypatch.setattr(prompt_repository_module, "_PROJECT_ROOT", tmp_path)

    news_generator.generate(sample_article, chat_id=None)
    _, prompt = fake_genai_client.calls[0]
    assert prompt.startswith("Default:")


def test_generate_retries_then_succeeds(news_generator, fake_genai_client, sample_article):
    fake_genai_client.fail_times(1)
    fake_genai_client.set_response("Recovered")

    result = news_generator.generate(sample_article, chat_id="1")

    assert result == "Recovered"
    assert len(fake_genai_client.calls) == 2


def test_generate_exhausted_returns_fallback_text(news_generator, fake_genai_client, sample_article):
    fake_genai_client.fail_times(99)

    result = news_generator.generate(sample_article, chat_id="1")

    assert result == "⚠️ Gemini не повернув текст."


def test_generate_empty_candidates_then_success(news_generator, fake_genai_client, sample_article):
    fake_genai_client.return_empty_candidates(2)
    fake_genai_client.set_response("Finally")

    result = news_generator.generate(sample_article, chat_id="1")

    assert result == "Finally"
    assert len(fake_genai_client.calls) == 3
