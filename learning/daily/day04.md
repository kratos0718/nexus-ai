# Day 4 — JWT Authentication + Streaming Responses + Conversation History

## What We Built Today

| Component | File | Purpose |
|-----------|------|---------|
| JWT security | `app/core/security.py` | Password hashing, token create/verify |
| Auth dependency | `app/core/dependencies.py` | Protect any route with one line |
| User model | `app/models/user.py` | ORM for registered users |
| Conversation models | `app/models/conversation.py` | Multi-turn chat storage |
| Auth endpoints | `app/api/v1/endpoints/auth.py` | Register, login, refresh, /me |
| Conversation endpoints | `app/api/v1/endpoints/conversations.py` | CRUD for conversations |
| Chat endpoints (updated) | `app/api/v1/endpoints/chat.py` | Query + streaming, both auth-protected |
| Rate limiting | `app/main.py` | slowapi: IP-based rate limiting |
| Generator (fixed) | `app/rag/generation/generator.py` | Both `generate()` and `generate_stream()` accept history |

---

## JWT Authentication — How It Actually Works

### The Problem JWT Solves

HTTP is stateless — every request is independent. The server has no memory between calls.

**Session approach (old school):**
```
Client: "Login me"
Server: Creates session ID "abc123" → stores in memory/Redis
Server: Sends cookie "session=abc123"
Client: Each request sends cookie
Server: Looks up "abc123" in its session store
```
Problem: server must store every active session. Doesn't scale horizontally (server 2 doesn't have server 1's sessions).

**JWT approach (stateless):**
```
Client: "Login me"
Server: Creates signed token containing {user_id, email, exp}
Server: Sends token back — stores NOTHING
Client: Each request sends "Authorization: Bearer <token>"
Server: Verifies signature → trusts the data inside — no DB lookup needed
```

### Token Structure

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9   ← Header (base64)
.
eyJzdWIiOiI0MiIsImVtYWlsIjoiYWJoaUBleC5jb20iLCJ0eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzAwMDAwMDAwfQ==  ← Payload (base64)
.
SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c  ← Signature (HMAC-SHA256 of header.payload using secret key)
```

The signature is what makes it tamper-proof. If anyone changes the payload, the signature breaks.

### Two-Token Strategy

```
Access Token:  expires in 30 minutes — used for every API call
Refresh Token: expires in 7 days — used ONLY to get new access tokens
```

Why two tokens?
- Short-lived access token limits damage if stolen (attacker can only use it 30 min)
- Long-lived refresh token avoids re-login every 30 min
- Refresh token can be revoked (blacklist in Redis) without killing access tokens in flight

### Our Implementation

```python
# app/core/security.py

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "nexus-dev-secret-change-in-production-min-32-chars")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

def create_access_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),    # "subject" — standard JWT claim
        "email": email,
        "type": "access",       # custom claim to distinguish token types
        "exp": datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(UTC),  # "issued at" — for debugging
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        return None  # expired, tampered, or invalid → return None, not exception
```

**Why "sub" as string?** JWT spec says "sub" (subject) is a string. Even though our user ID is an int in the DB, we store it as string in JWT, then `int(payload["sub"])` when reading.

### The FastAPI Dependency Pattern

```python
# app/core/dependencies.py

bearer_scheme = HTTPBearer()  # Reads "Authorization: Bearer <token>" header automatically

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = decode_token(token)

    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    return user
```

**Usage in any endpoint:**
```python
@router.get("/protected")
async def protected_route(current_user: User = Depends(get_current_user)):
    return {"user": current_user.email}  # guaranteed to have a valid user here
```

Adding `Depends(get_current_user)` to ANY route signature makes it auth-protected.
FastAPI's dependency injection wires everything automatically.

---

## Password Hashing — bcrypt

Never store plain text passwords. bcrypt is the standard:

```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)
    # Returns: "$2b$12$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy"
    # The "$12$" means 2^12 = 4096 rounds → slow by design (0.3 seconds per hash)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
    # bcrypt extracts the salt from the hash string automatically
