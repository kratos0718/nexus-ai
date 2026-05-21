"""
LLMTrace — records every LLM call made by the application.

Columns capture enough for:
  - Cost analysis (tokens × price)
  - Latency monitoring (duration_ms)
  - Error tracking (error field)
  - Per-user usage (user_id)
  - Per-document queries (document_id)
  - Agent vs direct RAG (trace_type)
"""

from datetime import datetime, UTC
from sqlalchemy import String, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LLMTrace(Base):
    __tablename__ = "llm_traces"

    id: Mapped[int]                   = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str]             = mapped_column(String(36), unique=True, index=True)  # UUID

    # Who made the call
    user_id: Mapped[int | None]       = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    document_id: Mapped[str | None]   = mapped_column(String(36), nullable=True, index=True)

    # What was asked/answered
    trace_type: Mapped[str]           = mapped_column(String(20), default="rag")  # "rag" | "agent" | "router" | "planner"
    question: Mapped[str]             = mapped_column(Text)
    answer: Mapped[str | None]        = mapped_column(Text, nullable=True)

    # LLM details
    model: Mapped[str]                = mapped_column(String(100))
    prompt_tokens: Mapped[int]        = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int]    = mapped_column(Integer, default=0)
    total_tokens: Mapped[int]         = mapped_column(Integer, default=0)

    # Performance
    duration_ms: Mapped[float]        = mapped_column(Float, default=0.0)

    # Error tracking (null = success)
    error: Mapped[str | None]         = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime]      = mapped_column(DateTime, default=lambda: datetime.now(UTC), index=True)

    def __repr__(self) -> str:
        return f"<LLMTrace {self.trace_type} {self.total_tokens}tok {self.duration_ms:.0f}ms>"
