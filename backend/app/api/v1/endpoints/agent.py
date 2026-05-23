"""
Multi-agent RAG endpoints.

POST /agent/query   — single response with routing metadata
POST /agent/stream  — SSE stream with step-by-step progress events
GET  /agent/health  — verify graph is compiled
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import rate_limit_user
from app.core.security_guard import security_guard
from app.models.user import User
from app.schemas.agent import AgentQueryRequest, AgentQueryResponse
from app.schemas.chat import SourceReference
from app.services.agent_service import agent_service
from app.services.rag_service import rag_service

router = APIRouter()


@router.post("/query", response_model=AgentQueryResponse)
async def agent_query(
    request: AgentQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(rate_limit_user),
):
    """
    Multi-agent RAG query.

    The router node decides:
    - simple → direct RAG retrieval → answer
    - complex → plan sub-questions → retrieve for each → synthesize

    Returns routing metadata so the UI can show how the query was handled.
    """
    question = security_guard.validate_question(request.question)

    if request.document_id:
        doc = await rag_service.get_document(db, request.document_id, user_id=current_user.id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

    history = None
    if request.conversation_id:
        conv = await rag_service.get_conversation(db, request.conversation_id, current_user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        history = rag_service._build_history(conv.messages)

    try:
        result = await agent_service.run(
            question=question,
            document_id=request.document_id,
            history=history,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent failed: {str(e)}")

    return AgentQueryResponse(
        answer=result["answer"],
        sources=[SourceReference(**s) for s in result["sources"]],
        route=result["route"],
        sub_questions=result["sub_questions"],
        prompt_tokens=result["prompt_tokens"],
        completion_tokens=result["completion_tokens"],
        question=request.question,
    )


@router.post("/stream")
async def agent_stream(
    request: AgentQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(rate_limit_user),
):
    """
    Streaming multi-agent query. SSE events show each agent step:

      data: [STEP]router       ← node started
      data: [ROUTE]complex     ← routing decision
      data: [PLAN]["q1","q2"]  ← sub-questions from planner
      data: [CONTEXT]8         ← chunks retrieved
      data: <token>            ← answer tokens
      data: [SOURCES]{...}     ← source citations
      data: [DONE]             ← stream complete
    """
    question = security_guard.validate_question(request.question)

    if request.document_id:
        doc = await rag_service.get_document(db, request.document_id, user_id=current_user.id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

    history = None
    if request.conversation_id:
        conv = await rag_service.get_conversation(db, request.conversation_id, current_user.id)
        if conv:
            history = rag_service._build_history(conv.messages)

    return StreamingResponse(
        agent_service.stream(
            question=question,
            document_id=request.document_id,
            history=history,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/health")
async def agent_health():
    from app.services.agent_service import _graph
    return {
        "graph_compiled": _graph is not None,
        "status": "ready" if _graph else "not_initialized",
    }