```

**Why bcrypt is slow by design:** If an attacker steals your DB and cracks passwords offline, bcrypt makes it computationally expensive — 4096 rounds means 4096× harder than plain SHA-256.

**The salt:** bcrypt auto-generates a random salt per password. Same password → different hashes. This prevents rainbow table attacks.

---

## Streaming with Server-Sent Events (SSE)

### Why Streaming?

LLMs generate tokens sequentially. Without streaming:
```
User sends query → waits 5-15 seconds → entire answer appears at once
```
With streaming:
```
User sends query → first tokens appear in ~200ms → words flow in real-time
```
Same total time, but perceived latency drops dramatically. Users see the AI "thinking."

### SSE Protocol

SSE is a one-way HTTP stream from server → client. Simpler than WebSockets (no bidirectional needed).

```
HTTP Response headers:
  Content-Type: text/event-stream
  Cache-Control: no-cache
  X-Accel-Buffering: no    ← tell nginx NOT to buffer (send immediately)

Response body (never closes until done):
  data: Hello\n\n
  data:  world\n\n
  data: !\n\n
  data: [SOURCES][{"source": "doc.pdf", ...}]\n\n
  data: [DONE]\n\n
```

Each `data: ...\n\n` is one event. The double newline `\n\n` is the SSE event separator.

### The Async Bridge Problem

Groq streams tokens synchronously (blocking iterator). FastAPI is async.
You can't run a blocking iterator inside an async generator — it blocks the event loop.

```
WRONG:
async def stream():
    for token in groq_stream:    # ← blocks event loop! no other requests served
        yield f"data: {token}\n\n"
```

**Solution: Queue Bridge Pattern**

```python
# app/services/rag_service.py — query_stream()

import queue
import threading

token_queue: queue.Queue = queue.Queue()

def producer():
    """Runs in a background thread — blocking is fine here."""
    try:
        for token in pipeline.generator.generate_stream(...):
            token_queue.put(token)      # thread-safe operation
    finally:
        token_queue.put(None)           # sentinel: signals completion

thread = threading.Thread(target=producer, daemon=True)
thread.start()

# Async consumer — never blocks the event loop
while True:
    try:
        token = token_queue.get_nowait()    # non-blocking
    except queue.Empty:
        await asyncio.sleep(0.01)           # yields control to event loop
        continue

    if token is None:
        break
    yield f"data: {token}\n\n"
