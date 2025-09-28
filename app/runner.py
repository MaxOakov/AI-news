
from app.scheduler import start_scheduler
from app import loop

def start():
    print("Запуск автоматизатора новин...")
    start_scheduler()
    loop.run_forever()


# def start():
#     print("Запуск автоматизатора новин...")
#     articles = start_scheduler()
#     news_text = generate_news(articles)
#     send_all(news_text)

    


    