from unittest.mock import AsyncMock, MagicMock

from freezegun import freeze_time

from app.scheduler import SchedulerService, get_kyiv_timezone


def test_get_kyiv_timezone_falls_back_to_utc_when_zoneinfo_unavailable(monkeypatch):
    from datetime import timezone

    def boom(name):
        raise Exception("tzdata not installed")

    monkeypatch.setattr("app.scheduler.ZoneInfo", boom)
    assert get_kyiv_timezone() == timezone.utc


def _capturing_create_task(created):
    """Stand-in for asyncio.create_task that records + closes the coroutine
    (so it never actually runs, and pytest doesn't warn about it being
    unawaited) and returns a dummy Task-like object supporting
    add_done_callback, matching what _scheduled_tick calls next.
    """

    def _create_task(coro):
        created.append(coro)
        coro.close()
        return MagicMock()

    return _create_task


# --------------------------------------------------------------------------
# trigger_now / chat_id forwarding
# --------------------------------------------------------------------------
async def test_trigger_now_forwards_chat_id(scheduler_service):
    scheduler_service._pipeline.run = AsyncMock(return_value=None)
    await scheduler_service.trigger_now(chat_id="1")
    scheduler_service._pipeline.run.assert_awaited_once_with(chat_id="1")


async def test_trigger_now_forwards_none_for_all_chats(scheduler_service):
    scheduler_service._pipeline.run = AsyncMock(return_value=None)
    await scheduler_service.trigger_now()
    scheduler_service._pipeline.run.assert_awaited_once_with(chat_id=None)


# --------------------------------------------------------------------------
# Overlap guard
# --------------------------------------------------------------------------
async def test_overlap_guard_blocks_concurrent_trigger(scheduler_service):
    scheduler_service._pipeline.run = AsyncMock(return_value=None)
    scheduler_service._running = True

    result = await scheduler_service.trigger_now()

    assert result is False
    scheduler_service._pipeline.run.assert_not_awaited()
    assert scheduler_service._running is True  # untouched, guard returns before the flip


async def test_running_flag_reset_after_success(scheduler_service):
    scheduler_service._pipeline.run = AsyncMock(return_value=None)
    result = await scheduler_service.trigger_now()
    assert result is True
    assert scheduler_service._running is False


# --------------------------------------------------------------------------
# 503 retry behavior
# --------------------------------------------------------------------------
async def test_503_error_retries_then_succeeds(scheduler_service):
    calls = {"n": 0}

    async def flaky_run(chat_id=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("HTTP 503 Service Unavailable")

    scheduler_service._pipeline.run = flaky_run
    result = await scheduler_service.trigger_now()

    assert result is True
    assert calls["n"] == 2


async def test_503_error_exhausted_returns_false_and_resets_running(scheduler_service):
    async def always_503(chat_id=None):
        raise RuntimeError("HTTP 503 Service Unavailable")

    scheduler_service._pipeline.run = always_503
    result = await scheduler_service.trigger_now()

    assert result is False
    assert scheduler_service._running is False


async def test_non_503_error_does_not_retry(scheduler_service):
    calls = {"n": 0}

    async def always_fails(chat_id=None):
        calls["n"] += 1
        raise ValueError("boom")

    scheduler_service._pipeline.run = always_fails
    result = await scheduler_service.trigger_now()

    assert result is False
    assert calls["n"] == 1


# --------------------------------------------------------------------------
# Day/night gating + per-tick overlap guard
# --------------------------------------------------------------------------
async def test_scheduled_tick_starts_job_during_active_hours(scheduler_service, monkeypatch):
    created = []
    monkeypatch.setattr(
        "app.scheduler.asyncio.create_task", _capturing_create_task(created)
    )

    with freeze_time("2026-01-15 14:00:00", tz_offset=0):
        # 14:00 UTC; Kyiv is UTC+2 in January -> 16:00 local, inside range(8,23)
        result = scheduler_service._scheduled_tick()

    assert result is True
    assert len(created) == 1


async def test_scheduled_tick_skips_outside_active_hours(scheduler_service, monkeypatch):
    created = []
    monkeypatch.setattr(
        "app.scheduler.asyncio.create_task", _capturing_create_task(created)
    )

    with freeze_time("2026-01-15 00:30:00", tz_offset=0):
        # 00:30 UTC -> 02:30 Kyiv, outside range(8, 23)
        result = scheduler_service._scheduled_tick()

    assert result is False
    assert created == []


async def test_scheduled_tick_skips_when_already_running(scheduler_service, monkeypatch):
    created = []
    monkeypatch.setattr(
        "app.scheduler.asyncio.create_task", _capturing_create_task(created)
    )
    scheduler_service._running = True

    with freeze_time("2026-01-15 14:00:00", tz_offset=0):
        result = scheduler_service._scheduled_tick()

    assert result is False
    assert created == []


async def test_custom_active_hours_range(news_pipeline, monkeypatch):
    scheduler = SchedulerService(news_pipeline, active_hours=range(0, 24))
    created = []
    monkeypatch.setattr(
        "app.scheduler.asyncio.create_task", _capturing_create_task(created)
    )

    with freeze_time("2026-01-15 00:30:00", tz_offset=0):
        result = scheduler._scheduled_tick()

    assert result is True
    assert len(created) == 1


# --------------------------------------------------------------------------
# _handle_task_exception never lets an exception escape a done_callback
# --------------------------------------------------------------------------
def test_handle_task_exception_cancelled_task(scheduler_service):
    class FakeTask:
        def cancelled(self):
            return True

    scheduler_service._handle_task_exception(FakeTask())  # must not raise


def test_handle_task_exception_result_raises_cancelled_error(scheduler_service):
    import asyncio

    class FakeTask:
        def cancelled(self):
            return False

        def result(self):
            raise asyncio.CancelledError()

    scheduler_service._handle_task_exception(FakeTask())  # must not raise


def test_handle_task_exception_swallows_generic_exception(scheduler_service):
    class FakeTask:
        def cancelled(self):
            return False

        def result(self):
            raise ValueError("boom")

    scheduler_service._handle_task_exception(FakeTask())  # must not raise


def test_handle_task_exception_swallows_503_exception(scheduler_service):
    class FakeTask:
        def cancelled(self):
            return False

        def result(self):
            raise RuntimeError("HTTP 503")

    scheduler_service._handle_task_exception(FakeTask())  # must not raise
