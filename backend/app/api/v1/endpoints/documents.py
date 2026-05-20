"""
Document management endpoints.

POST   /documents/upload       — upload a file, triggers background indexing
POST   /documents/url          — index a web URL
GET    /documents/             — list all documents with status
GET    /documents/{id}/status  — get one document's status
DELETE /documents/{id}         — delete document from DB + vector store
"""

import os
import uuid
import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.rag_service import rag_service
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentStatusResponse,
    DocumentListResponse,
    URLIndexRequest,
)

router = APIRouter()

UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document and begin background indexing.

    Returns 202 Accepted immediately — indexing runs in background.
    Poll GET /documents/{id}/status to check when status becomes "ready".
    """
    # Validate file extension
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{suffix}' not supported. Allowed: {ALLOWED_EXTENSIONS}",
        )

    # Check file size (read in chunks to avoid loading entire file into memory)
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Max size: {MAX_FILE_SIZE // 1024 // 1024}MB",
        )

    # Save to temp location for background task to process
    document_id = str(uuid.uuid4())
    temp_path = UPLOAD_DIR / f"{document_id}{suffix}"
    temp_path.write_bytes(file_bytes)

    # Create DB record (status=PENDING)
    await rag_service.create_document_record(
        db=db,
        document_id=document_id,
        filename=file.filename,
        source_type=suffix.lstrip("."),
        file_size_bytes=len(file_bytes),
    )

    # Queue background indexing — does NOT block the HTTP response
    background_tasks.add_task(
        rag_service.index_file_background,
        file_path=str(temp_path),
        document_id=document_id,
        db=db,
        original_filename=file.filename,
    )

    return DocumentUploadResponse(
        document_id=document_id,
        filename=file.filename,
        status="pending",
        message="File uploaded. Indexing started in background. Poll /status to check progress.",
    )


@router.post("/url", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def index_url(
    request: URLIndexRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Index content from a web URL."""
    document_id = str(uuid.uuid4())
    display_name = request.document_name or request.url[:80]

    await rag_service.create_document_record(
        db=db,
        document_id=document_id,
        filename=display_name,
        source_type="url",
    )

    background_tasks.add_task(
        rag_service.index_url_background,
        url=request.url,
        document_id=document_id,
        db=db,
    )

    return DocumentUploadResponse(
        document_id=document_id,
        filename=display_name,
        status="pending",
        message="URL queued for indexing.",
    )


@router.get("/", response_model=DocumentListResponse)
async def list_documents(db: AsyncSession = Depends(get_db)):
    """List all documents with their indexing status."""
    docs = await rag_service.list_documents(db)
    return DocumentListResponse(
        documents=[DocumentStatusResponse.model_validate(d) for d in docs],
        total=len(docs),
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(document_id: str, db: AsyncSession = Depends(get_db)):
    """Get the indexing status of a specific document."""
    doc = await rag_service.get_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentStatusResponse.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a document from both the database and vector store."""
    deleted = await rag_service.delete_document(db, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
