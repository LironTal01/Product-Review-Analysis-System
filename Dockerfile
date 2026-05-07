# PRAS — Product Review Analysis System
# Single-stage image used both for local docker-compose and for Azure
# Container Apps deployment (Step 16 of NEXT_STEPS.md).

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first to maximize Docker layer cache reuse.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Run as a non-root user (better default for Container Apps and security).
RUN useradd --create-home --shell /usr/sbin/nologin pras \
    && chown -R pras:pras /app
USER pras

EXPOSE 8000

# Lightweight liveness probe — matches the FastAPI /health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)" \
    || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
