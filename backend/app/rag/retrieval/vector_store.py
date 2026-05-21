"""
Vector store abstraction with ChromaDB (local) and Pinecone (cloud) backends.

ChromaDB  → local dev, persists to ./chroma_data, no API key needed
Pinecone  → Vercel/cloud, serverless-compatible, requires API key + index
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from loguru import logger

from app.rag.ingestion.chunker import Chunk


@dataclass
class SearchResult:
    text: str
    score: float
    metadata: dict
    chunk_id: str


# ── Abstract base ─────────────────────────────────────────────────────────────

class BaseVectorStore(ABC):

    @abstractmethod
    def upsert_chunks(self, chunks: List[Chunk], embeddings: List[List[float]], document_id: str) -> int:
        pass

    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 5, where: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        pass

    @abstractmethod
    def delete_document(self, document_id: str) -> int:
        pass

    @abstractmethod
    def collection_info(self) -> dict:
        pass

    def get_all_chunks(self) -> tuple[list, list, list]:
        """Return (ids, texts, metadatas) for BM25 rebuild. Override in stores that support it."""
        return [], [], []

    def get_document_chunks(self, document_id: str) -> list["SearchResult"]:
        """Return all stored chunks for one document, ordered by chunk_index."""
        return []


# ── ChromaDB (local) ──────────────────────────────────────────────────────────

class VectorStore(BaseVectorStore):
    """
    ChromaDB-backed store. Runs in-process, persists to disk.
    No API key. Use for local development.
    """

    def __init__(
        self,
        collection_name: str = "nexus_documents",
        host: str = "localhost",
        port: int = 8001,
        persist_path: str = "./chroma_data",
        use_embedded: bool = True,
    ):
        import chromadb

        if use_embedded:
            self._client = chromadb.PersistentClient(path=persist_path)
        else:
            self._client = chromadb.HttpClient(host=host, port=port)

        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._collection_name = collection_name
        logger.info(f"ChromaDB ready: collection='{collection_name}' docs={self._collection.count()}")

    def upsert_chunks(self, chunks: List[Chunk], embeddings: List[List[float]], document_id: str) -> int:
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

        self._collection.upsert(ids=ids, documents=texts, embeddings=vecs, metadatas=metas)
        logger.info(f"Upserted {len(chunks)} chunks for document '{document_id}'")
        return len(chunks)

    def search(self, query_embedding: List[float], top_k: int = 5, where: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        query_params = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, self._collection.count() or 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            query_params["where"] = where

        results = self._collection.query(**query_params)

        return [
            SearchResult(
                text=doc,
                score=1.0 - dist,   # ChromaDB returns cosine distance, convert to similarity
                metadata=meta,
                chunk_id=id_,
            )
            for doc, meta, dist, id_ in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
                results["ids"][0],
            )
        ]

    def delete_document(self, document_id: str) -> int:
        results = self._collection.get(where={"document_id": document_id}, include=["documents"])
        ids = results["ids"]
        if ids:
            self._collection.delete(ids=ids)
            logger.info(f"Deleted {len(ids)} chunks for document '{document_id}'")
        return len(ids)

    def get_all_chunks(self) -> tuple:
        all_data = self._collection.get(include=["documents", "metadatas"])
        return all_data["ids"], all_data["documents"], all_data["metadatas"]

    def get_document_chunks(self, document_id: str) -> list[SearchResult]:
        """Return all stored chunks for one document, ordered by chunk_index."""
        results = self._collection.get(
            where={"document_id": document_id},
            include=["documents", "metadatas"],
        )
        chunks = [
            SearchResult(
                text=doc,
                score=1.0,
                metadata=meta,
                chunk_id=id_,
            )
            for doc, meta, id_ in zip(results["documents"], results["metadatas"], results["ids"])
        ]
        # Sort by chunk_index so they read in document order
        chunks.sort(key=lambda c: c.metadata.get("chunk_index", 0))
        return chunks

    @property
    def count(self) -> int:
        return self._collection.count()

    def collection_info(self) -> dict:
        return {"name": self._collection_name, "count": self.count}


# ── Pinecone (cloud) ──────────────────────────────────────────────────────────

class PineconeVectorStore(BaseVectorStore):
    """
    Pinecone-backed store. Serverless, no local filesystem needed.
    Requires: PINECONE_API_KEY + a pre-created index with matching dimension.
    Use for Vercel/cloud deployment.

    Index setup (one-time, in Pinecone dashboard):
      Name: nexus-ai  |  Dimension: 1536  |  Metric: cosine  |  Cloud: AWS us-east-1
    """

    def __init__(self, api_key: str, index_name: str, dimension: int = 1536):
        from pinecone import Pinecone
        pc = Pinecone(api_key=api_key)
        self._index = pc.Index(index_name)
        self._index_name = index_name
        self._dimension = dimension
        logger.info(f"Pinecone ready: index='{index_name}' dim={dimension}")

    def upsert_chunks(self, chunks: List[Chunk], embeddings: List[List[float]], document_id: str) -> int:
        vectors = []
        for chunk, embedding in zip(chunks, embeddings):
            chunk_id = f"{document_id}_chunk_{chunk.chunk_index}"
            vectors.append({
                "id": chunk_id,
                "values": embedding,
                "metadata": {
                    **chunk.metadata,
                    "document_id": document_id,
                    "chunk_index": chunk.chunk_index,
                    "chunk_id": chunk_id,
                    "text": chunk.text,   # store text in metadata for retrieval
                },
            })

        # Pinecone recommends batches of ≤100
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            self._index.upsert(vectors=vectors[i:i + batch_size])

        logger.info(f"Upserted {len(vectors)} chunks to Pinecone for document '{document_id}'")
        return len(vectors)

    def search(self, query_embedding: List[float], top_k: int = 5, where: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        resp = self._index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
            filter=where,   # Pinecone filter format matches our where dict
        )

        return [
            SearchResult(
                text=match.metadata.get("text", ""),
                score=match.score,
                metadata=match.metadata,
                chunk_id=match.id,
            )
            for match in resp.matches
        ]

    def delete_document(self, document_id: str) -> int:
        self._index.delete(filter={"document_id": {"$eq": document_id}})
        logger.info(f"Deleted chunks for document '{document_id}' from Pinecone")
        return 0   # Pinecone doesn't return deleted count

    # Pinecone doesn't support fetching all vectors — BM25 is disabled in cloud mode
    def get_all_chunks(self) -> tuple:
        return [], [], []

    def collection_info(self) -> dict:
        stats = self._index.describe_index_stats()
        return {"name": self._index_name, "count": stats.total_vector_count}


# ── Factory ───────────────────────────────────────────────────────────────────

def get_vector_store(
    provider: str = "chroma",
    collection_name: str = "nexus_documents",
    persist_path: str = "./chroma_data",
    pinecone_api_key: str = None,
    pinecone_index_name: str = "nexus-ai",
    embedding_dimension: int = 384,
) -> BaseVectorStore:
    if provider == "chroma":
        return VectorStore(
            collection_name=collection_name,
            persist_path=persist_path,
            use_embedded=True,
        )
    elif provider == "pinecone":
        if not pinecone_api_key:
            raise ValueError("PINECONE_API_KEY required when VECTOR_STORE_PROVIDER=pinecone")
        return PineconeVectorStore(
            api_key=pinecone_api_key,
            index_name=pinecone_index_name,
            dimension=embedding_dimension,
        )
    else:
        raise ValueError(f"Unknown vector store provider: {provider}. Supported: chroma, pinecone")
