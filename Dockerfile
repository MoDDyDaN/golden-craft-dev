# Используем лёгкий образ Python
FROM python:3.11-slim

# Отключаем буферизацию вывода (чтобы логи сразу были в логах Railway)
ENV PYTHONUNBUFFERED=1

# Рабочая директория
WORKDIR /app

# Копируем только requirements.txt и ставим зависимости (кэшируется)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота
COPY bot.py .env ./

# Запуск
CMD ["python", "bot.py"]