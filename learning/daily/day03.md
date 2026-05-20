# Day 3 — FastAPI Backend: Endpoints, DB, Schemas, Background Tasks

**Date:** 2026-05-20  
**Phase:** Backend  
**Status:** Complete — all endpoints tested live  

---

## What I Built Today

| File | Purpose |
|------|---------|
| `app/core/database.py` | SQLAlchemy async engine, session factory, `get_db` dependency |
| `app/models/document.py` | Document ORM model (tracks indexing status in SQLite) |
| `app/schemas/document.py` | Pydantic shapes for document upload/list/status responses |
| `app/schemas/chat.py` | Pydantic shapes for query request/response |
| `app/services/rag_service.py` | Business logic — coordinates DB + RAG pipeline |
| `app/api/v1/endpoints/documents.py` | 5 document management endpoints |
| `app/api/v1/endpoints/chat.py` | Query endpoint + health check |
| `app/api/v1/router.py` | Combines all routers under `/api/v1` |
| `app/main.py` | App creation, middleware, lifespan, global error handler |

---

## Verified API Results

```
POST /api/v1/documents/upload
  → 202 Accepted immediately
  → {document_id, filename, status: "pending"}
  → background indexing starts

GET /api/v1/documents/{id}/status  (after 40s)
  → {status: "ready", chunks_count: 6}

POST /api/v1/chat/query
  → question: "What is the salary increment for rating 5?"
  → answer: "18% plus a special bonus of up to 30% of annual CTC"
  → cross-encoder score: +2.90 (correct chunk), -8.68 (wrong chunks)
  → 992 prompt tokens + 83 completion tokens

GET /api/v1/documents/
  → {documents: [...], total: 1}
```

---

## Key Code Blocks — Explained

### 1. FastAPI Dependency Injection — `get_db`

```python
# app/core/database.py

async def get_db():
    async with AsyncSessionLocal() as session:  # creates new DB session
        try:
            yield session        # hands session to the endpoint function
            await session.commit()  # if no error, commit changes
        except Exception:
            await session.rollback()  # if error, undo all changes
            raise
```

**How it's used in endpoints:**
```python
@router.get("/documents/")
async def list_documents(db: AsyncSession = Depends(get_db)):
    #                                        ^^^^^^^^^^^^^^
    #              FastAPI sees Depends(get_db) and calls get_db()
    #              The yielded session is passed in as `db`
    #              After the function returns, get_db() resumes and commits/rollbacks
    docs = await rag_service.list_documents(db)
    return docs
```

**Why this pattern?**
- One DB session per HTTP request (not one global session — race conditions)
- Automatically commits on success, rolls back on error
- Endpoint code never touches session lifecycle — separation of concerns
- Same pattern used at every serious FastAPI production app

---

### 2. Background Tasks — Why 202 Accepted?

```python
# app/api/v1/endpoints/documents.py

@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
#                                   ^^^^^^^^^^^^^^^^^^^^^^^^
#            202 = "I received your request, processing started, check back later"
#            NOT 200 ("done") because indexing takes 30-60 seconds

async def upload_document(
    background_tasks: BackgroundTasks,   # FastAPI injects this automatically
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    # 1. Save file to disk
    temp_path.write_bytes(file_bytes)

    # 2. Create DB row with status="pending"
    await rag_service.create_document_record(db, document_id, ...)

    # 3. Queue the heavy work — does NOT block the response
    background_tasks.add_task(
        rag_service.index_file_background,
        file_path=str(temp_path),
        document_id=document_id,
        db=db,
    )
    #   ↑ This returns immediately. The HTTP response is sent NOW.
    #   The background task runs AFTER the response is sent.

    return DocumentUploadResponse(status="pending", ...)
    # Response arrives in ~50ms, not 40 seconds
```

**The full flow timeline:**
```
t=0ms    → POST /upload received
t=10ms   → file saved, DB row created, background task queued
t=15ms   → 202 response returned to client   ← client unblocked!
t=16ms   → background task starts: load file, chunk, embed, store
t=40,000ms → background task done: DB row updated to status="ready"
```

**Without background tasks:** client waits 40 seconds for a response — terrible UX.  
**With background tasks:** client gets a response in 15ms, polls for status.

---

### 3. run_in_executor — Making Sync Code Work in Async FastAPI

```python
# app/services/rag_service.py

async def index_file_background(self, file_path, document_id, db):
    loop = asyncio.get_event_loop()

    result = await loop.run_in_executor(
        None,          # None = use the default thread pool
        lambda: pipeline.index_file(file_path, document_id=document_id)
        #       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        #       pipeline.index_file() is SYNCHRONOUS (blocks the thread)
        #       run_in_executor() runs it in a worker thread
        #       "await" suspends THIS coroutine until the thread finishes
        #       while waiting, FastAPI handles OTHER requests on the event loop
    )
```

**Why this matters:**
```
WITHOUT run_in_executor:
  Request 1 → pipeline.index_file()  ← BLOCKS EVENT LOOP for 40 seconds
  Request 2 → waiting...             ← completely blocked
  Request 3 → waiting...             ← completely blocked

WITH run_in_executor:
  Request 1 → run_in_executor(pipeline.index_file)  → thread pool
  Request 2 → handled immediately  ← event loop is FREE
  Request 3 → handled immediately  ← event loop is FREE
  (40 seconds later) thread pool finishes → request 1 result ready
```

