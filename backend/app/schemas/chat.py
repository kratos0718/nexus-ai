"""
Pydantic schemas for chat/query API.
"""

from typing import Optional
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    document_id: Optional[str] = Field(None, description="Limit search to one document")
    conversation_id: Optional[str] = Field(None, description="Continue an existing conversation")
    top_k: int = Field(5, ge=1, le=20)
    use_reranking: bool = True
    use_hybrid: bool = True


class SourceReference(BaseModel):
    chunk_id: str
    source: str
    page: Optional[int] = None
    score: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    model: str
    prompt_tokens: int
    completion_tokens: int
    question: str
