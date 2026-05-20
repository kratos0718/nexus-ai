"""
Vector store abstraction over ChromaDB.

Handles: collection management, upsert, similarity search,
metadata filtering, deletion, and collection stats.
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from loguru import logger

from app.rag.ingestion.chunker import Chunk


@dataclass
class SearchResult:
    text: str
    score: float            # cosine similarity (higher = more relevant)
    metadata: dict
    chunk_id: str


class VectorStore:
    """
    ChromaDB-backed vector store.

    Each knowledge base (per user, per project) gets its own collection.
    Embeddings are stored alongside original text and metadata.
    """

    def __init__(
        self,
        collection_name: str = "nexus_documents",
        host: str = "localhost",
        port: int = 8001,
        persist_path: str = "./chroma_data",   # used in embedded mode
        use_embedded: bool = True,              # False = HTTP client (Docker)
    ):
        import chromadb

        if use_embedded:
            # Embedded mode: runs in-process, persists to disk. No Docker needed.
            self._client = chromadb.PersistentClient(path=persist_path)
        else:
            # HTTP mode: connects to a running ChromaDB server (Docker)
            self._client = chromadb.HttpClient(host=host, port=port)

        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._collection_name = collection_name
        logger.info(f"VectorStore ready: collection='{collection_name}' "
                    f"docs={self._collection.count()} "
                    f"mode={'embedded' if use_embedded else 'http'}")

    # ── Write ────────────────────────────────────────────────────────────

    def upsert_chunks(
        self,
        chunks: List[Chunk],
        embeddings: List[List[float]],
        document_id: str,
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")

        ids, texts, metas, vecs = [], [], [], []

        for chunk, embedding in zip(chunks, embeddings):
            chunk_id = f"{document_id}_chunk_{chunk.chunk_index}"
            meta = {
                **chunk.metadata,
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "chunk_id": chunk_id,
            }
            ids.append(chunk_id)
            texts.append(chunk.text)
            metas.append(meta)
            vecs.append(embedding)

        self._collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=vecs,
            metadatas=metas,
        )

        logger.info(f"Upserted {len(chunks)} chunks for document '{document_id}'")
        return len(chunks)

    # ── Read ─────────────────────────────────────────────────────────────

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        query_params = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, self._collection.count() or 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            query_params["where"] = where

        results = self._collection.query(**query_params)

        search_results = []
        for doc, meta, dist, id_ in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
            results["ids"][0],
        ):
            # ChromaDB cosine distance = 1 - similarity; convert back
            similarity = 1.0 - dist
            search_results.append(SearchResult(
                text=doc,
                score=similarity,
                metadata=meta,
                chunk_id=id_,
            ))

        return search_results

    # ── Delete ───────────────────────────────────────────────────────────

    def delete_document(self, document_id: str) -> int:
        results = self._collection.get(
            where={"document_id": document_id},
            include=["documents"],
        )
        ids = results["ids"]
        if ids:
            self._collection.delete(ids=ids)
            logger.info(f"Deleted {len(ids)} chunks for document '{document_id}'")
        return len(ids)

    # ── Stats ────────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return self._collection.count()

    def collection_info(self) -> dict:
        return {
            "name": self._collection_name,
            "count": self.count,
        }
