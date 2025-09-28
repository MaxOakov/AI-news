from datetime import datetime
import asyncio
import schedule
from app.job import job
from app import loop

# ----------------- Планувальник -----------------
def job_wrapper():
    """Обгортка для schedule: перевіряє час перед запуском job"""
    now = datetime.now().hour
    if 9 <= now < 24:
        print(f"Зараз {now} година. Виконується автоматизатор новин...")
        # job асинхронна → створюємо таск у глобальному loop
        loop.create_task(job())
    else:
        print("⏸ Нічний час, задача не виконується.")


async def scheduler_loop():
    """Асинхронний цикл, який запускає pending jobs"""
    while True:
        schedule.run_pending()
        await asyncio.sleep(1)  # не блокуємо loop


def start_scheduler():
    # Планування задач кожні 2 години
    schedule.every(30).seconds.do(job_wrapper)

    # Запуск scheduler_loop у глобальному loop
    loop.create_task(scheduler_loop())
    print("✅ Скедулер запущено")
    loop.run_forever()
