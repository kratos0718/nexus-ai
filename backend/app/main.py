"""
FastAPI application entry point.
Creates app, registers routers, configures middleware and lifespan events.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.database import create_tables
from app.api.v1.router import api_router

# Global rate limiter — keyed by client IP
# Limits are applied per-route with @limiter.limit("N/period")
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("Starting Nexus AI...")

    await create_tables()
    logger.info("Database tables ready")

    os.makedirs("./uploads", exist_ok=True)

    logger.info("Nexus AI ready. Visit http://localhost:8000/docs")
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("Shutting down Nexus AI")


app = FastAPI(
    title="Nexus AI",
    description="Enterprise Multi-Agent RAG Intelligence Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# Attach limiter to app state so slowapi can find it
app.state.limiter = limiter

# ── Middleware ────────────────────────────────────────────────────────────
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Return 429 with a clear message when rate limit is exceeded
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Global exception handler ──────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# ── Routes ────────────────────────────────────────────────────────────────
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
async def health():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/", tags=["system"])
async def root():
    return {"message": "Nexus AI", "docs": "/docs", "health": "/health"}
