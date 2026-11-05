FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY run.py .

RUN chown -R appuser:appuser /app
USER appuser

# Cloud Run injeta PORT (default 8080)
ENV HOST=0.0.0.0 \
    PORT=8080 \
    APP_ENV=production \
    DEBUG=false

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')" || exit 1

# 1 worker: o polling de status roda dentro do processo e o estado fica no MongoDB.
CMD ["sh", "-c", "uvicorn app.main:app --host $HOST --port ${PORT:-8080} --workers 1 --log-level info --proxy-headers --forwarded-allow-ips='*'"]
