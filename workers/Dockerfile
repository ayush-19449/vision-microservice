FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KAFKA_BOOTSTRAP_SERVERS=kafka:9092 \
    MINIO_ENDPOINT=minio:9000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY media_server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY storage /app/storage
COPY kafka /app/kafka
COPY workers /app/workers

CMD ["python", "-m", "workers.base_worker"]
