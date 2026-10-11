FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# ./data в корне проекта (/app/data) - папка для базы.
# VOLUME тут не пишем: Railway его не принимает, том подключается в настройках сервиса.
RUN mkdir -p /app/data

EXPOSE 5000

# База: в томе Railway (если он подключён, путь в RAILWAY_VOLUME_MOUNT_PATH),
# иначе в ./data (/app/data). Порт берём из $PORT (Railway), локально 5000.
# 1 worker: сессии и SQLite без сюрпризов; потоки дают параллельность.
CMD ["sh", "-c", "export DB_PATH=\"${RAILWAY_VOLUME_MOUNT_PATH:-/app/data}/certs.db\"; mkdir -p \"$(dirname \"$DB_PATH\")\"; exec gunicorn -b 0.0.0.0:${PORT:-5000} -w 1 --threads 4 app:app"]