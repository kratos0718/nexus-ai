"""
RAG pipeline orchestrator.

Single entry point that coordinates:
  indexing  → load → chunk → embed → store
  retrieval → embed query → search → rerank → generate
"""

import uuid
from typing import List, Optional
from loguru import logger

from app.rag.ingestion.loader import RawDocument, load_file, load_url
from app.rag.ingestion.chunker import chunk_documents, ChunkStrategy
from app.rag.embeddings.embedder import BaseEmbedder, get_embedder
from app.rag.retrieval.vector_store import VectorStore
from app.rag.retrieval.hybrid_search import BM25Index, reciprocal_rank_fusion
from app.rag.retrieval.reranker import CrossEncoderReranker
from app.rag.generation.generator import GroqGenerator, GenerationResult


class RAGPipeline:
    """
    Full RAG pipeline: ingest documents, answer questions.

    Usage:
        pipeline = RAGPipeline(groq_api_key="gsk_...")
        pipeline.index_file("company_policy.pdf")
        result = pipeline.query("What is the vacation policy?")
        print(result.answer)
    """

    def __init__(
        self,
        groq_api_key: str,
        collection_name: str = "nexus_documents",
        chroma_host: str = "localhost",
        chroma_port: int = 8001,
        embedding_model: str = "all-MiniLM-L6-v2",
        llm_model: str = "llama-3.3-70b-versatile",
        chunk_strategy: ChunkStrategy = "recursive",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        retrieval_top_k: int = 10,
        rerank_top_k: int = 5,
        use_reranker: bool = True,
        use_hybrid_search: bool = True,
    ):
        self.chunk_strategy = chunk_strategy
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.retrieval_top_k = retrieval_top_k
        self.rerank_top_k = rerank_top_k
        self.use_reranker = use_reranker
        self.use_hybrid_search = use_hybrid_search

        logger.info("Initializing RAG pipeline components...")

        self.embedder: BaseEmbedder = get_embedder(
            provider="huggingface",
            model_name=embedding_model,
        )
        self.vector_store = VectorStore(
            collection_name=collection_name,
            host=chroma_host,
            port=chroma_port,
            persist_path="./chroma_data",
            use_embedded=True,
        )
        self.bm25_index = BM25Index()
        self.generator = GroqGenerator(
            api_key=groq_api_key,
            model=llm_model,
        )
        self.reranker: Optional[CrossEncoderReranker] = (
            CrossEncoderReranker() if use_reranker else None
        )

        logger.info("RAG pipeline ready")

    # ── Indexing ──────────────────────────────────────────────────────────

    def index_file(
        self,
        file_path: str,
        document_id: Optional[str] = None,
        display_name: Optional[str] = None,   # original filename for citations
    ) -> dict:
        document_id = document_id or str(uuid.uuid4())
        logger.info(f"Indexing file: {file_path} [doc_id={document_id}]")

        raw_docs = load_file(file_path)

        # Override the source metadata with the original filename so citations
        # show "company_policy.pdf" not the temp UUID path
        if display_name:
            for doc in raw_docs:
                doc.metadata["source"] = display_name

        return self._index_raw_docs(raw_docs, document_id)

    def index_url(self, url: str, document_id: Optional[str] = None) -> dict:
        document_id = document_id or str(uuid.uuid4())
        logger.info(f"Indexing URL: {url} [doc_id={document_id}]")

        raw_docs = load_url(url)
        return self._index_raw_docs(raw_docs, document_id)

    def index_text(self, text: str, source_name: str = "manual", document_id: Optional[str] = None) -> dict:
        document_id = document_id or str(uuid.uuid4())
        raw_docs = [RawDocument(text=text, metadata={"source": source_name, "type": "text"})]
        return self._index_raw_docs(raw_docs, document_id)

    def _index_raw_docs(self, raw_docs: List[RawDocument], document_id: str) -> dict:
        chunks = chunk_documents(
            raw_docs,
            strategy=self.chunk_strategy,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            embedder=self.embedder if self.chunk_strategy == "semantic" else None,
        )

        if not chunks:
            logger.warning("No chunks produced — document may be empty")
            return {"document_id": document_id, "chunks_indexed": 0}

        texts = [c.text for c in chunks]
        embeddings = self.embedder.embed_batch(texts)

        self.vector_store.upsert_chunks(chunks, embeddings, document_id)
        self._rebuild_bm25()

        return {
            "document_id": document_id,
            "chunks_indexed": len(chunks),
        }

    def _rebuild_bm25(self):
        # Fetch all documents from ChromaDB to rebuild the BM25 index
        try:
            all_data = self.vector_store._collection.get(include=["documents", "metadatas"])
            if all_data["ids"]:
                self.bm25_index.build(
                    texts=all_data["documents"],
                    chunk_ids=all_data["ids"],
                    metadatas=all_data["metadatas"],
                )
        except Exception as e:
            logger.warning(f"BM25 rebuild failed: {e}")

    # ── Querying ──────────────────────────────────────────────────────────

    def query(
        self,
        question: str,
        where: Optional[dict] = None,
    ) -> GenerationResult:
        logger.info(f"Query: '{question[:80]}...' " if len(question) > 80 else f"Query: '{question}'")

        # Embed the query
        query_embedding = self.embedder.embed_text(question)

        # Dense retrieval
        dense_results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=self.retrieval_top_k,
            where=where,
        )

        # Hybrid: merge with BM25
        if self.use_hybrid_search:
            sparse_results = self.bm25_index.search(question, top_k=self.retrieval_top_k)
            results = reciprocal_rank_fusion(dense_results, sparse_results)
        else:
            results = dense_results

        if not results:
            logger.warning("No results retrieved — knowledge base may be empty")
            return GenerationResult(
                answer="I don't have any documents to search. Please upload documents first.",
                sources=[],
                model="none",
            )

        # Rerank
        if self.reranker and len(results) > 1:
            results = self.reranker.rerank(question, results, top_k=self.rerank_top_k)
        else:
            results = results[:self.rerank_top_k]

        # Generate answer
        result = self.generator.generate(
            query=question,
            context_results=results,
        )

        logger.info(f"Generated answer: {result.prompt_tokens} prompt tokens, "
                    f"{result.completion_tokens} completion tokens")
        return result

    # ── Info ──────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "vector_store": self.vector_store.collection_info(),
            "embedding_model": self.embedder._model_name,
            "llm_model": self.generator._model,
            "hybrid_search": self.use_hybrid_search,
            "reranking": self.use_reranker,
        }
