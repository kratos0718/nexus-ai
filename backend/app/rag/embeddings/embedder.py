"""
Embedding engine with provider abstraction.

Supports:
  - HuggingFace sentence-transformers (local, free, runs on CPU)
  - OpenAI text-embedding-3-small (cloud, requires API key, used on Vercel)

Swapping providers requires zero changes in the calling code.
"""

from abc import ABC, abstractmethod
from typing import List

import numpy as np
from loguru import logger


class BaseEmbedder(ABC):

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        pass

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        a = np.array(vec1)
        b = np.array(vec2)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ── HuggingFace (local, free) ─────────────────────────────────────────────────

class HuggingFaceEmbedder(BaseEmbedder):
    """
    Runs sentence-transformers locally — no API key, no cost.
    Model: all-MiniLM-L6-v2 — 384-dim, ~80MB download, cached after first use.
    Use for local development.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        logger.info(f"Loading local embedding model: {model_name}")
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        logger.info(f"Local embedding model ready. Dimension: {self.dimension}")

    def embed_text(self, text: str) -> List[float]:
        return self._model.encode(text, convert_to_numpy=True).tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return self._model.encode(texts, convert_to_numpy=True, batch_size=32).tolist()

    @property
    def dimension(self) -> int:
        return self._model.get_embedding_dimension()


# ── OpenAI (cloud, requires key) ─────────────────────────────────────────────

class OpenAIEmbedder(BaseEmbedder):
    """
    Calls OpenAI embeddings API — no large model download, works on Vercel.
    Model: text-embedding-3-small — 1536-dim, ~$0.02/1M tokens.
    Use for cloud/Vercel deployment.
    """

    _DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._model_name = model
        self._dim = self._DIMENSIONS.get(model, 1536)
        logger.info(f"OpenAI embedder ready: model={model} dim={self._dim}")

    def embed_text(self, text: str) -> List[float]:
        resp = self._client.embeddings.create(input=[text], model=self._model)
        return resp.data[0].embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        # OpenAI supports up to 2048 inputs per request
        resp = self._client.embeddings.create(input=texts, model=self._model)
        # Response items are ordered to match input order
        return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]

    @property
    def dimension(self) -> int:
        return self._dim


# ── HuggingFace Inference API (cloud, free) ───────────────────────────────────

class HuggingFaceAPIEmbedder(BaseEmbedder):
    """
    Calls HuggingFace Inference API — completely free, just need HF account.
    Same model as local (all-MiniLM-L6-v2), same 384 dimensions.
    Use for Vercel/cloud deployment instead of running the model locally.
    """

    _API_BASE = "https://api-inference.huggingface.co/pipeline/feature-extraction"

    def __init__(self, api_key: str, model: str = "sentence-transformers/all-MiniLM-L6-v2"):
        import requests as req
        self._requests = req
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._url = f"{self._API_BASE}/{model}"
        self._model_name = model
        self._dim = 384
        logger.info(f"HuggingFace API embedder ready: {model}")

    def _call(self, inputs) -> list:
        resp = self._requests.post(
            self._url,
            headers=self._headers,
            json={"inputs": inputs, "options": {"wait_for_model": True}},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def embed_text(self, text: str) -> List[float]:
        return self._call(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return self._call(texts)

    @property
    def dimension(self) -> int:
        return self._dim


# ── Factory ───────────────────────────────────────────────────────────────────

def get_embedder(
    provider: str = "huggingface",
    model_name: str = None,
    api_key: str = None,
) -> BaseEmbedder:
    if provider == "huggingface":
        return HuggingFaceEmbedder(model_name=model_name or "all-MiniLM-L6-v2")
    elif provider == "huggingface-api":
        if not api_key:
            raise ValueError("HF_API_KEY required when EMBEDDING_PROVIDER=huggingface-api")
        return HuggingFaceAPIEmbedder(api_key=api_key, model=model_name or "sentence-transformers/all-MiniLM-L6-v2")
    elif provider == "openai":
        if not api_key:
            raise ValueError("OPENAI_API_KEY required when EMBEDDING_PROVIDER=openai")
        return OpenAIEmbedder(api_key=api_key, model=model_name or "text-embedding-3-small")
    else:
        raise ValueError(f"Unknown embedding provider: {provider}. Supported: huggingface, huggingface-api, openai")
