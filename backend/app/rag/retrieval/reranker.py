"""
Cross-encoder reranker.

Takes (query, chunk) pairs and produces precise relevance scores.
Run after bi-encoder retrieval to improve ranking quality.
"""

from typing import List
from loguru import logger

from app.rag.retrieval.vector_store import SearchResult


class CrossEncoderReranker:
    """
    Uses a cross-encoder model that sees (query + document) together
    and outputs a single relevance score — more accurate than cosine similarity.

    Model: cross-encoder/ms-marco-MiniLM-L-6-v2
    Downloads ~80MB on first use, cached after.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        from sentence_transformers import CrossEncoder
        logger.info(f"Loading cross-encoder: {model_name}")
        self._model = CrossEncoder(model_name)
        logger.info("Cross-encoder ready")

    def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: int = 5,
    ) -> List[SearchResult]:
        if not results:
            return results

        pairs = [(query, r.text) for r in results]
        scores = self._model.predict(pairs).tolist()

        # Attach rerank score and sort descending
        scored = sorted(
            zip(scores, results),
            key=lambda x: x[0],
            reverse=True,
        )

        reranked = []
        for new_score, result in scored[:top_k]:
            result.score = float(new_score)
            reranked.append(result)

        return reranked
