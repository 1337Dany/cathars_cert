FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/certs.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# БД лежит в томе, чтобы не терять сертификаты при пересоздании контейнера
RUN useradd -m appuser && mkdir /data && chown appuser /data
USER appuser
VOLUME /data

EXPOSE 5000

# 1 worker: сессии и SQLite без сюрпризов; потоки дают параллельность
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "1", "--threads", "4", "app:app"]
