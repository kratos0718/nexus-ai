# Day 19 — Configurable Chunking Strategies

## What we built

Exposed the three existing chunking strategies (recursive, semantic, fixed) as a user-controlled option. Every document upload now accepts a `chunking_strategy` field. The semantic chunker — which uses embedding similarity between consecutive sentences to detect topic boundaries — is now user-accessible. The change is threaded through the pipeline, RAG service, Celery worker, and frontend upload UI.

---

## Files modified

| File | Change |
|------|--------|
| `backend/app/rag/pipeline.py` | Added `chunk_strategy` override param to `index_file` and `_index_raw_docs` |
| `backend/app/api/v1/endpoints/documents.py` | Added `chunking_strategy: str = Form("recursive")` to upload endpoint |
| `backend/app/services/rag_service.py` | Threaded `chunk_strategy` through `index_file_background` |
| `backend/app/workers/document_tasks.py` | Added `chunk_strategy` param to Celery task |
| `frontend/src/app/(app)/dashboard/page.tsx` | Added strategy dropdown + appends to FormData |
| `learning/concepts/27_chunking_strategies.md` | 7-level concept guide |

---

## The key design decision: per-call override

The pipeline is a singleton — it's initialized once with `chunk_strategy="recursive"`. Rather than creating separate pipeline instances per strategy (wasteful), we added an optional `chunk_strategy` override to `index_file` and `_index_raw_docs`:

```python
def _index_raw_docs(self, raw_docs, document_id, chunk_strategy=None):
    strategy = chunk_strategy or self.chunk_strategy  # override if provided, else use default
    chunks = chunk_documents(
        raw_docs,
        strategy=strategy,
        chunk_size=self.chunk_size,
        chunk_overlap=self.chunk_overlap,
        embedder=self.embedder if strategy == "semantic" else None,
    )
```

The `embedder` is only passed when strategy is `"semantic"` — it's the expensive ingredient that semantic chunking needs. Recursive and fixed chunking don't touch the embedder.

---

## Why `embedder` must only pass for semantic

The semantic chunker calls `embedder.embed_batch(sentences)` on every sentence in the document before deciding where to split. For a 5000-word document with ~300 sentences, this is 300 embedding calls (batched, but still significant CPU).

Passing `embedder=None` for non-semantic strategies means the chunker never tries to embed sentences — it just splits on character boundaries or structural markers. This is both correct and efficient.

---

## The Form + File pattern

FastAPI supports mixing `File()` and `Form()` parameters in the same endpoint:

```python
@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    chunking_strategy: str = Form("recursive"),
    ...
):
```

The client sends `multipart/form-data` with two parts: the file binary and the strategy string. The frontend appends both to FormData:

```typescript
const form = new FormData();
form.append("file", file);
form.append("chunking_strategy", chunkStrategy);  // "recursive" | "semantic" | "fixed"
```

**Backward compatibility:** `Form("recursive")` sets a default. Existing API clients that don't send `chunking_strategy` get recursive chunking — same as before.

---

## Celery task signature update

Celery serializes task arguments. Adding `chunk_strategy="recursive"` as a default-valued parameter is backward compatible — old tasks in the queue (without chunk_strategy) will use the default.

```python
def index_document(self, document_id, file_path, filename, chunk_strategy="recursive"):
    result = pipeline.index_file(
        file_path=file_path,
        document_id=document_id,
        display_name=filename,
        chunk_strategy=chunk_strategy,   # ← passed through
    )
```

---

## What the strategies produce (for the same document)

**Recursive (default):**
- Splits on `\n\n` → paragraphs stay together
- Predictable chunk count: ≈ document_size / chunk_size
- Good for well-structured documents (PDFs, Markdown, technical docs)

**Semantic:**
- Splits where embedding similarity between consecutive sentences drops sharply
- Chunk count is variable — determined by topic structure
- Good for raw text without structure (transcripts, OCR, web scrapes)
- Slower indexing (embeds all sentences before splitting)
- Chunks visible in Knowledge Base Explorer show more coherent topics

**Fixed:**
- Splits every N characters regardless of content
- Predictable, uniform chunk sizes
- Useful for benchmarking or comparing against recursive/semantic

---

## How to test the difference

1. Upload the same document twice — once with "Recursive", once with "Semantic"
2. Open the Knowledge Base Explorer for each document
3. Compare chunk text: semantic chunks should align with topic shifts, recursive chunks should align with paragraph breaks
4. Search the same query in both — semantic may retrieve more relevant chunks for topic-spanning questions

---

## Validation

The endpoint validates the strategy before writing any files:

```python
VALID_CHUNK_STRATEGIES = {"recursive", "semantic", "fixed"}
if chunking_strategy not in VALID_CHUNK_STRATEGIES:
    raise HTTPException(400, detail=f"Invalid chunking_strategy...")
```

This prevents the `chunk_documents()` function from receiving an unknown strategy and raising an internal error, which would leave the document stuck in PENDING status.
