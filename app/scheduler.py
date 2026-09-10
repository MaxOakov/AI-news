from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import asyncio
import schedule

from app.news_pipeline import NewsPipeline


def get_kyiv_timezone():
    try:
        return ZoneInfo("Europe/Kyiv")
    except Exception:
        print("⚠️ Не вдалося завантажити таймзону Europe/Kyiv. Використовується UTC.")
        return timezone.utc


KYIV_TZ = get_kyiv_timezone()


class SchedulerService:
    """Runs the news pipeline once at startup and then on an hourly
    schedule, guarding against overlapping runs and retrying on transient
    (503) failures.

    Replaces the module-level `_job_running` flag that used to live here
    with instance state, so the "is a run in progress" flag can't be
    mutated from anywhere else in the process by accident.
    """

    def __init__(self, pipeline: NewsPipeline, active_hours: range = range(8, 23)):
        self._pipeline = pipeline
        self._active_hours = active_hours
        self._running = False

    def _handle_task_exception(self, task: asyncio.Task):
        """Callback for handling exceptions in background tasks."""
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

    async def _run_with_retry(self, retry_count=0, max_retries=2):
        """Run the news job with retries while preventing overlapping executions."""
        if self._running:
            print("⏸ Попередній запуск новин ще виконується. Пропускаємо.")
            return False

        self._running = True
        try:
            for attempt in range(retry_count, max_retries + 1):
                try:
                    await self._pipeline.run()
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
            self._running = False

    async def trigger_now(self):
        """Start the newsletter job immediately, without waiting for the schedule."""
        return await self._run_with_retry()

    def _scheduled_tick(self):
        """Schedule wrapper that avoids overlapping job runs."""
        kyiv_now = datetime.now(KYIV_TZ)
        now = kyiv_now.hour
        print(f"Київський час ({KYIV_TZ}): {kyiv_now.strftime('%Y-%m-%d %H:%M')}")
        if now in self._active_hours:
            print(f"Зараз {now} година. Виконується автоматизатор новин...")
            if self._running:
                print("⏸ Задача вже виконується, пропускаємо поточний запуск.")
                return False
            task = asyncio.create_task(self._run_with_retry())
            task.add_done_callback(self._handle_task_exception)
            return True
        else:
            print("⏸ Нічний час, задача не виконується.")
            return False

    async def _loop(self):
        """Асинхронний цикл, який запускає pending jobs"""
        while True:
            schedule.run_pending()
            await asyncio.sleep(60)  # не блокуємо loop

    async def start(self):
        """Асинхронна функція для запуску планувальника"""
        # Запуск при включенні з перевіркою часу
        self._scheduled_tick()

        # Планування задач щогодини
        schedule.every(1).hours.do(self._scheduled_tick)

        # Запуск _loop у глобальному loop
        await self._loop()
