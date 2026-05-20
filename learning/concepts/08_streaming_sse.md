# Concept 8 — Streaming Responses and Server-Sent Events

## Why Stream LLM Responses?

LLMs are autoregressive — they generate one token at a time, left to right.
The full answer for a complex question can take 5-15 seconds.

**Without streaming:**
```
[0s] User sends query
[8s] Server sends full 300-word answer
     → User stares at loading spinner for 8 seconds
```

**With streaming:**
```
[0s]    User sends query
[0.3s]  First token arrives: "The"
[0.4s]  " vacation"
[0.5s]  " policy"
...     (words flow in real time)
[8s]    Last token arrives — answer complete
        → User starts reading at 0.3s
```

Same total time. Completely different user experience.

---

## Three Streaming Protocols Compared

| Protocol | Direction | Persistent Connection | Complexity |
|----------|-----------|----------------------|------------|
| SSE | Server → Client only | Yes | Low |
| WebSocket | Bidirectional | Yes | Medium |
| HTTP Chunked Transfer | Server → Client only | No (one request) | Low |

**SSE wins for LLM streaming because:**
- LLM responses are one-directional (server sends tokens to client)
- SSE is a simple HTTP protocol (works through proxies and firewalls)
- Browser has native EventSource API
- Reconnects automatically on failure
- No special server setup (unlike WebSocket upgrade)

---

## SSE Wire Format

SSE is just an HTTP response that never closes, with a specific text format:

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

data: Hello\n\n
data:  world\n\n
data: !\n\n
data: [SOURCES][{"source": "policy.pdf", "page": 3, "score": 0.94}]\n\n
data: [DONE]\n\n
```

Rules:
- Each event: `data: <content>\n\n` (double newline = event separator)
- Lines starting with `:` are comments (keepalive pings)
- `event: <name>\n` before `data:` specifies event type (optional)
- `id: <id>\n` sets last event ID for reconnection (optional)

We use a custom protocol on top:
- `data: <token>` — a text fragment to append
- `data: [SOURCES]{...}` — JSON array of citations
- `data: [DONE]` — end of stream signal

---

## Groq's Streaming API

```python
# The stream=True flag makes the API return an iterator instead of waiting
stream = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=messages,
    stream=True,         # ← key difference
)

# Iterator yields chunks as they arrive from the API
for chunk in stream:
    token = chunk.choices[0].delta.content
    # delta.content is None on the last chunk
    if token:
        yield token
```

Without `stream=True`: API waits for full response → returns one object.
With `stream=True`: API returns iterator → yields partial `delta.content` fragments as they're generated.

---

## The Async Bridge Problem

FastAPI uses asyncio (single-threaded event loop).
Groq streaming is a synchronous blocking iterator.

```
Event Loop Thread
│
├─ Request 1: awaiting result...
├─ Request 2: awaiting result...
└─ ???: running Groq stream iterator  ← BLOCKS everything above!
```

If you run the blocking iterator in the event loop thread, no other requests can be served while it's running. This kills concurrency.

### Solution: Queue Bridge

```python
import queue
import threading
import asyncio

token_queue: queue.Queue = queue.Queue()

def producer():
    """Runs in a dedicated background thread — can block freely."""
    try:
        for token in pipeline.generator.generate_stream(...):
            token_queue.put(token)   # put() is thread-safe
    finally:
        token_queue.put(None)        # sentinel: tells consumer we're done

# Start producer in background thread (non-blocking)
thread = threading.Thread(target=producer, daemon=True)
thread.start()

# Consumer: async generator in event loop thread
async def consumer():
    while True:
        try:
            token = token_queue.get_nowait()  # non-blocking — raises Empty if nothing
        except queue.Empty:
            await asyncio.sleep(0.01)         # yields control, event loop serves others
            continue

        if token is None:   # sentinel received
            break
        yield f"data: {token}\n\n"
```

**Threading.Queue is thread-safe:** Python's `queue.Queue` uses internal locking. The producer thread can `put()` and the consumer coroutine can `get_nowait()` without race conditions.

**Why 10ms sleep?** Trade-off between latency (shorter sleep = faster) and CPU waste (longer sleep = less polling). At 10ms, the consumer checks 100 times/second — fine for token streaming.

---

## FastAPI Streaming Response

```python
from fastapi.responses import StreamingResponse

@router.post("/stream")
async def query_stream(request: QueryRequest):
    return StreamingResponse(
        content=my_async_generator(),   # any async generator
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # critical for nginx!
        },
    )
```

**`X-Accel-Buffering: no`** tells nginx (if deployed behind it) not to buffer the response. Without this, nginx collects the full response before forwarding to the client — completely defeating streaming.

**`Cache-Control: no-cache`** prevents any intermediate cache from storing the stream.

**How StreamingResponse works internally:**
```python
# Simplified FastAPI internals
async def send_response(generator):
    async for chunk in generator:
        await connection.send(chunk.encode())
        # sends each chunk immediately without waiting for generator to finish
```

---

## Client-Side: Reading SSE

**Browser (native EventSource):**
```javascript
const source = new EventSource('/api/v1/chat/stream');

source.onmessage = (event) => {
    const data = event.data;
    if (data === '[DONE]') {
        source.close();
        return;
    }
    if (data.startsWith('[SOURCES]')) {
        const sources = JSON.parse(data.slice(9));
        displaySources(sources);
        return;
    }
    appendToken(data);  // append to displayed answer
};

source.onerror = () => {
    // EventSource auto-reconnects on error — close if you don't want that
    source.close();
};
```

**Limitation:** EventSource doesn't support POST requests or custom headers.
For auth, use `fetch()` with manual stream reading:

```javascript
const response = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({ question: "..." }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value);
    // parse SSE events from text...
}
```

---

## Conversation History + Streaming

Streaming creates a challenge: you need to save the complete answer to the DB, but it arrives token-by-token.

**Approach 1 (simple, our current approach):**
Only save messages on the non-streaming `/query` endpoint.
Streaming endpoint focuses on real-time delivery without DB writes mid-stream.

**Approach 2 (production):**
Accumulate tokens, then save after `[DONE]`:
```python
full_answer = []
async for token in stream_generator():
    full_answer.append(token)
    yield f"data: {token}\n\n"
await save_to_db("".join(full_answer))
```

**Approach 3 (complex, robust):**
Use a callback/task: stream to client, post a background task to save the complete answer after streaming completes.

---

## Performance Notes

| Aspect | Non-streaming | Streaming |
|--------|--------------|-----------|
| Time to first byte | 8s (full generation) | 0.3s (first token) |
| Total time | 8s | 8s |
| Server memory | Low (returns once) | Low (yield, don't buffer) |
| Connection duration | 1s | 8s |
| Max concurrent streams | High | Lower (connections held open) |

Streaming trades connection duration for perceived latency. Most LLM services use streaming as default.

---

## Rate Limiting Streaming Endpoints

Streaming endpoints are expensive (long-held connections, LLM compute).
Apply stricter limits:

```python
@router.post("/stream")
@limiter.limit("10/minute")   # stricter than /query's 20/minute
async def query_stream(request: Request, ...):
    ...
```

Also consider: maximum stream duration timeouts, connection limits per user, and async generator cleanup on client disconnect.
