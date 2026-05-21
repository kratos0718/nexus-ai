"""
Celery task: index a document in the background.

Flow:
  1. HTTP upload endpoint saves file + creates DB record (status=PENDING)
  2. Endpoint dispatches this task and returns 202 immediately
  3. Celery worker picks up the task
  4. Sets status=PROCESSING
  5. Runs embedding + vector store upsert (slow, CPU/IO heavy)
  6. Sets status=READY (or FAILED on error)
  7. Client polls /documents/{id}/status until READY
"""

from loguru import logger
from app.core.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="app.workers.document_tasks.index_document",
    max_retries=3,
    default_retry_delay=60,   # wait 60s before retry
)
def index_document(self, document_id: str, file_path: str, filename: str):
    """
    `bind=True` gives access to `self` — the task instance.
    Used for self.retry() on failure.
    """
    from app.core.database import get_sync_db
    from app.models.document import Document, DocumentStatus
    from app.services.rag_service import get_pipeline

    db = get_sync_db()
    try:
        # Mark as processing
        doc = db.query(Document).filter(Document.document_id == document_id).first()
        if not doc:
            logger.error(f"Document {document_id} not found in DB")
            return

        doc.status = DocumentStatus.PROCESSING
        db.commit()
        logger.info(f"[Task] Indexing started: {filename} ({document_id})")

        # Run the heavy embedding + vector upsert
        pipeline = get_pipeline()
        result = pipeline.index_file(
            file_path=file_path,
            document_id=document_id,
            display_name=filename,
        )

        # Mark as ready
        doc.status = DocumentStatus.READY
        doc.chunks_count = result.get("chunks_indexed", 0)
        db.commit()
        logger.info(f"[Task] Indexed {doc.chunks_count} chunks for {filename}")

    except Exception as exc:
        logger.error(f"[Task] Indexing failed for {document_id}: {exc}")
        try:
            doc = db.query(Document).filter(Document.document_id == document_id).first()
            if doc:
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(exc)[:500]
                db.commit()
        except Exception:
            pass

        # Retry up to max_retries times
        raise self.retry(exc=exc)
    finally:
        db.close()
