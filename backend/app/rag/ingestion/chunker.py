"""
Text chunking strategies.

Three strategies available:
  fixed     — split by character count, simple baseline
  recursive — respects paragraph/sentence/word boundaries (default)
  semantic  — splits at topic boundaries detected via embedding similarity
"""

from dataclasses import dataclass, field
from typing import List, Literal

from loguru import logger

from app.rag.ingestion.loader import RawDocument


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)
    chunk_index: int = 0


ChunkStrategy = Literal["fixed", "recursive", "semantic"]


def chunk_documents(
    docs: List[RawDocument],
    strategy: ChunkStrategy = "recursive",
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    embedder=None,          # required only for strategy="semantic"
) -> List[Chunk]:
    chunks = []
    for doc in docs:
        doc_chunks = _chunk_text(
            doc.text,
            base_metadata=doc.metadata,
            strategy=strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedder=embedder,
        )
        chunks.extend(doc_chunks)

    logger.info(f"Chunked {len(docs)} document(s) into {len(chunks)} chunks "
                f"[strategy={strategy}, size={chunk_size}, overlap={chunk_overlap}]")
    return chunks


def _chunk_text(
    text: str,
    base_metadata: dict,
    strategy: ChunkStrategy,
    chunk_size: int,
    chunk_overlap: int,
    embedder,
) -> List[Chunk]:

    if strategy == "fixed":
        raw_chunks = _fixed_split(text, chunk_size, chunk_overlap)
    elif strategy == "recursive":
        raw_chunks = _recursive_split(text, chunk_size, chunk_overlap)
    elif strategy == "semantic":
        if embedder is None:
            raise ValueError("semantic strategy requires an embedder instance")
        raw_chunks = _semantic_split(text, chunk_size, embedder)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    return [
        Chunk(text=t, metadata={**base_metadata, "strategy": strategy}, chunk_index=i)
        for i, t in enumerate(raw_chunks)
        if t.strip()
    ]


# ── Strategy 1: Fixed Size ─────────────────────────────────────────────

def _fixed_split(text: str, size: int, overlap: int) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return chunks


# ── Strategy 2: Recursive Character (LangChain default) ───────────────

def _recursive_split(text: str, size: int, overlap: int) -> List[str]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )
    return splitter.split_text(text)


# ── Strategy 3: Semantic (embedding-based boundary detection) ──────────

def _semantic_split(text: str, max_chunk_size: int, embedder) -> List[str]:
    """
    Split at topic boundaries: where consecutive sentence similarity drops sharply.
    Sentences in the same topic stay together; split when topic changes.
    """
    import numpy as np

    # Sentence-level split first
    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return [text]

    # Embed all sentences at once
    embeddings = embedder.embed_batch(sentences)

    # Compute cosine similarity between consecutive sentences
    similarities = []
    for i in range(len(embeddings) - 1):
        a = np.array(embeddings[i])
        b = np.array(embeddings[i + 1])
        sim = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))
        similarities.append(sim)

    # Threshold: split where similarity drops below mean - 0.5*std
    mean_sim = np.mean(similarities)
    std_sim = np.std(similarities)
    threshold = mean_sim - 0.5 * std_sim

    # Group sentences into chunks
    chunks = []
    current = [sentences[0]]

    for i, sim in enumerate(similarities):
        next_sentence = sentences[i + 1]
        current_text = " ".join(current)

        is_boundary = sim < threshold
        would_overflow = len(current_text) + len(next_sentence) > max_chunk_size

        if is_boundary or would_overflow:
            chunks.append(current_text)
            current = [next_sentence]
        else:
            current.append(next_sentence)

    if current:
        chunks.append(" ".join(current))

    return chunks


def _split_sentences(text: str) -> List[str]:
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]
