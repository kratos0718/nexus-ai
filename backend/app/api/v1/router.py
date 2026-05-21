"""Combines all v1 endpoint routers under /api/v1."""

from fastapi import APIRouter
from app.api.v1.endpoints import documents, chat, auth, conversations, agent, traces, eval, search, feedback, system_prompts, cache_admin

api_router = APIRouter()

api_router.include_router(auth.router,          prefix="/auth",          tags=["auth"])
api_router.include_router(documents.router,     prefix="/documents",     tags=["documents"])
api_router.include_router(chat.router,          prefix="/chat",          tags=["chat"])
api_router.include_router(conversations.router, prefix="/conversations",  tags=["conversations"])
api_router.include_router(agent.router,         prefix="/agent",         tags=["agent"])
api_router.include_router(traces.router,        prefix="/traces",        tags=["observability"])
api_router.include_router(eval.router,          prefix="/eval",          tags=["evaluation"])
api_router.include_router(search.router,        prefix="/search",        tags=["search"])
api_router.include_router(feedback.router,        prefix="/feedback",        tags=["feedback"])
api_router.include_router(system_prompts.router,  prefix="/system-prompts",  tags=["system-prompts"])
api_router.include_router(cache_admin.router,     prefix="/cache",           tags=["cache"])
