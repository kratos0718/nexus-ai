"""
Embedding engine with provider abstraction.

Supports HuggingFace sentence-transformers (local, free) and OpenAI (cloud).
Swapping providers requires zero changes in the calling code.
"""

from abc import ABC, abstractmethod
from typing import List
import numpy as np
from loguru import logger


# ── Abstract Base: defines the CONTRACT ───────────────────────────────
# Any embedding provider (HuggingFace, OpenAI, Cohere) must implement this
class BaseEmbedder(ABC):

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Convert a single text string to an embedding vector."""
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Convert multiple texts to embeddings (more efficient than one-by-one)."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Number of dimensions in the output vector."""
        pass

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Compute cosine similarity between two vectors.
        Returns a value between -1 (opposite) and 1 (identical).

        Formula: cos(θ) = (A · B) / (|A| × |B|)
        We only care about direction (meaning), not magnitude (length of text).
        """
        a = np.array(vec1)
        b = np.array(vec2)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ── HuggingFace Embedder (FREE, runs locally) ─────────────────────────
class HuggingFaceEmbedder(BaseEmbedder):
    """
    Uses sentence-transformers library to generate embeddings locally.
    No API key needed. Runs on your CPU/GPU.

    Model: all-MiniLM-L6-v2
    - Dimension: 384
    - Speed: ~14,000 sentences/second on CPU
    - Size: ~80MB download (cached after first use)
    - Quality: excellent for semantic search tasks
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        logger.info(f"Loading embedding model: {model_name}")
        # Import here to avoid slow startup if not using HuggingFace
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        logger.info(f"Embedding model loaded. Dimension: {self.dimension}")

    def embed_text(self, text: str) -> List[float]:
        """Embed a single piece of text."""
        vector = self._model.encode(text, convert_to_numpy=True)
        return vector.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple texts at once.
        WHY BATCH? Much faster than embedding one-by-one.
        The model processes multiple inputs in parallel on the GPU/CPU.
        """
        vectors = self._model.encode(texts, convert_to_numpy=True, batch_size=32)
        return vectors.tolist()

    @property
    def dimension(self) -> int:
        return self._model.get_embedding_dimension()


# ── Factory Function: creates the right embedder from config ──────────
def get_embedder(provider: str = "huggingface", model_name: str = None) -> BaseEmbedder:
    """
    Factory pattern: return the right embedder based on configuration.

    WHY FACTORY PATTERN?
    The rest of the code never needs to know WHICH embedder is being used.
    Change config → different embedder, zero code change elsewhere.
    """
    if provider == "huggingface":
        model = model_name or "all-MiniLM-L6-v2"
        return HuggingFaceEmbedder(model_name=model)
    else:
        raise ValueError(f"Unknown embedding provider: {provider}. Supported: huggingface")