The event loop is single-threaded. CPU-heavy operations (embedding, inference)  
must run in a thread pool so they don't freeze the server for all other users.

---

### 4. Pydantic Schemas — The Contract Layer

```python
# app/schemas/chat.py

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    #               ^^^   ^^^  ^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^
    #               req  desc  auto-validated  auto-validated
    #
    #  If client sends question="" → FastAPI returns 422 automatically
    #  If client sends question="a" → 422 (less than min_length=3)
    #  Zero custom validation code needed

    document_id: Optional[str] = Field(None, ...)
    #            ^^^^^^^^^^^^               ^^^^
    #            can be null               default is None

    top_k: int = Field(5, ge=1, le=20)
    #                  ^  ^^^^  ^^^^^
    #               default ≥1   ≤20
```

**Schema vs ORM Model — key difference:**
```
ORM Model (Document):         Schema (DocumentStatusResponse):
  Talks to the DATABASE          Talks to the CLIENT (API)
  Has SQLAlchemy columns         Has Pydantic fields
  Stored in nexus.db             Sent over HTTP as JSON
  Has internal fields            Only exposes what client needs
  (e.g., raw SQL types)          (no internal DB internals)

model_config = {"from_attributes": True}
# ↑ Allows schema to be built from an ORM object automatically:
# DocumentStatusResponse.model_validate(db_document)
```

---

### 5. SQLAlchemy ORM Model — Mapped Columns

```python
# app/models/document.py

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #  ^^^^^^^^^^^^ = ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    #  Python type    SQLAlchemy column definition
    #  (type hints)   (maps to actual DB column)

    document_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    #                                                     ^^^^^^^^^   ^^^^^^^^^^
    #                                                    no duplicates  faster lookups

    status: Mapped[DocumentStatus] = mapped_column(SAEnum(DocumentStatus), ...)
    #                                              ^^^^^^^^^^^^^^^^^^^^^^^
    #             Only values in the Enum are allowed at the DB level
    #             DB enforces: "pending"|"processing"|"ready"|"failed"
```

---

### 6. Layered Architecture in Practice

```
HTTP Request → documents.py (endpoint)
                    ↓  calls
               rag_service.py (service)
                    ↓  calls two things:
          pipeline.py (RAG)   +   database.py (DB)
               ↓                        ↓
          ChromaDB                    SQLite

Why this separation?
• Endpoint only handles HTTP: parsing, validation, status codes
• Service only handles business rules: "if doc not ready, raise 409"
• Pipeline only handles AI: chunk, embed, retrieve, generate
• Database only handles persistence: store, query, update

You can test rag_service.py WITHOUT starting the HTTP server.
You can swap SQLite → PostgreSQL WITHOUT touching rag_service.py.
You can change the API response shape WITHOUT touching the pipeline.
```

---

## Architecture Concepts Learned

### The 202 Accepted Pattern (Async Job API)

Standard pattern for any operation taking >1 second:
```
POST /upload → 202 {job_id: "abc"}        (immediate)
GET  /jobs/abc/status → {status: "processing"} (poll)
GET  /jobs/abc/status → {status: "ready"}  (done)
```

Used by: GitHub Actions, AWS Lambda, Stripe webhooks, all ML serving APIs.

### Dependency Injection (FastAPI's Depends)

`Depends(get_db)` is FastAPI's IoC (Inversion of Control) container.  
The endpoint says "I need a DB session" — FastAPI provides it.  
The endpoint never constructs its own session.  
Benefits: testable (swap real DB for mock), consistent lifecycle, no boilerplate.

### HTTP Status Codes (Know These Cold)

| Code | Meaning | When to use |
|------|---------|-------------|
| 200 | OK | GET success, synchronous POST success |
| 201 | Created | Resource created (POST that creates something) |
| 202 | Accepted | Async job started, processing in background |
| 204 | No Content | DELETE success (nothing to return) |
| 400 | Bad Request | Invalid input from client |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Resource not in right state ("document not ready") |
| 413 | Too Large | File exceeds size limit |
| 422 | Unprocessable | Pydantic validation failed (FastAPI auto-returns this) |
| 500 | Server Error | Bug in your code |

---

## Interview Q&As (see 100_questions.md Q66–Q80)

---

## What to Fix / Note

- Source file names use document UUID as prefix (from temp file save) — need to preserve original filename in metadata. Fixed in Day 4.  
- BM25 index doesn't persist across server restarts — rebuilt from ChromaDB on first query. Acceptable for now.
- No auth yet — any client can upload/query. Added in Day 5 (JWT).

---

## Tomorrow — Day 4

**Goal:** Fix source filenames + add streaming responses + improve the query experience

1. Fix metadata so sources show original filename, not temp UUID path
2. Streaming responses via SSE (Server-Sent Events) for real-time token output
3. Conversation history — multi-turn chat
4. Better error messages with error codes
5. API rate limiting setup (Redis)
