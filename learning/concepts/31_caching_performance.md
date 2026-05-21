# Redis Caching & Performance Optimization

## Why Cache in an AI Application?

A single RAG query costs:
- 1 embedding call (~50ms)
- 1 vector search (~100ms)
- 1 LLM generation (~1000-3000ms)
- Total: ~1-4 seconds, $0.001-0.01 (if on paid API)

If 10 users ask "What is the refund policy?" — you pay that cost 10 times.
With a cache: pay once, serve the rest from memory in ~1ms.

Cache ROI is highest when:
- Questions repeat (FAQ-style knowledge bases)
- LLM calls are expensive (GPT-4, paid APIs)
- Users have similar information needs

---

## 1. Redis — Why It's Used for Caching

Redis is an in-memory key-value store. Key properties:
- **In-memory**: reads are ~0.1ms (vs ~1ms disk, ~100ms network DB)
- **TTL support**: keys expire automatically — no manual cleanup
- **Atomic operations**: INCR is thread-safe — safe for counters under load
- **Data structures**: strings, lists, sets, sorted sets, hashes

Redis vs. in-process dict (Python memory):
| Feature         | Redis         | Python dict           |
|-----------------|---------------|-----------------------|
| Survives restart| Yes           | No                    |
| Multi-process   | Yes (shared)  | No (per-process)      |
| TTL/expiry      | Built in      | Manual                |
| Memory limit    | Configurable  | Grows until OOM       |
| Cluster         | Yes           | No                    |

Use Redis when multiple processes serve the same app (uvicorn --workers N).
Python dict only works when one process handles all requests.

---

## 2. Cache Key Design

A good cache key uniquely identifies the request:

```python
def _make_key(question: str, document_filter: Optional[dict] = None) -> str:
    content = f"{question.strip().lower()}:{json.dumps(document_filter or {}, sort_keys=True)}"
    digest = hashlib.sha256(content.encode()).hexdigest()
    return f"nexus:query:{digest}"
```

**Why SHA256?**
- Questions can be long — SHA256 gives a fixed 64-char key regardless of input length
- Collision probability is astronomically low (~2^-256)
- Hashing includes document_filter so "same question, different doc" → different key

**Why `.strip().lower()`?**
- "What is the policy?" and "what is the policy?" are the same question
- Normalizing before hashing maximizes cache hits

**Namespace prefix (`nexus:query:`):**
- Allows pattern-matching all query keys: `SCAN nexus:query:*`
- Separates from rate limit keys (`nexus:ratelimit:*`) and counters

---

## 3. Cache Strategies

### Cache-aside (Lazy loading) — used in Nexus AI
```
1. Check cache for key
2. Cache HIT  → return cached value immediately
3. Cache MISS → compute result → write to cache → return result
```
Best for: read-heavy workloads, expensive computations.
Drawback: first request is always slow (cold start).

### Write-through
```
1. Compute result
2. Write to DB and cache simultaneously
3. Return result
```
Best for: data that must always be fresh in both DB and cache.
Drawback: every write hits both systems (slower writes).

### Write-behind (Write-back)
```
1. Write to cache immediately
2. Async: flush to DB in batches
```
Best for: high write throughput where some data loss is acceptable.
Drawback: if cache crashes before flushing, data is lost.

### Read-through
Cache sits between app and DB. App never reads DB directly.
Best for: simple apps where all reads benefit from caching.

---

## 4. TTL (Time To Live)

TTL is how long a cached value lives before Redis deletes it automatically.

```python
r.setex(key, ttl=3600, value=serialized_result)  # expires after 1 hour
```

**Choosing TTL:**
- Short TTL (60-300s): for frequently updated data (live prices, scores)
- Medium TTL (1-24h): for semi-static data (RAG answers, product info)
- Long TTL (days): for truly static data (historical facts)
- No TTL: for session data managed by application logic

**Nexus AI uses 3600s (1h)** for query results. Rationale:
- Documents rarely change within an hour
- LLM answers are expensive — getting 1h of reuse is a good trade-off
- Manual flush endpoint available if content changes immediately

---

## 5. Cache Invalidation — The Hard Problem

"There are only two hard things in computer science: cache invalidation and naming things."

**The problem:** when the underlying data changes, cached results may be stale.

In Nexus AI: when a document is deleted, cached answers about that document are wrong.

**Approach used:** flush the entire query cache namespace:
```python
def invalidate_document_cache(document_id: str) -> None:
    keys = list(r.scan_iter("nexus:query:*"))
    if keys:
        r.delete(*keys)
```

**Why not invalidate per document?**
Cache keys are SHA256 hashes of questions — we can't tell which keys referenced
the deleted document. Including `document_id` in the key would fix this, but only
for queries that filtered by document. Cross-document queries (no document_id filter)
still can't be invalidated selectively.

