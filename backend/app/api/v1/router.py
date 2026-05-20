"""Combines all v1 endpoint routers under /api/v1."""

from fastapi import APIRouter
from app.api.v1.endpoints import documents, chat, auth, conversations, agent

api_router = APIRouter()

api_router.include_router(auth.router,          prefix="/auth",          tags=["auth"])
api_router.include_router(documents.router,     prefix="/documents",     tags=["documents"])
api_router.include_router(chat.router,          prefix="/chat",          tags=["chat"])
api_router.include_router(conversations.router, prefix="/conversations",  tags=["conversations"])
api_router.include_router(agent.router,         prefix="/agent",         tags=["agent"])
