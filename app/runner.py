
from app.scheduler import start_scheduler
from app import loop

def start():
    print("Запуск автоматизатора новин...")
    start_scheduler()
    loop.run_forever()
