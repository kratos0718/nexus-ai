"""
RAG service — business logic layer between API endpoints and the RAG pipeline.

Responsibilities:
  - Own the single RAGPipeline instance (singleton)
  - Coordinate between the pipeline and the database
  - Handle errors and translate them to meaningful messages
  - Run CPU-heavy operations in a thread pool (non-blocking for async FastAPI)
"""

import asyncio
import os
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.rag.pipeline import RAGPipeline
from app.schemas.chat import QueryResponse, SourceReference


def _build_pipeline() -> RAGPipeline:
    """Create the pipeline once. Called by get_rag_service()."""
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        logger.warning("GROQ_API_KEY not set — generation will fail on query")

    return RAGPipeline(
        groq_api_key=api_key,
        collection_name="nexus_documents",
        chunk_strategy="recursive",
        chunk_size=800,
        chunk_overlap=150,
        retrieval_top_k=10,
        rerank_top_k=5,
        use_reranker=True,
        use_hybrid_search=True,
    )


# Module-level singleton — created once when the module is first imported
_pipeline: Optional[RAGPipeline] = None


def get_pipeline() -> RAGPipeline:
    global _pipeline
    if _pipeline is None:
        logger.info("Initializing RAG pipeline (first request)...")
        _pipeline = _build_pipeline()
    return _pipeline


class RAGService:
    """Async-friendly wrapper around the synchronous RAGPipeline."""

    # ── File Indexing ──────────────────────────────────────────────────

    async def index_file_background(
        self,
        file_path: str,
        document_id: str,
        db: AsyncSession,
        original_filename: Optional[str] = None,
    ) -> None:
        """
        Indexes a file in a background task.
        Updates the Document DB row with status and chunk count when done.
        """
        pipeline = get_pipeline()

        # Mark as processing
        await self._update_status(db, document_id, DocumentStatus.PROCESSING)

        try:
            # run_in_executor: runs the blocking pipeline call in a thread pool
            # so it doesn't block the FastAPI event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: pipeline.index_file(
                    file_path,
                    document_id=document_id,
                    display_name=original_filename,
                )
            )

            await self._update_status(
                db, document_id, DocumentStatus.READY,
                chunks_count=result["chunks_indexed"]
            )
            logger.info(f"Indexed {result['chunks_indexed']} chunks for {document_id}")

        except Exception as e:
            logger.error(f"Indexing failed for {document_id}: {e}")
            await self._update_status(
                db, document_id, DocumentStatus.FAILED,
                error_message=str(e)
            )
        finally:
            # Clean up the temp file
            try:
                Path(file_path).unlink(missing_ok=True)
            except Exception:
                pass

    async def index_url_background(
        self,
        url: str,
        document_id: str,
        db: AsyncSession,
    ) -> None:
        pipeline = get_pipeline()
        await self._update_status(db, document_id, DocumentStatus.PROCESSING)

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: pipeline.index_url(url, document_id=document_id)
            )
            await self._update_status(
                db, document_id, DocumentStatus.READY,
                chunks_count=result["chunks_indexed"]
            )
        except Exception as e:
            logger.error(f"URL indexing failed for {document_id}: {e}")
            await self._update_status(db, document_id, DocumentStatus.FAILED, error_message=str(e))

    # ── Querying ──────────────────────────────────────────────────────

    async def query(
        self,
        question: str,
        document_id: Optional[str] = None,
    ) -> QueryResponse:
        pipeline = get_pipeline()

        where = {"document_id": document_id} if document_id else None

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: pipeline.query(question, where=where)
        )

        return QueryResponse(
            answer=result.answer,
            sources=[
                SourceReference(
                    chunk_id=s["chunk_id"],
                    source=s["source"],
                    page=s.get("page"),
                    score=s["score"],
                )
                for s in result.sources
            ],
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            question=question,
        )

    # ── Document DB helpers ───────────────────────────────────────────

    async def create_document_record(
        self,
        db: AsyncSession,
        document_id: str,
        filename: str,
        source_type: str,
        file_size_bytes: int = 0,
    ) -> Document:
        doc = Document(
            document_id=document_id,
            filename=filename,
            source_type=source_type,
            status=DocumentStatus.PENDING,
            file_size_bytes=file_size_bytes,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    async def get_document(self, db: AsyncSession, document_id: str) -> Optional[Document]:
        result = await db.execute(
            select(Document).where(Document.document_id == document_id)
        )
        return result.scalar_one_or_none()

    async def list_documents(self, db: AsyncSession) -> list[Document]:
        result = await db.execute(select(Document).order_by(Document.created_at.desc()))
        return list(result.scalars().all())

    async def delete_document(self, db: AsyncSession, document_id: str) -> bool:
        doc = await self.get_document(db, document_id)
        if not doc:
            return False

        # Remove from vector store
        try:
            pipeline = get_pipeline()
            pipeline.vector_store.delete_document(document_id)
            pipeline._rebuild_bm25()
        except Exception as e:
            logger.warning(f"Vector store delete failed: {e}")

        await db.delete(doc)
        await db.commit()
        return True

    async def _update_status(
        self,
        db: AsyncSession,
        document_id: str,
        status: DocumentStatus,
        chunks_count: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        doc = await self.get_document(db, document_id)
        if doc:
            doc.status = status
            if chunks_count:
                doc.chunks_count = chunks_count
            if error_message:
                doc.error_message = error_message
            await db.commit()


# Singleton service instance
rag_service = RAGService()
