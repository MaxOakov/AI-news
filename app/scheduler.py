import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import asyncio
import schedule
from app.job import job


def get_local_timezone():
    tz_name = os.getenv("TIMEZONE") or os.getenv("TZ") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        print(f"⚠️ Невірна таймзона '{tz_name}'. Використовується UTC.")
        return timezone.utc

LOCAL_TZ = get_local_timezone()


# ----------------- Планувальник -----------------
def handle_task_exception(task):
    """Callback for handling exceptions in background tasks"""
    try:
        task.result()
    except Exception as e:
        print(f"❌ Помилка при виконанні задачі: {type(e).__name__}: {e}")
        if "503" in str(e):
            print("⚠️  Сервіс тимчасово недоступний. Повторна спроба при наступному запуску.")


async def job_with_log(retry_count=0, max_retries=2):
    """Асинхронний запуск job з повідомленням про наступний запуск."""
    try:
        await job()
    except Exception as e:
        print(f"❌ Помилка при виконанні новин: {type(e).__name__}: {e}")
        # Якщо це тимчасова помилка (503) і маємо спроби - повторюємо
        if "503" in str(e) and retry_count < max_retries:
            retry_count += 1
            print(f"🔄 Повторна спроба {retry_count}/{max_retries}...")
            await asyncio.sleep(5)  # Затримка перед повторною спробою
            await job_with_log(retry_count=retry_count, max_retries=max_retries)
            return
        else:
            # Якщо не 503 або вичерпали спроби - логуємо помилку
            print(f"⏹ Задача припинена. Спроб: {retry_count}")
    
    # Обчислюємо час наступного запуску в локальному часі (виводиться завжди)
    next_time = datetime.now(LOCAL_TZ) + timedelta(hours=2)
    print(f"⏰ Наступний запуск о {next_time.strftime('%H:%M')}")


def job_wrapper():
    """Обгортка для schedule: перевіряє час перед запуском job"""
    local_now = datetime.now(LOCAL_TZ)
    now = local_now.hour
    print(f"Локальний час ({LOCAL_TZ}): {local_now.strftime('%Y-%m-%d %H:%M')}")
    if 9 <= now <= 22:
        print(f"Зараз {now} година. Виконується автоматизатор новин...")
        # job асинхронна → створюємо таск у глобальному loop
        task = asyncio.create_task(job_with_log())
        task.add_done_callback(handle_task_exception)
    else:
        print("⏸ Нічний час, задача не виконується.")


async def scheduler_loop():
    """Асинхронний цикл, який запускає pending jobs"""
    while True:
        schedule.run_pending()
        await asyncio.sleep(1)  # не блокуємо loop


async def start_scheduler():
    """Асинхронна функція для запуску планувальника"""
    # Запуск при включенні 
    task = asyncio.create_task(job_with_log())
    task.add_done_callback(handle_task_exception)

    # Планування задач кожні 2 години
    schedule.every(2).hours.do(job_wrapper)

    # Запуск scheduler_loop у глобальному loop
    await scheduler_loop()