FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8001 \
    HOST=0.0.0.0

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY source_management/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY license_fastapi_system /app/license_fastapi_system
COPY service_management /app/service_management
COPY source_management /app/source_management

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "source_management.main:app", "--host", "0.0.0.0", "--port", "8001"]
