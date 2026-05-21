"""
RAG pipeline orchestrator.

Single entry point that coordinates:
  indexing  → load → chunk → embed → store
  retrieval → embed query → search → rerank → generate

Provider selection via environment variables:
  EMBEDDING_PROVIDER=huggingface (local dev) | openai (cloud/Vercel)
  VECTOR_STORE_PROVIDER=chroma (local dev)   | pinecone (cloud/Vercel)
"""

import uuid
from typing import List, Optional
from loguru import logger

from app.rag.ingestion.loader import RawDocument, load_file, load_url
from app.rag.ingestion.chunker import chunk_documents, ChunkStrategy
from app.rag.embeddings.embedder import BaseEmbedder, get_embedder
from app.rag.retrieval.vector_store import BaseVectorStore, get_vector_store
from app.rag.retrieval.hybrid_search import BM25Index, reciprocal_rank_fusion
from app.rag.generation.generator import GroqGenerator, GenerationResult


class RAGPipeline:

    def __init__(
        self,
        groq_api_key: str,
        # Embedding config
        embedding_provider: str = "huggingface",
        embedding_model: str = "all-MiniLM-L6-v2",
        openai_api_key: str = "",
        hf_api_key: str = "",
        # Vector store config
        vector_store_provider: str = "chroma",
        collection_name: str = "nexus_documents",
        chroma_persist_path: str = "./chroma_data",
        pinecone_api_key: str = "",
        pinecone_index_name: str = "nexus-ai",
        embedding_dimension: int = 384,
        # LLM config
        llm_model: str = "llama-3.3-70b-versatile",
        # RAG config
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
        self.use_hybrid_search = use_hybrid_search

        logger.info(f"Initializing RAG pipeline: embed={embedding_provider} store={vector_store_provider}")

        embedding_api_key = hf_api_key or openai_api_key or None
        self.embedder: BaseEmbedder = get_embedder(
            provider=embedding_provider,
            model_name=embedding_model,
            api_key=embedding_api_key,
        )

        self.vector_store: BaseVectorStore = get_vector_store(
            provider=vector_store_provider,
            collection_name=collection_name,
            persist_path=chroma_persist_path,
            pinecone_api_key=pinecone_api_key or None,
            pinecone_index_name=pinecone_index_name,
            embedding_dimension=embedding_dimension,
        )

        self.bm25_index = BM25Index()

        self.generator = GroqGenerator(api_key=groq_api_key, model=llm_model)

        # Reranker uses sentence-transformers — skip on cloud where it's not installed
        self.reranker = None
        if use_reranker:
            try:
                from app.rag.retrieval.reranker import CrossEncoderReranker
                self.reranker = CrossEncoderReranker()
            except Exception as e:
                logger.warning(f"Reranker unavailable (cloud mode): {e}")

        logger.info("RAG pipeline ready")

    # ── Indexing ──────────────────────────────────────────────────────────────

    def index_file(self, file_path: str, document_id: Optional[str] = None, display_name: Optional[str] = None, chunk_strategy: Optional[str] = None) -> dict:
        document_id = document_id or str(uuid.uuid4())
        logger.info(f"Indexing file: {file_path} [doc_id={document_id}, strategy={chunk_strategy or self.chunk_strategy}]")
        raw_docs = load_file(file_path)
        if display_name:
            for doc in raw_docs:
                doc.metadata["source"] = display_name
        return self._index_raw_docs(raw_docs, document_id, chunk_strategy=chunk_strategy)

    def index_url(self, url: str, document_id: Optional[str] = None) -> dict:
        document_id = document_id or str(uuid.uuid4())
        raw_docs = load_url(url)
        return self._index_raw_docs(raw_docs, document_id)

    def index_text(self, text: str, source_name: str = "manual", document_id: Optional[str] = None) -> dict:
        document_id = document_id or str(uuid.uuid4())
        raw_docs = [RawDocument(text=text, metadata={"source": source_name, "type": "text"})]
        return self._index_raw_docs(raw_docs, document_id)

    def _index_raw_docs(self, raw_docs: List[RawDocument], document_id: str, chunk_strategy: Optional[str] = None) -> dict:
        strategy = chunk_strategy or self.chunk_strategy
        chunks = chunk_documents(
            raw_docs,
            strategy=strategy,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            embedder=self.embedder if strategy == "semantic" else None,
        )

        if not chunks:
            logger.warning("No chunks produced — document may be empty")
            return {"document_id": document_id, "chunks_indexed": 0}

        embeddings = self.embedder.embed_batch([c.text for c in chunks])
        self.vector_store.upsert_chunks(chunks, embeddings, document_id)
        self._rebuild_bm25()

        return {"document_id": document_id, "chunks_indexed": len(chunks)}

    def _rebuild_bm25(self):
        try:
            ids, texts, metas = self.vector_store.get_all_chunks()
            if ids:
                self.bm25_index.build(texts=texts, chunk_ids=ids, metadatas=metas)
        except Exception as e:
            logger.warning(f"BM25 rebuild skipped: {e}")

    # ── Querying ──────────────────────────────────────────────────────────────

    def _retrieve(self, question: str, where: Optional[dict] = None):
        query_embedding = self.embedder.embed_text(question)

        dense_results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=self.retrieval_top_k,
            where=where,
        )

        if self.use_hybrid_search and self.bm25_index.is_built:
            sparse_results = self.bm25_index.search(question, top_k=self.retrieval_top_k)
            results = reciprocal_rank_fusion(dense_results, sparse_results)
        else:
            results = dense_results

        if not results:
            return []

        if self.reranker and len(results) > 1:
            return self.reranker.rerank(question, results, top_k=self.rerank_top_k)
        return results[:self.rerank_top_k]

    def query(self, question: str, where: Optional[dict] = None, history: Optional[list] = None) -> GenerationResult:
        logger.info(f"Query: '{question[:80]}'")
        results = self._retrieve(question, where=where)

        if not results:
            return GenerationResult(
                answer="I don't have any documents to search. Please upload documents first.",
                sources=[],
                model="none",
            )

        return self.generator.generate(query=question, context_results=results, history=history)

    def stats(self) -> dict:
        return {
            "vector_store": self.vector_store.collection_info(),
            "embedding_model": self.embedder._model_name,
            "llm_model": self.generator._model,
            "hybrid_search": self.use_hybrid_search,
            "reranking": self.reranker is not None,
        }
