import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import asyncio
import schedule
from app.job import job


def get_kyiv_timezone():
    try:
        return ZoneInfo("Europe/Kyiv")
    except Exception:
        print("⚠️ Не вдалося завантажити таймзону Europe/Kyiv. Використовується UTC.")
        return timezone.utc

KYIV_TZ = get_kyiv_timezone()


# ----------------- Планувальник -----------------
_job_running = False


def handle_task_exception(task):
    """Callback for handling exceptions in background tasks"""
    try:
        if task.cancelled():
            return
        task.result()
    except asyncio.CancelledError:
        print("⏹ Задача скасована.")
    except Exception as e:
        print(f"❌ Помилка при виконанні задачі: {type(e).__name__}: {e}")
        if "503" in str(e):
            print("⚠️  Сервіс тимчасово недоступний. Повторна спроба при наступному запуску.")


async def job_with_log(retry_count=0, max_retries=2):
    """Run the news job with retries while preventing overlapping executions."""
    global _job_running

    if _job_running:
        print("⏸ Попередній запуск новин ще виконується. Пропускаємо.")
        return False

    _job_running = True
    try:
        for attempt in range(retry_count, max_retries + 1):
            try:
                await job()
                break
            except Exception as e:
                print(f"❌ Помилка при виконанні новин: {type(e).__name__}: {e}")
                if "503" in str(e) and attempt < max_retries:
                    print(f"🔄 Повторна спроба {attempt + 1}/{max_retries}...")
                    await asyncio.sleep(5)
                    continue
                print(f"⏹ Задача припинена. Спроб: {attempt}")
                return False

        next_time = datetime.now(KYIV_TZ) + timedelta(hours=1)
        print(f"⏰ Наступний запуск о {next_time.strftime('%H:%M')}")
        return True
    finally:
        _job_running = False


async def trigger_job_now():
    """Start the newsletter job immediately, without waiting for the schedule."""
    return await job_with_log()


def job_wrapper():
    """Schedule wrapper that avoids overlapping job runs."""
    global _job_running

    kyiv_now = datetime.now(KYIV_TZ)
    now = kyiv_now.hour
    print(f"Київський час ({KYIV_TZ}): {kyiv_now.strftime('%Y-%m-%d %H:%M')}")
    if 8 <= now < 23:
        print(f"Зараз {now} година. Виконується автоматизатор новин...")
        if _job_running:
            print("⏸ Задача вже виконується, пропускаємо поточний запуск.")
            return False
        task = asyncio.create_task(job_with_log())
        task.add_done_callback(handle_task_exception)
        return True
    else:
        print("⏸ Нічний час, задача не виконується.")
        return False


async def scheduler_loop():
    """Асинхронний цикл, який запускає pending jobs"""
    while True:
        schedule.run_pending()
        await asyncio.sleep(60)  # не блокуємо loop


async def start_scheduler():
    """Асинхронна функція для запуску планувальника"""
    # Запуск при включенні з перевіркою часу
    job_wrapper()

    # Планування задач кожні 5  хвилин
    schedule.every(1).hours.do(job_wrapper)

    # Запуск scheduler_loop у глобальному loop
    await scheduler_loop()