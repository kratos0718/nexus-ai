"""
Semantic search endpoint — pure retrieval, no LLM generation.

POST /search   query the vector store and return ranked chunks
               useful for debugging retrieval quality and building
               knowledge base exploration UIs

This calls pipeline._retrieve() directly, bypassing the generator.
All retrieval modes (standard / hyde / multiquery) are supported.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security_guard import security_guard
from app.models.user import User
from app.schemas.chat import QueryRequest
from pydantic import BaseModel, Field

router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000)
    document_id: Optional[str] = Field(None, description="Filter to one document")
    top_k: int = Field(5, ge=1, le=20)
    retrieval_mode: str = Field("standard", description="standard | hyde | multiquery")


class ChunkResult(BaseModel):
    chunk_id: str
    text: str
    score: float
    source: str
    page: Optional[int]
    chunk_index: int


class SearchResponse(BaseModel):
    query: str
    retrieval_mode: str
    chunks: list[ChunkResult]
    total: int


@router.post("/", response_model=SearchResponse, summary="Semantic search — retrieve chunks without generating an answer")
async def semantic_search(
    request: SearchRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Run semantic search directly against the vector store.
    Returns ranked chunks — no LLM call, no answer generation.

    Useful for:
    - Debugging why a query returns wrong chunks
    - Exploring what information is indexed
    - Building knowledge base UIs
    """
    query = security_guard.validate_question(request.query)

    from app.services.rag_service import get_pipeline
    from app.services.query_processor import QueryProcessor
    import asyncio

    pipeline = get_pipeline()
    where = {"document_id": request.document_id} if request.document_id else None
    loop = asyncio.get_event_loop()

    mode = request.retrieval_mode
    processor = QueryProcessor(pipeline.generator.llm)

    if mode == "hyde":
        retrieval_query = await loop.run_in_executor(None, lambda: processor.hyde(query))
    elif mode == "multiquery":
        variants = await loop.run_in_executor(None, lambda: processor.expand_queries(query))
        # For multiquery: retrieve and deduplicate, return merged set
        from app.services.rag_service import rag_service
        raw_chunks = await loop.run_in_executor(
            None,
            lambda: rag_service._retrieve_multiquery(pipeline, variants, where),
        )
        return SearchResponse(
            query=query,
            retrieval_mode=mode,
            chunks=[
                ChunkResult(
                    chunk_id=c.chunk_id,
                    text=c.text,
                    score=round(c.score, 4),
                    source=c.metadata.get("source", ""),
                    page=c.metadata.get("page"),
                    chunk_index=c.metadata.get("chunk_index", 0),
                )
                for c in raw_chunks[: request.top_k]
            ],
            total=len(raw_chunks[: request.top_k]),
        )
    else:
        retrieval_query = query

    raw_chunks = await loop.run_in_executor(
        None,
        lambda: pipeline._retrieve(retrieval_query, where=where),
    )

    chunks = [
        ChunkResult(
            chunk_id=c.chunk_id,
            text=c.text,
            score=round(c.score, 4),
            source=c.metadata.get("source", ""),
            page=c.metadata.get("page"),
            chunk_index=c.metadata.get("chunk_index", 0),
        )
        for c in raw_chunks[: request.top_k]
    ]

    return SearchResponse(query=query, retrieval_mode=mode, chunks=chunks, total=len(chunks))