**Trade-off accepted:** delete all query cache on any document change.
Cache rebuilds within 1 hour of normal usage.

---

## 6. KEYS vs SCAN — Production Safety

`KEYS pattern` in Redis: scans all keys in one blocking operation.
- O(N) where N is total key count
- **Blocks all other Redis operations** while running
- Safe for development, dangerous in production

`SCAN pattern` in Redis: iterates in small batches, non-blocking.
- Same result, spread across many round-trips
- Other clients can use Redis between scans
- Always use SCAN in production

```python
# BAD — blocks Redis on large keysets
keys = r.keys("nexus:query:*")

# GOOD — iterates incrementally
keys = list(r.scan_iter("nexus:query:*"))
```

---

## 7. Cache Hit/Miss Tracking

To know if the cache is working, track hits and misses with Redis counters:

```python
# On cache hit
r.incr("nexus:cache:hits")

# On cache miss
r.incr("nexus:cache:misses")
```

`INCR` is atomic in Redis — safe under concurrent requests. No race conditions.

Hit rate = hits / (hits + misses) × 100%

Good hit rates by use case:
- FAQ knowledge base: 70-90% (users repeat the same questions)
- Research tool: 20-40% (users explore unique questions)
- General chat: 10-30% (conversational, mostly unique)

---

## 8. Percentile Latency — P50, P95, P99

**Average (mean)** latency hides outliers:
- 9 requests: 100ms each
- 1 request: 10,000ms (timeout/retry)
- Average: 1090ms — misleading, 90% of users are fast

**Percentiles** show the true distribution:
- P50 (median): 50% of requests are faster than this
- P95: 95% of requests are faster than this (the "worst normal case")
- P99: 99% are faster (extreme tail, catches most outliers)

P95 is the SLA metric of choice at most companies:
"99% of users see responses in under 2s" — this is a P99 latency SLA.

In Nexus AI, P95 is computed in Python:
```python
durations = sorted(all_duration_values)
p95 = durations[int(0.95 * len(durations))]
```

For large-scale systems: use dedicated tools (Prometheus histograms, Datadog APM)
that compute percentiles without loading all values into memory.

---

## 9. Graceful Degradation

The cache is not critical. The app must work without Redis:

```python
def get_cached_query(...) -> Optional[dict]:
    try:
        r = _get_redis()
        ...
    except Exception as e:
        logger.warning(f"Cache get failed (Redis down?): {e}")
    return None  # on any error, return None → caller computes fresh result
```

Pattern: wrap all Redis calls in try/except. Log the failure. Fall back to the slow path.
Users experience slower responses when Redis is down, not errors.

Same pattern in rate_limit.py — if Redis is down, allow all requests through.
This is "fail open" — prioritize availability over rate limiting.

---

## Interview Questions

**Q: What is cache-aside and when do you use it?**
Cache-aside: check cache first, on miss compute and store. It's the most common pattern
because it's simple and only caches what's actually read. Use it for read-heavy workloads
where the computation is expensive (LLM calls, complex DB queries). The first request
for each key is always slow — this is the cold-start trade-off.

**Q: Why use SHA256 for cache keys instead of the raw question string?**
Two reasons: key length and normalization. Redis keys can be long strings but shorter is
faster. SHA256 gives a fixed 64-char key regardless of question length. Additionally,
applying `.strip().lower()` before hashing means "What is the policy?" and
"  what is the policy?  " map to the same hash, maximizing cache hits.

**Q: What is the difference between KEYS and SCAN in Redis?**
`KEYS pattern` scans all keys in one operation — it blocks Redis until complete (O(N)).
With millions of keys, this can freeze Redis for seconds. `SCAN` iterates in small batches,
allowing other clients to run between iterations. Always use SCAN in production.

**Q: What is a TTL and how do you choose the right value?**
TTL (Time To Live) is how long a Redis key lives before automatic deletion. Choose based
on data volatility: short TTL (60-300s) for frequently updated data, medium TTL (1-24h)
for semi-static content like RAG answers, long TTL or no TTL for truly static data.
Also consider the cost of a cache miss — for LLM calls (slow, expensive), a longer TTL
is worth the risk of slightly stale answers.

**Q: What is the difference between P50, P95, and P99 latency?**
These are percentiles of the latency distribution. P95 = 95% of requests complete faster
than this value. The average hides outliers — 9 fast requests and 1 very slow one can
make the average look bad even though 90% of users are happy. P95 is the standard SLA
metric because it represents the "worst normal case" while ignoring extreme tail events.
P99 is used for stricter SLAs where you want to guarantee experience for 99% of users.
