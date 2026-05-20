"""
Chat / query endpoints.

POST /chat/query  — ask a question, get an answer with citations
GET  /chat/health — verify LLM is reachable
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.rag_service import rag_service
from app.schemas.chat import QueryRequest, QueryResponse

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Ask a question against the indexed knowledge base.

    If document_id is provided, only searches within that document.
    Otherwise searches the entire knowledge base.
    """
    if request.document_id:
        doc = await rag_service.get_document(db, request.document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        if doc.status != "ready":
            raise HTTPException(
                status_code=409,
                detail=f"Document is not ready yet. Current status: {doc.status}",
            )

    try:
        result = await rag_service.query(
            question=request.question,
            document_id=request.document_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

    return result


@router.get("/health")
async def chat_health():
    """Verify the LLM + pipeline are initialized."""
    from app.services.rag_service import _pipeline
    return {
        "pipeline_initialized": _pipeline is not None,
        "status": "ready" if _pipeline else "not_initialized",
    }
