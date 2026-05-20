"""
RAG service — business logic layer between API endpoints and the RAG pipeline.

Responsibilities:
  - Own the single RAGPipeline instance (singleton)
  - Coordinate between the pipeline and the database
  - Handle errors and translate them to meaningful messages
  - Run CPU-heavy operations in a thread pool (non-blocking for async FastAPI)
"""

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import Document, DocumentStatus
from app.models.conversation import Conversation, Message
from app.rag.pipeline import RAGPipeline
from app.schemas.chat import QueryResponse, SourceReference


def _build_pipeline() -> RAGPipeline:
    """Create the pipeline once. Reads provider config from environment."""
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "huggingface")
    vector_store_provider = os.getenv("VECTOR_STORE_PROVIDER", "chroma")

    # For cloud/Vercel: set EMBEDDING_PROVIDER=openai and VECTOR_STORE_PROVIDER=pinecone
    embedding_dimension = 1536 if embedding_provider == "openai" else 384

    return RAGPipeline(
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        embedding_provider=embedding_provider,
        embedding_model=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2" if embedding_provider == "huggingface" else "text-embedding-3-small"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        vector_store_provider=vector_store_provider,
        collection_name="nexus_documents",
        pinecone_api_key=os.getenv("PINECONE_API_KEY", ""),
        pinecone_index_name=os.getenv("PINECONE_INDEX_NAME", "nexus-ai"),
        embedding_dimension=embedding_dimension,
        chunk_strategy="recursive",
        chunk_size=800,
        chunk_overlap=150,
        retrieval_top_k=10,
        rerank_top_k=5,
        use_reranker=(embedding_provider == "huggingface"),  # reranker needs sentence-transformers
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
        history: Optional[list[dict]] = None,
    ) -> QueryResponse:
        pipeline = get_pipeline()
        where = {"document_id": document_id} if document_id else None

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: pipeline.query(question, where=where, history=history)
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

    async def query_stream(
        self,
        question: str,
        document_id: Optional[str] = None,
        history: Optional[list[dict]] = None,
    ):
        """
        Async generator that yields SSE-formatted strings.
        Runs retrieval in thread pool, then streams generation token-by-token.

        SSE format:
            data: <token>\n\n         ← each token chunk
            data: [SOURCES]<json>\n\n ← final event with citations
            data: [DONE]\n\n          ← end marker
        """
        pipeline = get_pipeline()
        where = {"document_id": document_id} if document_id else None

        # Retrieval + reranking (CPU-bound → thread pool)
        loop = asyncio.get_event_loop()
        context_results = await loop.run_in_executor(
            None,
            lambda: pipeline._retrieve(question, where=where),
        )

        sources = [
            {
                "chunk_id": r.chunk_id,
                "source": r.metadata.get("source", ""),
                "page": r.metadata.get("page"),
                "score": round(r.score, 4),
            }
            for r in context_results
        ]

        # Stream generation — runs in thread pool to avoid blocking event loop
        def _stream_tokens():
            return list(pipeline.generator.generate_stream(
                query=question,
                context_results=context_results,
                history=history or [],
            ))

        # Collect tokens from thread pool, yield to client
        # For true token-by-token streaming we use run_in_executor with a queue
        import queue
        import threading

        token_queue: queue.Queue = queue.Queue()

        def producer():
            try:
                for token in pipeline.generator.generate_stream(
                    query=question,
                    context_results=context_results,
                    history=history or [],
                ):
                    token_queue.put(token)
            finally:
                token_queue.put(None)   # sentinel = done

        thread = threading.Thread(target=producer, daemon=True)
        thread.start()

        while True:
            # Poll queue without blocking event loop
            try:
                token = token_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue

            if token is None:
                break
            yield f"data: {token}\n\n"

        yield f"data: [SOURCES]{json.dumps(sources)}\n\n"
        yield "data: [DONE]\n\n"

    # ── Conversation helpers ──────────────────────────────────────────

    async def create_conversation(
        self,
        db: AsyncSession,
        user_id: int,
        title: str = "New Conversation",
        document_id: Optional[str] = None,
    ) -> Conversation:
        conv = Conversation(
            conversation_id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            document_id=document_id,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        return conv

    async def get_conversation(
        self, db: AsyncSession, conversation_id: str, user_id: int
    ) -> Optional[Conversation]:
        result = await db.execute(
            select(Conversation)
            .where(
                Conversation.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .options(selectinload(Conversation.messages))
        )
        return result.scalar_one_or_none()

    async def list_conversations(self, db: AsyncSession, user_id: int) -> list[Conversation]:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .options(selectinload(Conversation.messages))
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    async def delete_conversation(self, db: AsyncSession, conversation_id: str, user_id: int) -> bool:
        conv = await self.get_conversation(db, conversation_id, user_id)
        if not conv:
            return False
        await db.delete(conv)
        await db.commit()
        return True

    async def add_message(
        self,
        db: AsyncSession,
        conversation_id: str,
        role: str,
        content: str,
        sources: Optional[list] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> Message:
        msg = Message(
            message_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources=json.dumps(sources) if sources else None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        db.add(msg)
        # bump conversation updated_at
        await db.execute(
            select(Conversation).where(Conversation.conversation_id == conversation_id)
        )
        await db.commit()
        await db.refresh(msg)
        return msg

    def _build_history(self, messages: list[Message]) -> list[dict]:
        """Convert ORM Message rows into the list[dict] format Groq expects."""
        return [{"role": m.role, "content": m.content} for m in messages]

    # ── Document DB helpers ───────────────────────────────────────────

    async def create_document_record(
        self,
        db: AsyncSession,
        document_id: str,
        filename: str,
        source_type: str,
        user_id: Optional[int] = None,
        file_size_bytes: int = 0,
    ) -> Document:
        doc = Document(
            document_id=document_id,
            user_id=user_id,
            filename=filename,
            source_type=source_type,
            status=DocumentStatus.PENDING,
            file_size_bytes=file_size_bytes,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    async def get_document(
        self, db: AsyncSession, document_id: str, user_id: Optional[int] = None
    ) -> Optional[Document]:
        q = select(Document).where(Document.document_id == document_id)
        if user_id is not None:
            q = q.where(Document.user_id == user_id)
        result = await db.execute(q)
        return result.scalar_one_or_none()

    async def list_documents(
        self, db: AsyncSession, user_id: Optional[int] = None
    ) -> list[Document]:
        q = select(Document).order_by(Document.created_at.desc())
        if user_id is not None:
            q = q.where(Document.user_id == user_id)
        result = await db.execute(q)
        return list(result.scalars().all())

    async def delete_document(
        self, db: AsyncSession, document_id: str, user_id: Optional[int] = None
    ) -> bool:
        doc = await self.get_document(db, document_id, user_id=user_id)
        if not doc:
            return False

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
