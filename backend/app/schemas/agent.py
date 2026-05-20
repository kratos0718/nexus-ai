"""Pydantic schemas for the multi-agent API."""

from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.chat import SourceReference


class AgentQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=4000)
    document_id: Optional[str] = Field(None, description="Scope search to one document")
    conversation_id: Optional[str] = None


class AgentQueryResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    route: str                        # "simple" | "complex"
    sub_questions: list[str]          # empty for simple route
    model: str = "llama-3.3-70b-versatile"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    question: str
