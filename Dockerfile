# Базовий образ Python
FROM python:3.14.4-slim

# Встановлюємо змінні оточення для неблокуючого виводу і часової зони
ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Kiev

# Встановлюємо робочу директорію
WORKDIR /ai-news

# Копіюємо залежності
COPY requirements.txt .

# Встановлюємо залежності
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь код
COPY ./app ./app
COPY ./main.py .
COPY ./prompt.txt .

# Команда запуску
CMD ["python", "main.py"]