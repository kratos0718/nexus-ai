"""
Pydantic schemas for document-related API request/response shapes.
These are NOT database models — they define what the API accepts and returns.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    message: str


class DocumentStatusResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    chunks_count: int
    file_size_bytes: int
    created_at: datetime
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}   # allow building from ORM objects


class DocumentListResponse(BaseModel):
    documents: list[DocumentStatusResponse]
    total: int


class URLIndexRequest(BaseModel):
    url: str = Field(..., description="Web URL to fetch and index")
    document_name: Optional[str] = Field(None, description="Optional display name")
