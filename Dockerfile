# Берем легкую и быструю версию Python
FROM python:3.10-slim

# Создаем рабочую папку на сервере
WORKDIR /app

# Копируем список библиотек и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь наш код (включая hlam.py)
COPY . .

# Команда для запуска нашего гибридного сервера
CMD ["python", "hlam.py"]
