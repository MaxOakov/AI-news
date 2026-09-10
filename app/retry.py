"""Shared retry helpers.

Several modules (mongo.py, rss_parser.py, news_generator.py, telegram_bot.py)
each hand-rolled the same "try N times, sleep between attempts, log on every
failure, do something special on the last one" loop. These two decorators
replace all of them with one implementation, while still letting each call
site keep its own log messages and fallback behaviour via callbacks.
"""
import asyncio
import time
from functools import wraps


def retry(max_retries=3, delay=1, exceptions=(Exception,), on_retry=None, on_failure=None):
    """Retry a synchronous function on failure.

    Args:
        max_retries: total number of attempts (matches the previous
            `for retry_count in range(max_retries)` call sites).
        delay: seconds to sleep between attempts (skipped after the last one).
        exceptions: exception type(s) that trigger a retry.
        on_retry(exc, attempt, max_retries, *args, **kwargs): called after
            every failed attempt, including the last one, so each call site
            can log it exactly like it used to.
        on_failure(exc, *args, **kwargs): called once all attempts are
            exhausted. If provided, its return value becomes the decorated
            function's return value instead of re-raising the exception.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if on_retry is not None:
                        on_retry(exc, attempt, max_retries, *args, **kwargs)
                    if attempt < max_retries:
                        time.sleep(delay)
                    elif on_failure is not None:
                        return on_failure(exc, *args, **kwargs)
                    else:
                        raise
        return wrapper
    return decorator


def retry_async(max_retries=3, delay=1, exceptions=(Exception,), on_retry=None, on_failure=None):
    """Async counterpart of `retry`, for coroutine functions."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    if on_retry is not None:
                        on_retry(exc, attempt, max_retries, *args, **kwargs)
                    if attempt < max_retries:
                        await asyncio.sleep(delay)
                    elif on_failure is not None:
                        return on_failure(exc, *args, **kwargs)
                    else:
                        raise
        return wrapper
    return decorator
