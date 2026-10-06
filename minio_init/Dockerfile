FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir minio

COPY init.py /app/init.py

CMD ["python", "-u", "init.py"]
