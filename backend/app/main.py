"""
FastAPI application entry point.
Creates app, registers routers, configures middleware and lifespan events.
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import create_tables, get_db
from app.api.v1.router import api_router
from app.middleware.request_id import RequestIDMiddleware

# Global rate limiter — keyed by client IP
limiter = Limiter(key_func=get_remote_address)


# ── Logging ───────────────────────────────────────────────────────────────────

def _configure_logging() -> None:
    """
    LOG_FORMAT=json  → newline-delimited JSON (production / log aggregators)
    LOG_FORMAT=text  → coloured human-readable (default, local dev)
    LOG_LEVEL        → DEBUG | INFO | WARNING | ERROR  (default: INFO)
    """
    logger.remove()
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    if os.getenv("LOG_FORMAT", "text").lower() == "json":
        logger.add(sys.stdout, level=level, serialize=True, enqueue=True)
    else:
        logger.add(
            sys.stdout,
            level=level,
            colorize=True,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
                "{message}"
            ),
            enqueue=True,
        )


_configure_logging()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Nexus AI...")
    await create_tables()
    logger.info("Database tables ready")
    os.makedirs("./uploads", exist_ok=True)
    logger.info("Nexus AI ready. Visit http://localhost:8000/docs")
    yield
    logger.info("Shutting down Nexus AI")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Nexus AI",
    description="Enterprise Multi-Agent RAG Intelligence Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter

# ── Middleware ────────────────────────────────────────────────────────────────

_allowed_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every request gets a unique ID — echoed in X-Request-ID response header
app.add_middleware(RequestIDMiddleware)

app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        f"Unhandled exception | request_id={request_id} | "
        f"path={request.url.path} | {type(exc).__name__}: {exc}"
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "type": type(exc).__name__,
            "request_id": request_id,
        },
    )


# ── Routes ────────────────────────────────────────────────────────────────────

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
async def health(db: AsyncSession = Depends(get_db)):
    """
    Detailed health check for load balancers and Docker HEALTHCHECK.

    Probes each subsystem independently so partial outages are visible.
    Redis failure → "degraded" (system still works, caching disabled).
    Database failure → "degraded" overall (auth and queries will fail).
    """
    checks: dict[str, str] = {}

    # Database (critical)
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.error(f"Health — DB error: {e}")
        checks["database"] = "error"

    # Redis (graceful degradation)
    try:
        from app.core.cache import _get_redis
        _get_redis().ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "degraded"

    # RAG pipeline (lazy — initialised on first query)
    from app.services.rag_service import _pipeline
    if _pipeline is not None:
        try:
            info = _pipeline.vector_store.collection_info()
            checks["pipeline"] = "ready"
            checks["vector_store"] = f"ok ({info.get('count', 0)} chunks)"
        except Exception as e:
            checks["pipeline"] = "ready"
            checks["vector_store"] = f"error: {e}"
    else:
        checks["pipeline"] = "not_initialized"
        checks["vector_store"] = "not_initialized"

    overall = "healthy" if checks["database"] == "ok" else "degraded"

    return {"status": overall, "version": "1.0.0", "checks": checks}


@app.get("/", tags=["system"])
async def root():
    return {"message": "Nexus AI", "docs": "/docs", "health": "/health"}
