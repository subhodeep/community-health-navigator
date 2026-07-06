# Workflow Worker — Pub/Sub push consumer.
# Build from the repo root so shared/ and config.yaml are in context:
#   docker build -f services/worker/Dockerfile -t worker .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared /app/shared
COPY services/worker /app
COPY config.yaml /app/config.yaml

ENV PYTHONPATH=/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
