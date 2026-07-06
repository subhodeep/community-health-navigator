# Build context: repo root (community-health-navigator/)
#   docker build -f services/agent/Dockerfile .
FROM python:3.12-slim

WORKDIR /app
COPY services/agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared /app/shared
COPY services/agent /app
COPY config.yaml /app/config.yaml

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
