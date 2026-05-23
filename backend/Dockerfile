# ── Stage 1: dependency installation ─────────────────────────────────────────
# Use a slim base to keep the image small
FROM python:3.11-slim AS deps

WORKDIR /app

# System libs needed by some ML packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy only the installed packages from deps stage (not build tools)
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Runtime system libs only (no build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY . .

# Create directories the app needs
RUN mkdir -p uploads chroma_data

# Non-root user for security
RUN useradd -m -u 1000 nexus && chown -R nexus:nexus /app
USER nexus

# Expose FastAPI port ($PORT is set by the hosting platform; falls back to 8000 locally)
EXPOSE 8000

# Health check — /ping has no DB dependency so it works during cold start
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/ping || exit 1

# Run migrations then start the server
# 1 worker: keeps memory under 512MB on free-tier hosts (sentence-transformers ~300MB)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
