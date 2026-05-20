# Day 2 — Document Ingestion, Chunking, Vector Store, Full RAG Pipeline

**Date:** 2026-05-20  
**Phase:** RAG Foundation  
**Status:** Complete — all 7 stages passing  

---

## What I Built Today

### Files Created
- `backend/app/rag/ingestion/loader.py` — loads PDF, TXT, DOCX, URLs into `RawDocument` objects
- `backend/app/rag/ingestion/chunker.py` — 3 chunking strategies: fixed, recursive, semantic
- `backend/app/rag/retrieval/vector_store.py` — ChromaDB wrapper (embedded + HTTP modes)
- `backend/app/rag/retrieval/hybrid_search.py` — BM25 index + Reciprocal Rank Fusion
- `backend/app/rag/retrieval/reranker.py` — cross-encoder reranking
- `backend/app/rag/generation/generator.py` — Groq LLM generation with citations
- `backend/app/rag/pipeline.py` — full orchestrator tying all stages together
- `backend/test_pipeline.py` — end-to-end test (all 7 stages)
- `backend/sample_docs/company_policy.txt` — test document (ACME HR policy)

### Verified Results
```
Loading    : 1 doc, 3852 chars loaded from TXT ✅
Chunking   : fixed=10 chunks, recursive=11 chunks (recursive respects sentences) ✅
Embedding  : 6 chunks in 0.45s, 13 chunks/sec, 384-dim ✅
Vector Store: 6 chunks stored in ChromaDB embedded mode ✅
Retrieval  : Dense score=0.496 for correct chunk ✅
Hybrid     : BM25 + RRF merged 5 dense + 5 sparse → 6 unique ✅
Reranking  : Cross-encoder score=3.17 for best chunk ✅
Generation : "Full-time employees are entitled to 20 days..." ✅
Tokens     : 529 prompt + 53 completion (Groq llama-3.3-70b)
```

---

## Key Concepts — see concepts/ files for deep explanations

- `concepts/04_chunking_strategies.md` — fixed vs recursive vs semantic, why overlap matters
- `concepts/05_hybrid_search.md` — BM25, RRF, dense vs sparse retrieval
- `concepts/06_reranking.md` — bi-encoder vs cross-encoder, why rerank after retrieve

---

## Architecture Pattern: Orchestrator + Specialized Components

```
RAGPipeline (orchestrator)
    ├── HuggingFaceEmbedder  (single responsibility: text → vector)
    ├── VectorStore          (single responsibility: store + search vectors)
    ├── BM25Index            (single responsibility: keyword search)
    ├── CrossEncoderReranker (single responsibility: precise relevance scoring)
    └── GroqGenerator        (single responsibility: LLM generation)
```

Each component has ONE job. The pipeline coordinates them.  
Swap any component without touching the others.  
This is the Open/Closed Principle — open for extension, closed for modification.

---

## ChromaDB Embedded vs HTTP Mode

```python
# Embedded (no Docker, dev-friendly):
client = chromadb.PersistentClient(path="./chroma_data")

# HTTP (Docker/production):
client = chromadb.HttpClient(host="localhost", port=8001)
```

Same API, different backend. Data persists to disk in embedded mode.  
Switch to HTTP for production where ChromaDB runs as a separate service.

---

## Chunking Comparison — Real Numbers

| Strategy | Chunks | Avg Size | Respects Sentences |
|----------|--------|----------|--------------------|
| Fixed | 10 | 475 chars | No |
| Recursive | 11 | 356 chars | Yes |

Recursive produced more chunks because it splits at `\n\n` first (paragraphs),  
then `\n` (lines), then `. ` (sentences) — only splits by character as last resort.  
This keeps semantically related text together.

---

## Retrieval Score Interpretation

```
Dense (cosine similarity):   0.496 → 49.6% similar direction
BM25 (TF-IDF based):        0.847 → high keyword match
RRF fused:                   0.016 → normalized rank score (not a percentage)
Cross-encoder:               3.17  → raw logit score (higher = more relevant)
```

Cross-encoder scores are NOT bounded 0–1. They are raw logits.  
Positive = relevant, negative = not relevant.  
Sort descending — only relative ordering matters.

---

## Interview Q&As Added Today

See `interview-prep/100_questions.md` sections 4–6 (chunking, hybrid search, reranking).

---

## What to Fix / Improve Tomorrow (Day 3)

- BM25 rebuild is O(n) — full rescan of ChromaDB on every insert. Need incremental update.
- Reranker loads model at startup — should be lazy-loaded.
- No error handling for ChromaDB connection failure.
- Pipeline needs async support for FastAPI integration (Day 4).

---

## Tomorrow — Day 3

**Goal:** FastAPI endpoints for document upload and querying

1. `POST /api/v1/documents/upload` — accepts file, runs indexing pipeline
2. `POST /api/v1/chat/query` — accepts question, returns answer + sources
3. Background task pattern (so upload doesn't block the HTTP response)
4. Pydantic schemas for request/response validation
5. Error handling middleware
