# Root Dockerfile for HuggingFace Spaces deployment.
# HF Spaces builds from repo root, so this copies from backend/.
# Local dev and other platforms use backend/Dockerfile directly.

FROM python:3.11-slim AS deps

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime

WORKDIR /app

COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ .

RUN mkdir -p uploads chroma_data

RUN useradd -m -u 1000 nexus && chown -R nexus:nexus /app
USER nexus

# HuggingFace Spaces routes traffic to port 7860
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:7860/ping || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 7860 --workers 1"]
