# Используем легкий образ Python
FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота
COPY . .

# Создаем директории для данных и логов
RUN mkdir -p /app/data /app/logs

# Устанавливаем права
RUN chmod +x /app/main.py

# Команда запуска
CMD ["python", "main.py"]