```

**Why `daemon=True`?** Daemon threads are killed automatically when the main process exits. Without this, the thread could keep running after the HTTP connection closes.

**Why `get_nowait()` not `get()`?** `queue.get()` blocks until an item is available — that would block the async event loop. `get_nowait()` raises `queue.Empty` immediately if empty, letting us `await asyncio.sleep(0.01)` and yield control back.

### FastAPI StreamingResponse

```python
@router.post("/stream")
async def query_stream(request: QueryRequest):
    return StreamingResponse(
        rag_service.query_stream(question=request.question, ...),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

`StreamingResponse` wraps any async generator and streams it as HTTP chunked transfer encoding.

---

## Conversation History — Multi-Turn Chat

### The Stateless Problem

Each API call to Groq is independent. The model has no memory between calls.

```
User: "What is the vacation policy?"
AI:   "Employees get 15 days per year."
User: "How do I request it?"         ← "it" refers to vacation — but model doesn't know!
AI:   "I don't know what you're referring to."  ← fails without history
```

### The Solution: Inject History as Messages

```python
# How Groq/OpenAI multi-turn works
messages = [
    {"role": "system",    "content": "You are a helpful assistant..."},
    {"role": "user",      "content": "What is the vacation policy?"},      # turn 1
    {"role": "assistant", "content": "Employees get 15 days per year."},   # turn 1
    {"role": "user",      "content": "How do I request it?"},              # turn 2 — "it" now has context
]
```

Every new message, you replay the entire conversation history. The model re-reads everything and responds with full context.

**Cost:** More tokens per request as conversation grows. Enterprise solutions use summarization or sliding windows to keep history bounded.

### Our Storage Schema

```
Conversation
  conversation_id: UUID (public)
  user_id: FK → users
  title: "What is the vacation policy?"
  document_id: optional — scopes all queries to one doc

  messages: [
    Message(role="user",      content="What is the vacation..."),
    Message(role="assistant", content="Employees get 15 days...", prompt_tokens=450, completion_tokens=30),
    Message(role="user",      content="How do I request it?"),
    Message(role="assistant", content="Submit a request via...", prompt_tokens=500, completion_tokens=40),
  ]
```

### Flow: Query With History

```
1. Client sends POST /chat/query {question: "How do I request it?", conversation_id: "abc-123"}
2. Endpoint loads conversation from DB → gets all past messages
3. rag_service._build_history(messages) → converts to list[dict] for Groq
4. pipeline.query(question, history=history) → injects history into LLM messages
5. LLM sees full context → gives coherent answer
6. Endpoint saves {user: question} + {assistant: answer} to DB
7. Next request repeats with longer history
```

---

## Rate Limiting with slowapi

Rate limiting prevents:
- API abuse (someone running 10,000 queries/minute)
- Accidental infinite loops in client code
- DoS from a single IP overwhelming your server

```python
# app/main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)  # rate limit per IP address
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

Usage on individual routes:
```python
@router.post("/query")
@limiter.limit("20/minute")    # 20 requests per minute per IP
async def query(request: Request, ...):
    ...
```

When exceeded, slowapi returns:
```json
HTTP 429 Too Many Requests
{"error": "Rate limit exceeded: 20 per 1 minute"}
```

---

## What `run_in_executor` Actually Does

This is the pattern used throughout the service layer:

```python
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(
    None,                                    # None = use default ThreadPoolExecutor
    lambda: pipeline.query(question, ...)    # sync function to run in thread
)
```

**The thread pool:** Python maintains a pool of worker threads (default: min(32, CPU count + 4)). `run_in_executor` submits the function to this pool and returns a Future that the event loop can await.

**Why not just `asyncio.to_thread()`?** Same thing — `asyncio.to_thread()` is the modern (Python 3.9+) convenience wrapper around `run_in_executor(None, ...)`. Both work identically.

**The GIL concern:** Python's Global Interpreter Lock means only one thread runs Python bytecode at a time. But ML operations (numpy, PyTorch, sentence-transformers) release the GIL during computation. The thread pool is still faster than blocking the main thread.

---

## Today's Architecture Map

```
HTTP Request
    ↓
FastAPI Router
    ↓
Depends(get_current_user)  ← JWT verified, User loaded
    ↓
Depends(limiter.limit())   ← rate check passes
    ↓
Endpoint Handler
    ↓
rag_service.query(history=history)
    ↓
[thread pool] pipeline.query()
    ↓
_retrieve() → embed → dense+sparse → RRF → rerank
    ↓
generator.generate(history=history)
    ↓
Groq API
    ↓
GenerationResult → saved to DB as Message
    ↓
QueryResponse → JSON to client
```

---

## Files Changed Today

```
backend/app/core/security.py              ← NEW: JWT + bcrypt
backend/app/core/dependencies.py          ← NEW: get_current_user dependency
backend/app/models/user.py                ← NEW: User ORM
backend/app/models/conversation.py        ← NEW: Conversation + Message ORM
backend/app/schemas/auth.py               ← NEW: Register/Login/Token schemas
backend/app/schemas/conversation.py       ← NEW: Conversation schemas
backend/app/api/v1/endpoints/auth.py      ← NEW: /auth/* routes
backend/app/api/v1/endpoints/conversations.py ← NEW: /conversations/* routes
backend/app/api/v1/endpoints/chat.py      ← UPDATED: auth + conversation + streaming
backend/app/api/v1/router.py              ← UPDATED: added auth + conversations
backend/app/rag/generation/generator.py   ← UPDATED: history param in generate()
backend/app/services/rag_service.py       ← UPDATED: conversation methods + history
backend/app/main.py                       ← UPDATED: slowapi rate limiting
```
