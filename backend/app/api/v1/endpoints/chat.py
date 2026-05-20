"""
Chat / query endpoints.

POST /chat/query   — ask a question, get an answer with citations (auth required)
POST /chat/stream  — streaming version via Server-Sent Events (auth required)
GET  /chat/health  — verify LLM is reachable (public)
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.rag_service import rag_service
from app.schemas.chat import QueryRequest, QueryResponse

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Ask a question against the indexed knowledge base.

    Optionally pass conversation_id to get multi-turn context injected.
    If document_id is provided, only searches within that document.
    """
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

    if request.conversation_id:
        conversation = await rag_service.get_conversation(db, request.conversation_id, current_user.id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        history = rag_service._build_history(conversation.messages)

    try:
        result = await rag_service.query(
            question=request.question,
            document_id=request.document_id,
            history=history,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

    # Persist messages to conversation if one was provided
    if conversation:
        await rag_service.add_message(
            db, conversation.conversation_id,
            role="user", content=request.question,
        )
        await rag_service.add_message(
            db, conversation.conversation_id,
            role="assistant", content=result.answer,
            sources=[s.model_dump() for s in result.sources],
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )

    return result


@router.post("/stream")
async def query_stream(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Streaming version of /query. Returns Server-Sent Events.

    Client reads the response as a stream:
      data: <token>\\n\\n  (repeated for each token)
      data: [SOURCES]{...}\\n\\n
      data: [DONE]\\n\\n
    """
    if request.document_id:
        doc = await rag_service.get_document(db, request.document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

    history = None
    if request.conversation_id:
        conversation = await rag_service.get_conversation(db, request.conversation_id, current_user.id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        history = rag_service._build_history(conversation.messages)

    return StreamingResponse(
        rag_service.query_stream(
            question=request.question,
            document_id=request.document_id,
            history=history,
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
