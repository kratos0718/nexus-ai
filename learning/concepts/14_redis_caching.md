# Redis Caching for AI Applications

## What is Redis?

Redis (Remote Dictionary Server) is an **in-memory key-value store**. "In-memory" means data lives in RAM, not disk — so reads are microseconds, not milliseconds.

```
Without cache:  User → FastAPI → Embedder → Vector DB → LLM → User   (~3-10 seconds)
With cache hit: User → FastAPI → Redis → User                          (~2 milliseconds)
```

For RAG apps, caching is high-value because:
- LLM inference is expensive (costs money or time)
- Many users ask the same questions ("What is your refund policy?")
- Embeddings + vector search is also slow (~200ms locally)

---

## How Redis Works

Redis stores **key → value** pairs where:
- Keys are strings (max 512MB, but keep them short)
- Values can be strings, lists, hashes, sets, sorted sets, etc.
- Each key can have a **TTL** (time-to-live) — auto-expires after N seconds

```python
import redis
r = redis.from_url("redis://localhost:6379")

r.set("greeting", "hello")          # store
r.get("greeting")                   # → b"hello"
r.setex("session", 3600, "token")   # store with 60-min TTL
r.get("nonexistent")                # → None (never raises KeyError)
r.delete("greeting")                # remove
r.keys("nexus:*")                   # list keys matching pattern
```

---

## Cache Key Design

A cache key must **uniquely identify** the exact same request. For RAG queries:

```python
def _make_key(question: str, document_filter: dict | None) -> str:
    # Normalize: lowercase + strip whitespace so "What is AI?" == "what is ai?"
    content = f"{question.strip().lower()}:{json.dumps(document_filter or {}, sort_keys=True)}"
    # Hash: SHA256 gives fixed-length key regardless of question length
    digest = hashlib.sha256(content.encode()).hexdigest()
    return f"nexus:query:{digest}"
```

Key design rules:
1. **Namespace with prefix** (`nexus:query:`) — lets you `r.keys("nexus:query:*")` to find all query caches
2. **Normalize input** — "What is AI?" and "what is ai?" should hit the same cache
3. **Include all dimensions that change the answer** — if document_id changes the answer, include it in the key
4. **Hash long inputs** — SHA256 keeps keys short and fixed-length

---

## Cache Invalidation

The hardest problem in caching: **when to clear stale data**.

Nexus uses a simple strategy: when a document is deleted, flush ALL query caches.

```python
def invalidate_document_cache(document_id: str) -> None:
    keys = r.keys("nexus:query:*")   # find all query cache keys
    if keys:
        r.delete(*keys)              # delete all at once (atomic)
```

Why flush all instead of just queries for that document?
- We can't reverse a SHA256 hash to know which queries touched a document
- The cache rebuilds itself on next request — no data is permanently lost
- Document deletions are rare, so the cost is acceptable

Other strategies (not used here but good to know):
| Strategy | How | When to use |
|---|---|---|
| TTL expiry | Set short TTL, let it expire naturally | When slight staleness is OK |
| Tag-based | Store which document IDs each cache key depends on | Complex but precise |
| Write-through | Update cache whenever DB updates | High read/write both |
| Full flush | Clear everything on any write | Simple, aggressive |

---

## Redis Databases (db numbers)

Redis supports 16 logical databases on one server (db 0–15). Nexus uses:
- `db 0` — query cache (`REDIS_URL=redis://localhost:6379/0`)
- `db 1` — Celery broker (task messages)
- `db 2` — Celery result backend (task results)

Separate DBs prevent cache keys from colliding with Celery internal keys. They're not true isolation (same memory, same process) but useful for organization.

---

## Graceful Degradation Pattern

Never let Redis failure break your main application:

```python
def get_cached_query(question: str) -> dict | None:
    try:
        r = _get_redis()
        raw = r.get(_make_key(question))
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.warning(f"Cache get failed (Redis down?): {e}")
        return None   # ← cache miss, app continues normally
```

This pattern means:
- Redis up → fast cached responses
- Redis down → full pipeline runs, slightly slower but fully functional
- No `try/except` in the caller — it just sees a `None` cache miss

---

## TTL Strategy

```python
# Current: 1 hour TTL
r.setex(key, 3600, json.dumps(result))
```

Choose TTL based on how fast your data changes:
- **Query cache** (answers from docs): 1 hour — docs don't change mid-session
- **Session tokens**: 24 hours — matches login duration
- **Rate limit counters**: 60 seconds — sliding window
- **Static config**: 24 hours — rarely changes

Short TTL = more cache misses but fresher data
Long TTL = more hits but risk of stale answers

---

## Redis vs Other Caches

| | Redis | Memcached | In-process dict |
|---|---|---|---|
| Persistence | Optional (RDB/AOF) | None | None |
| Data structures | Strings, lists, hashes, sets, sorted sets | Strings only | Python objects |
| Clustering | Yes | Yes | No (single process) |
| Pub/Sub | Yes | No | No |
| Use case | Cache, queues, sessions, leaderboards | Pure cache | Single-instance cache |

Redis is preferred for AI apps because it also serves as a **message broker** (Celery uses it) — one service, two roles.

---

## Interview Questions

**Q: What's the difference between Redis and a database?**
Redis stores data in RAM (fast, limited size, optional persistence). A database stores on disk (slower, unlimited size, durable by default). Redis is typically used as a cache layer in front of a database, not as a replacement.

**Q: What happens if Redis goes down in your system?**
Nexus degrades gracefully — all cache operations are wrapped in try/except, so a Redis failure causes cache misses, not application errors. The full pipeline runs as fallback.

**Q: How do you prevent cache stampede?**
Cache stampede: Redis key expires, 100 requests all miss cache simultaneously, all hit the LLM at once. Solutions: probabilistic early expiry (refresh before TTL expires), locking (only one request recomputes, others wait), or background refresh (pre-warm before expiry).

**Q: Why hash the cache key instead of using the question directly?**
Questions can be arbitrarily long (thousands of characters). SHA256 produces a fixed 64-character hex string. Also, if the question contained special characters, it could break key parsing.
