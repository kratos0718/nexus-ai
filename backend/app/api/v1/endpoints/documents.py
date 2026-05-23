"""
Document management endpoints.

POST   /documents/upload       — upload a file, triggers background indexing
POST   /documents/url          — index a web URL
GET    /documents/             — list documents owned by current user
GET    /documents/{id}/status  — get one document's status
DELETE /documents/{id}         — delete document from DB + vector store
"""

import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security_guard import security_guard
from app.models.user import User
from app.schemas.document import (
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
    URLIndexRequest,
)
from app.services.rag_service import rag_service

router = APIRouter()

UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


VALID_CHUNK_STRATEGIES = {"recursive", "semantic", "fixed"}


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    chunking_strategy: str = Form("recursive"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a document and begin background indexing.
    Returns 202 immediately — poll GET /documents/{id}/status for progress.
    """
    if chunking_strategy not in VALID_CHUNK_STRATEGIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid chunking_strategy '{chunking_strategy}'. Choose from: {sorted(VALID_CHUNK_STRATEGIES)}",
        )

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{suffix}' not supported. Allowed: {ALLOWED_EXTENSIONS}",
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Max size: {MAX_FILE_SIZE // 1024 // 1024}MB",
        )
    security_guard.validate_file_bytes(file_bytes, suffix)

    document_id = str(uuid.uuid4())
    temp_path = UPLOAD_DIR / f"{document_id}{suffix}"
    temp_path.write_bytes(file_bytes)

    await rag_service.create_document_record(
        db=db,
        document_id=document_id,
        filename=file.filename,
        source_type=suffix.lstrip("."),
        user_id=current_user.id,
        file_size_bytes=len(file_bytes),
    )

    # Prefer Celery (separate worker process) — fall back to asyncio background task
    # when Celery/Redis is unavailable (local dev without Redis)
    celery_dispatched = False
    try:
        from app.workers.document_tasks import index_document
        index_document.delay(document_id, str(temp_path), file.filename, chunking_strategy)
        celery_dispatched = True
    except Exception:
        pass

    if not celery_dispatched:
        background_tasks.add_task(
            rag_service.index_file_background,
            file_path=str(temp_path),
            document_id=document_id,
            db=db,
            original_filename=file.filename,
            chunk_strategy=chunking_strategy,
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
    current_user: User = Depends(get_current_user),
):
    """Index content from a web URL."""
    security_guard.validate_url(request.url)
    document_id = str(uuid.uuid4())
    display_name = request.document_name or request.url[:80]

    await rag_service.create_document_record(
        db=db,
        document_id=document_id,
        filename=display_name,
        source_type="url",
        user_id=current_user.id,
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
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List documents belonging to the current user."""
    docs = await rag_service.list_documents(db, user_id=current_user.id)
    return DocumentListResponse(
        documents=[DocumentStatusResponse.model_validate(d) for d in docs],
        total=len(docs),
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the indexing status of a document owned by the current user."""
    doc = await rag_service.get_document(db, document_id, user_id=current_user.id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentStatusResponse.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document owned by the current user."""
    deleted = await rag_service.delete_document(db, document_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")


@router.get("/{document_id}/chunks", summary="Browse indexed chunks for a document")
async def get_document_chunks(
    document_id: str,
    offset: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the raw text chunks stored in the vector store for one document.
    Ordered by chunk_index (document reading order).
    Useful for debugging retrieval quality and exploring indexed content.
    """
    doc = await rag_service.get_document(db, document_id, user_id=current_user.id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status != "ready":
        raise HTTPException(status_code=409, detail=f"Document not ready (status: {doc.status})")

    import asyncio

    from app.services.rag_service import get_pipeline

    pipeline = get_pipeline()
    loop = asyncio.get_event_loop()
    all_chunks = await loop.run_in_executor(
        None,
        lambda: pipeline.vector_store.get_document_chunks(document_id),
    )

    page = all_chunks[offset: offset + limit]
    return {
        "document_id": document_id,
        "filename": doc.filename,
        "total_chunks": len(all_chunks),
        "offset": offset,
        "limit": limit,
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "chunk_index": c.metadata.get("chunk_index", 0),
                "text": c.text,
                "source": c.metadata.get("source", ""),
                "page": c.metadata.get("page"),
                "char_count": len(c.text),
            }
            for c in page
        ],
    }
