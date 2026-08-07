FROM python:3.9-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Создаем файл-флаг, чтобы пространство не засыпало сразу (для CPU spaces)
# Но для Docker space это не критично, главное - процесс работает
ENV HF_HOME=/tmp/huggingface

# Запуск бота
CMD ["python", "main.py"]
