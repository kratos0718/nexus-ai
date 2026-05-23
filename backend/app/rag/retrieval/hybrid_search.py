"""
Hybrid search: combines dense (semantic) + sparse (BM25 keyword) retrieval.

Dense search finds semantically similar chunks even when exact words differ.
BM25 search finds exact keyword matches that dense search might miss.
Reciprocal Rank Fusion (RRF) merges both result lists.
"""

from typing import Dict, List

from loguru import logger

from app.rag.retrieval.vector_store import SearchResult


def reciprocal_rank_fusion(
    dense_results: List[SearchResult],
    sparse_results: List[SearchResult],
    k: int = 60,
    dense_weight: float = 0.7,
    sparse_weight: float = 0.3,
) -> List[SearchResult]:
    """
    RRF score = Σ weight / (k + rank)
    Merges two ranked lists without requiring score normalization.
    """
    scores: Dict[str, float] = {}
    chunks: Dict[str, SearchResult] = {}

    for rank, result in enumerate(dense_results):
        cid = result.chunk_id
        scores[cid] = scores.get(cid, 0.0) + dense_weight / (k + rank + 1)
        chunks[cid] = result

    for rank, result in enumerate(sparse_results):
        cid = result.chunk_id
        scores[cid] = scores.get(cid, 0.0) + sparse_weight / (k + rank + 1)
        if cid not in chunks:
            chunks[cid] = result

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    fused = []
    for cid, fused_score in merged:
        result = chunks[cid]
        result.score = fused_score
        fused.append(result)

    logger.debug(f"RRF merged {len(dense_results)} dense + {len(sparse_results)} sparse "
                 f"→ {len(fused)} unique results")
    return fused


class BM25Index:
    """
    In-memory BM25 index over stored chunks.
    Rebuilt when documents are added or removed.
    """

    def __init__(self):
        self._corpus: List[str] = []
        self._chunk_ids: List[str] = []
        self._metadatas: List[dict] = []
        self._bm25 = None

    def build(self, texts: List[str], chunk_ids: List[str], metadatas: List[dict]):
        from rank_bm25 import BM25Okapi

        self._corpus = texts
        self._chunk_ids = chunk_ids
        self._metadatas = metadatas
        tokenized = [t.lower().split() for t in texts]
        self._bm25 = BM25Okapi(tokenized)
        logger.info(f"BM25 index built with {len(texts)} documents")

    @property
    def is_built(self) -> bool:
        return self._bm25 is not None

    def search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        if self._bm25 is None:
            return []

        tokens = query.lower().split()
        scores = self._bm25.get_scores(tokens)

        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for idx, score in ranked:
            if score > 0:
                results.append(SearchResult(
                    text=self._corpus[idx],
                    score=float(score),
                    metadata=self._metadatas[idx],
                    chunk_id=self._chunk_ids[idx],
                ))
        return results
