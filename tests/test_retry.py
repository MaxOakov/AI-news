import pytest

from app.retry import retry, retry_async


# --------------------------------------------------------------------------
# retry (sync)
# --------------------------------------------------------------------------
def test_retry_happy_path_never_calls_callbacks():
    calls = []
    retry_calls = []

    @retry(max_retries=3, on_retry=lambda *a: retry_calls.append(a))
    def func():
        calls.append(1)
        return "ok"

    assert func() == "ok"
    assert calls == [1]
    assert retry_calls == []


def test_retry_succeeds_after_transient_failures():
    attempts = {"n": 0}
    retry_log = []

    @retry(
        max_retries=3,
        delay=1,
        on_retry=lambda exc, attempt, total, *a, **kw: retry_log.append((attempt, total)),
    )
    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert flaky() == "ok"
    assert attempts["n"] == 3
    assert retry_log == [(1, 3), (2, 3)]


def test_retry_exhausted_without_on_failure_reraises():
    @retry(max_retries=2, delay=0)
    def always_fails():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        always_fails()


def test_retry_exhausted_with_on_failure_returns_fallback():
    @retry(max_retries=2, delay=0, on_failure=lambda exc, *a, **kw: "fallback")
    def always_fails():
        raise ValueError("nope")

    assert always_fails() == "fallback"


def test_retry_only_catches_listed_exception_types():
    calls = {"n": 0}

    @retry(max_retries=3, delay=0, exceptions=(ValueError,))
    def raises_type_error():
        calls["n"] += 1
        raise TypeError("not a value error")

    with pytest.raises(TypeError):
        raises_type_error()
    assert calls["n"] == 1  # never retried


def test_retry_forwards_self_for_instance_methods():
    seen = []

    class Thing:
        @retry(
            max_retries=2,
            delay=0,
            on_retry=lambda exc, attempt, total, self, *a: seen.append(self),
            on_failure=lambda exc, self, *a: "fallback",
        )
        def method(self):
            raise ValueError("boom")

    thing = Thing()
    assert thing.method() == "fallback"
    # on_retry fires on every failed attempt (including the last), so `seen`
    # has one entry per attempt; what matters here is each is `thing` itself.
    assert seen and all(s is thing for s in seen)


def test_retry_skips_sleep_after_last_attempt(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("app.retry.time.sleep", lambda d: sleep_calls.append(d))

    @retry(max_retries=3, delay=5, on_failure=lambda exc, *a, **kw: None)
    def always_fails():
        raise ValueError("nope")

    always_fails()
    # 3 attempts -> sleeps after attempt 1 and 2, not after the final attempt 3
    assert sleep_calls == [5, 5]


# --------------------------------------------------------------------------
# retry_async
# --------------------------------------------------------------------------
async def test_retry_async_happy_path():
    @retry_async(max_retries=3)
    async def func():
        return "ok"

    assert await func() == "ok"


async def test_retry_async_succeeds_after_transient_failures():
    attempts = {"n": 0}
    retry_log = []

    @retry_async(
        max_retries=3,
        delay=1,
        on_retry=lambda exc, attempt, total, *a, **kw: retry_log.append((attempt, total)),
    )
    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ValueError("boom")
        return "ok"

    assert await flaky() == "ok"
    assert retry_log == [(1, 3)]


async def test_retry_async_exhausted_without_on_failure_reraises():
    @retry_async(max_retries=2, delay=0)
    async def always_fails():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        await always_fails()


async def test_retry_async_exhausted_with_on_failure_returns_fallback():
    @retry_async(max_retries=2, delay=0, on_failure=lambda exc, *a, **kw: "fallback")
    async def always_fails():
        raise ValueError("nope")

    assert await always_fails() == "fallback"


async def test_retry_async_exceptions_filtering():
    @retry_async(max_retries=3, delay=0, exceptions=(ValueError,))
    async def raises_type_error():
        raise TypeError("nope")

    with pytest.raises(TypeError):
        await raises_type_error()


async def test_retry_async_forwards_self_for_instance_methods():
    seen = []

    class Thing:
        @retry_async(
            max_retries=2,
            delay=0,
            on_retry=lambda exc, attempt, total, self, *a: seen.append(self),
            on_failure=lambda exc, self, *a: "fallback",
        )
        async def method(self):
            raise ValueError("boom")

    thing = Thing()
    assert await thing.method() == "fallback"
    assert seen and all(s is thing for s in seen)
