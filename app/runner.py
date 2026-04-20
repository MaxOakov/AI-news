
from app.scheduler import start_scheduler
from app import loop

def start():
    """Start the news automation bot"""
    print("Запуск автоматизатора новин...")
    try:
        loop.run_until_complete(start_scheduler())
    except KeyboardInterrupt:
        print("\n⏹ Зупинено користувачем.")
    finally:
        loop.close()


