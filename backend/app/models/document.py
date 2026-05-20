"""
SQLAlchemy ORM model for documents.
Maps the `documents` table — tracks every file uploaded by every user.
"""

from datetime import datetime, UTC
from sqlalchemy import String, Integer, DateTime, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
import enum

from app.core.database import Base


class DocumentStatus(str, enum.Enum):
    PENDING    = "pending"      # just uploaded, not indexed yet
    PROCESSING = "processing"   # background indexing job running
    READY      = "ready"        # indexed, searchable
    FAILED     = "failed"       # indexing failed


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int]                  = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str]         = mapped_column(String(36), unique=True, index=True)   # UUID
    filename: Mapped[str]            = mapped_column(String(255))
    source_type: Mapped[str]         = mapped_column(String(20))     # "pdf" | "txt" | "url" | etc.
    status: Mapped[DocumentStatus]   = mapped_column(SAEnum(DocumentStatus), default=DocumentStatus.PENDING)
    chunks_count: Mapped[int]        = mapped_column(Integer, default=0)
    file_size_bytes: Mapped[int]     = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime]     = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime]     = mapped_column(DateTime, default=lambda: datetime.now(UTC),
                                                     onupdate=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<Document {self.filename} [{self.status}]>"
