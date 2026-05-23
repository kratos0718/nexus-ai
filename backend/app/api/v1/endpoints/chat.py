"""
Chat / query endpoints.

POST /chat/query   — ask a question, get an answer with citations (auth required)
POST /chat/stream  — streaming version via Server-Sent Events (auth required)
GET  /chat/health  — verify LLM is reachable (public)
"""

import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import rate_limit_user
from app.core.security_guard import security_guard
from app.models.system_prompt import SystemPrompt
from app.models.user import User
from app.schemas.chat import QueryRequest, QueryResponse
from app.services.rag_service import rag_service
from app.services.trace_service import trace_service

router = APIRouter()


async def _resolve_system_prompt(db: AsyncSession, prompt_id: int | None, user_id: int) -> str | None:
    """Look up a saved system prompt by ID, verifying ownership. Returns content or None."""
    if not prompt_id:
        return None
    result = await db.execute(
        select(SystemPrompt).where(SystemPrompt.id == prompt_id, SystemPrompt.user_id == user_id)
    )
    sp = result.scalar_one_or_none()
    return sp.content if sp else None


@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(rate_limit_user),
):
    """
    Ask a question against the indexed knowledge base.

    Optionally pass conversation_id to get multi-turn context injected.
    If document_id is provided, only searches within that document.
    """
    question = security_guard.validate_question(request.question)

    if request.document_id:
        doc = await rag_service.get_document(db, request.document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        if doc.status != "ready":
            raise HTTPException(
                status_code=409,
                detail=f"Document not ready. Status: {doc.status}",
            )

    history = None
    conversation = None
    system_prompt_content = await _resolve_system_prompt(db, request.system_prompt_id, current_user.id)

    if request.conversation_id:
        conversation = await rag_service.get_conversation(db, request.conversation_id, current_user.id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        history = rag_service._build_history(conversation.messages)

    t0 = time.monotonic()
    try:
        result = await rag_service.query(
            question=question,
            document_id=request.document_id,
            history=history,
            retrieval_mode=request.retrieval_mode,
            system_prompt=system_prompt_content,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

    duration_ms = (time.monotonic() - t0) * 1000
    background_tasks.add_task(
        trace_service.record,
        db=db,
        question=question,
        answer=result.answer,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        duration_ms=duration_ms,
        trace_type=f"rag_{request.retrieval_mode}",
        user_id=current_user.id,
        document_id=request.document_id,
    )

    # Persist messages to conversation if one was provided
    if conversation:
        is_first_message = len(conversation.messages) == 0
        await rag_service.add_message(
            db, conversation.conversation_id,
            role="user", content=question,
        )
        await rag_service.add_message(
            db, conversation.conversation_id,
            role="assistant", content=result.answer,
            sources=[s.model_dump() for s in result.sources],
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        # Auto-generate title from first question (runs after response is sent)
        if is_first_message and conversation.title == "New Conversation":
            background_tasks.add_task(
                rag_service._auto_title_conversation,
                db, conversation.conversation_id, question,
            )

    return result


@router.post("/stream")
async def query_stream(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(rate_limit_user),
):
    """
    Streaming version of /query. Returns Server-Sent Events.

    Client reads the response as a stream:
      data: <token>\\n\\n  (repeated for each token)
      data: [SOURCES]{...}\\n\\n
      data: [DONE]\\n\\n
    """
    question = security_guard.validate_question(request.question)

    if request.document_id:
        doc = await rag_service.get_document(db, request.document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

    history = None
    system_prompt_content = await _resolve_system_prompt(db, request.system_prompt_id, current_user.id)

    if request.conversation_id:
        conversation = await rag_service.get_conversation(db, request.conversation_id, current_user.id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        history = rag_service._build_history(conversation.messages)

    return StreamingResponse(
        rag_service.query_stream(
            question=question,
            document_id=request.document_id,
            history=history,
            system_prompt=system_prompt_content,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disables nginx buffering for true streaming
        },
    )


@router.get("/health")
async def chat_health():
    """Verify the LLM + pipeline are initialized. Public endpoint."""
    from app.services.rag_service import _pipeline
    return {
        "pipeline_initialized": _pipeline is not None,
        "status": "ready" if _pipeline else "not_initialized",
    }
