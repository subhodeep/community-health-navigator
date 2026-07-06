# Build context: repo root (community-health-navigator/)
#   docker build -f services/api/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

COPY services/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared /app/shared
COPY services/api /app
COPY config.yaml /app/config.yaml

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
