# Concept: FastAPI, Async Python, and Production API Design

---

## The Real-Life Analogy — Sync vs Async

**Synchronous (sync) — waiter analogy:**  
One waiter takes order from Table 1.  
Walks to kitchen. Stands there. Waits 10 minutes for food.  
Walks back. Delivers food.  
THEN goes to Table 2.  
Table 2 waited 10 minutes just because Table 1's kitchen was slow.

**Asynchronous (async) — good waiter analogy:**  
Waiter takes order from Table 1. Gives order to kitchen.  
While kitchen cooks, waiter goes to Table 2. Takes their order.  
Goes to Table 3. Takes their order.  
Kitchen signals "Table 1 food ready." Waiter delivers it.  
Kitchen signals "Table 2 food ready." Waiter delivers it.  
Same one waiter served 3 tables in the time the sync waiter served 1.

**In FastAPI:**  
Waiter = event loop (single thread)  
Tables = HTTP requests  
Kitchen = external work (DB query, LLM API call, file I/O)  
`await` = "hand this to the kitchen, go serve other tables"

---

## Sync vs Async — The Python Code

```python
# SYNCHRONOUS — blocks the thread
def get_data_sync():
    time.sleep(2)           # thread is frozen for 2 seconds
    return "data"           # nothing else can run during sleep

# ASYNCHRONOUS — suspends, lets other code run
async def get_data_async():
    await asyncio.sleep(2)  # suspends THIS function, event loop serves others
    return "data"           # resumes here after 2 seconds
```

**With FastAPI endpoints:**

```python
# Sync endpoint — FastAPI runs this in a thread pool automatically
# Use for: CPU-heavy work (embedding, inference)
@app.get("/sync")
def sync_endpoint():
    result = expensive_computation()  # runs in thread, doesn't block event loop
    return result

# Async endpoint — runs on the event loop directly
# Use for: I/O-bound work (DB queries, HTTP calls, file reads)
@app.get("/async")
async def async_endpoint():
    result = await db.execute(query)  # suspends, event loop serves other requests
    return result
```

**Key rule:** `async def` endpoints should ONLY do `await`-able operations.  
If you do CPU-heavy work inside `async def` without `run_in_executor`, you block the event loop.

---

## FastAPI's Dependency Injection System

### What is Dependency Injection?

Instead of a function creating its own dependencies, it declares what it needs  
and a framework provides them. The function is "injected" with the dependency.

```python
# WITHOUT dependency injection:
@app.get("/documents/")
async def list_documents():
    db = AsyncSessionLocal()     # endpoint creates its own session
    docs = await db.execute(...)
    await db.close()             # must remember to close
    return docs

# WITH dependency injection:
@app.get("/documents/")
async def list_documents(db: AsyncSession = Depends(get_db)):
    #                                       ^^^^^^^^^^^^^^^^
    #                     FastAPI calls get_db(), injects the result
    docs = await db.execute(...)
    return docs
    # FastAPI automatically closes the session after response is sent
```

### How Depends Works Internally

```python
async def get_db():           # This is a "dependency provider"
    async with session() as db:
        try:
            yield db          # ← yield hands control to the endpoint
            await db.commit()
        except:
            await db.rollback()
                              # ← resumes here after endpoint returns
```

```
FastAPI sees Depends(get_db) in the endpoint signature
    ↓
Calls get_db() (it's an async generator)
    ↓
get_db() runs until yield → hands db to the endpoint
    ↓
Endpoint runs with db
    ↓
get_db() resumes after yield → commit or rollback
    ↓
Session closed
```

### Chaining Dependencies

```python
async def get_current_user(token: str = Header(...)):
    return decode_jwt(token)   # returns User object

async def require_admin(user = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(403, "Admin only")
    return user

@app.delete("/documents/{id}")
async def delete_document(
    doc_id: str,
    db = Depends(get_db),
    admin = Depends(require_admin),   # chains get_current_user internally
):
    ...
```

FastAPI resolves the dependency graph automatically. Same pattern used in large-scale APIs.

---

## Pydantic — The Validation Engine

### Why Pydantic?

Every API endpoint receives data from untrusted clients. You must validate.  
Without Pydantic, you'd write hundreds of lines of if/else validation.

```python
# Manual validation (what you'd write without Pydantic):
def upload(data: dict):
    if "question" not in data:
        raise ValueError("question required")
    if not isinstance(data["question"], str):
        raise ValueError("question must be string")
    if len(data["question"]) < 3:
        raise ValueError("question too short")
    if len(data["question"]) > 2000:
        raise ValueError("question too long")
    # ... 50 more lines

# With Pydantic:
class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    # All validation above is now automatic. FastAPI returns 422 if violated.
```

### Pydantic v2 Key Patterns Used in This Project

