# Day 16 — Knowledge Base Explorer

## What we built

A chunk browser and semantic search tool that lets you inspect what's actually stored in the vector database — making the RAG pipeline visible and debuggable.

---

## Files created / modified

| File | Change |
|------|--------|
| `backend/app/rag/retrieval/vector_store.py` | `get_document_chunks()` on base + ChromaDB |
| `backend/app/api/v1/endpoints/documents.py` | `GET /{id}/chunks` endpoint |
| `backend/app/api/v1/endpoints/search.py` | NEW: `POST /search` pure retrieval endpoint |
| `backend/app/api/v1/router.py` | Registered `/search` router |
| `frontend/src/app/(app)/dashboard/[documentId]/page.tsx` | NEW: chunk browser + search UI |
| `frontend/src/app/(app)/dashboard/page.tsx` | Added "Explore" link per ready document |
| `learning/concepts/24_vector_databases.md` | 8-level concept guide |

---

## Architecture

```
Dashboard → click "Explore" on a ready document
    ↓
GET /documents/{id}/chunks           (paginated, ordered by chunk_index)
    → vector_store.get_document_chunks(document_id)
    → sorted by chunk_index
    → returned 10 at a time with pagination

Search panel on same page → type a query → choose mode → submit
    ↓
POST /search
    → security_guard.validate_question(query)
    → pipeline._retrieve(query, where={"document_id": ...})
    → returns ranked chunks with similarity scores
    → no LLM call, no answer generation
```

---

## The chunks endpoint

```python
# documents.py — new route
@router.get("/{document_id}/chunks")
async def get_document_chunks(document_id, offset=0, limit=20, ...):
    # auth: doc must belong to current_user
    # status: doc must be "ready" (indexing complete)
    all_chunks = pipeline.vector_store.get_document_chunks(document_id)
    page = all_chunks[offset: offset + limit]
    return {
        "total_chunks": len(all_chunks),
        "chunks": [{ "chunk_id", "chunk_index", "text", "page", "char_count" }]
    }
```

Chunks are sorted by `chunk_index` — document reading order. Pagination uses `offset`/`limit` (not page number) so the client controls exactly which slice it wants.

---

## The search endpoint

```python
# POST /search
# body: { query, document_id, top_k, retrieval_mode }
# response: { query, retrieval_mode, chunks: [{ chunk_id, text, score, ... }] }
```

Supports all three retrieval modes — the client can compare results:
```bash
# Standard: embed the question directly
curl -X POST /search -d '{"query": "what is chunking?", "retrieval_mode": "standard"}'

# HyDE: embed a hypothetical answer
curl -X POST /search -d '{"query": "what is chunking?", "retrieval_mode": "hyde"}'

# Multi-query: expand to 3 phrasings, merge
curl -X POST /search -d '{"query": "what is chunking?", "retrieval_mode": "multiquery"}'
```

This is exactly how you'd debug a retrieval quality issue: run the same query in all three modes, compare which chunks surface, see which mode finds the most relevant content.

---

## Vector store change

Added `get_document_chunks()` to `BaseVectorStore` and implemented it for ChromaDB:

```python
def get_document_chunks(self, document_id: str) -> list[SearchResult]:
    results = self._collection.get(
        where={"document_id": document_id},  # metadata filter
        include=["documents", "metadatas"],
    )
    chunks = [SearchResult(text=doc, score=1.0, ...) for doc, meta, id_ in zip(...)]
    chunks.sort(key=lambda c: c.metadata.get("chunk_index", 0))  # reading order
    return chunks
```

Pinecone inherits the base default (returns `[]`) — Pinecone doesn't support fetching all vectors for a namespace without paying for the list API.

---

## Frontend: dynamic route

`/dashboard/[documentId]/page.tsx` is a Next.js dynamic route. The `[documentId]` folder name creates a URL parameter:
- `/dashboard/abc123` → `params.documentId = "abc123"`
- `useParams()` extracts it client-side

```tsx
const params = useParams();
const documentId = params.documentId as string;
// use documentId in API calls
```

The page has two independent panels:
1. **Chunk browser** — pagination controls, ordered by chunk_index
2. **Search panel** — submit a query, choose retrieval mode, get scored results

Both use the same `ChunkCard` component, which shows a 200-char preview with an "expand" toggle.

---

## Why this matters for debugging RAG

Classic RAG debugging workflow:
1. User reports: "It said it couldn't find information about X"
2. Go to `/dashboard/{document_id}` → search for X
3. No results? → X isn't in the indexed chunks → check chunking strategy or document content
4. Results returned? → Click to expand → Is the relevant content present?
5. Content present, retrieval score low? → Try HyDE mode → Compare scores
6. Content present, retrieval correct? → Problem is in generation → check prompt

Without a chunk explorer, step 3-5 requires writing ad-hoc scripts against the vector store directly.
