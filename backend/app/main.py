"""
FastAPI application entry point.
Creates app, registers routers, configures middleware and lifespan events.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger

from app.core.config import settings


# ── Lifespan: runs on startup and shutdown ─────────────────────────────
# Modern FastAPI pattern (replaces @app.on_event decorators)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP: runs before first request
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.app_env}")
    logger.info(f"LLM Model: {settings.llm_model}")

    # TODO Week 1: Initialize database connection pool
    # TODO Week 1: Initialize vector database client
    # TODO Week 1: Warm up embedding model

    yield  # Application runs here

    # SHUTDOWN: runs after last request
    logger.info("Shutting down Nexus AI...")
    # TODO: Close database connections, cleanup resources


# ── Application Instance ───────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    description="Enterprise Multi-Agent RAG Intelligence Platform",
    version=settings.app_version,
    docs_url="/docs" if settings.debug else None,      # Hide docs in prod
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)


# ── Middleware ─────────────────────────────────────────────────────────
# CORS: allows frontend (localhost:3000) to call our backend (localhost:8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ─────────────────────────────────────────────────────────────
# We'll add these routers as we build each feature:
# from app.api.v1.endpoints import auth, documents, chat, agents
# app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
# app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
# app.include_router(chat.router, prefix="/api/v1/chat", tags=["chat"])


# ── Health Check ───────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health_check():
    """
    Health check endpoint.
    Used by: load balancers, Docker, Kubernetes, monitoring systems.
    Should return 200 when the app is ready to serve requests.
    """
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.app_env,
    }


@app.get("/", tags=["system"])
async def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "docs": "/docs",
        "health": "/health",
    }