```python
# 1. Required vs Optional fields
class Schema(BaseModel):
    required_field: str             # MUST be provided
    optional_field: str | None = None  # can be None, defaults to None
    field_with_default: int = 5     # optional, defaults to 5

# 2. Field metadata for validation
from pydantic import Field
class QueryRequest(BaseModel):
    question: str = Field(
        ...,                    # ... means "required"
        min_length=3,           # raises 422 if shorter
        max_length=2000,        # raises 422 if longer
        description="The question to ask the knowledge base",  # shows in /docs
    )
    top_k: int = Field(5, ge=1, le=20)   # ge=greater_equal, le=less_equal

# 3. Build from ORM model
class DocumentStatusResponse(BaseModel):
    document_id: str
    status: str

    model_config = {"from_attributes": True}
    # Enables: DocumentStatusResponse.model_validate(db_document)
    # Without this, you'd have to manually map each field

# 4. Nested models
class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceReference]  # list of another Pydantic model
    # FastAPI serializes nested models to nested JSON automatically
```

---

## HTTP Status Codes — Production Knowledge

Must know these cold for interviews. Every code has a specific meaning:

```
2xx — Success
  200 OK           → request succeeded, here's the response
  201 Created      → new resource created (use for POST that creates something)
  202 Accepted     → request accepted, processing started (async jobs)
  204 No Content   → success but nothing to return (use for DELETE)

4xx — Client Error (their fault)
  400 Bad Request       → malformed request (wrong format, missing fields)
  401 Unauthorized      → not logged in (no valid token)
  403 Forbidden         → logged in but no permission
  404 Not Found         → resource doesn't exist
  409 Conflict          → resource exists but in wrong state
  413 Payload Too Large → file/body exceeds size limit
  422 Unprocessable     → request format OK but data invalid (FastAPI auto)
  429 Too Many Requests → rate limited

5xx — Server Error (your fault)
  500 Internal Server Error → bug in your code
  502 Bad Gateway           → upstream service failed
  503 Service Unavailable   → server overloaded or down
```

**Interview Q:** "What status code do you return when a file is too large?"  
Wrong answer: "400" — 400 means bad format, not too large.  
Right answer: "413 Request Entity Too Large"

---

## Background Tasks vs Celery — When to Use Each

```
FastAPI BackgroundTasks (what we use today):
  ✅ Simple, no extra infrastructure
  ✅ Task starts after HTTP response is sent
  ✅ Great for: send email, log analytics, index small document
  ❌ If server crashes, task is lost (no persistence)
  ❌ No retry mechanism
  ❌ No progress tracking
  ❌ Runs in same process as the web server

Celery + Redis (Day 13 of this project):
  ✅ Tasks persist in Redis queue (survive crashes)
  ✅ Automatic retry on failure
  ✅ Can monitor with Flower dashboard
  ✅ Runs in separate worker processes (doesn't compete with web server)
  ✅ Can distribute work across multiple machines
  ❌ Requires Redis + Celery worker setup
  ❌ More complex

Rule: Use BackgroundTasks for low-stakes, fast tasks.
      Use Celery for critical, long-running, or retry-required tasks.
```

---

## The Service Layer Pattern

```
WRONG (logic in endpoint):
@router.post("/upload")
async def upload(file, db):
    # 50 lines of business logic here
    chunks = chunk_document(file)
    embeddings = embed(chunks)
    vector_store.insert(embeddings)
    db.add(Document(...))
    # ...

CORRECT (thin endpoint, fat service):
@router.post("/upload")
async def upload(file, db):
    result = await rag_service.index_file_background(file, db)
    return result

class RAGService:
    async def index_file_background(self, file, db):
        # business logic lives here
```

Why?
- Endpoint changes (REST → WebSocket → gRPC) → service unchanged
- Business logic is testable without HTTP
- Same service can be called by multiple endpoints or background jobs
- Single Responsibility Principle: endpoint = HTTP, service = logic
```

---

## Interview Questions (in 100_questions.md Q66–Q80)

---

## Resume Bullets

```
• Designed layered FastAPI backend: thin HTTP endpoints delegating to a service
  layer coordinating the RAG pipeline and SQLAlchemy async DB operations

• Implemented async document upload with FastAPI BackgroundTasks — 202 response
  in <20ms with background indexing, eliminating 40-second client wait

• Built Pydantic schemas for all API boundaries with field-level validation
  (min/max length, range constraints), eliminating manual input sanitization

• Applied run_in_executor pattern for CPU-bound embedding and inference operations,
  keeping the FastAPI event loop non-blocking under concurrent requests

• Implemented dependency injection via FastAPI Depends for DB session lifecycle —
  auto-commit on success, auto-rollback on exception, one session per request
```
