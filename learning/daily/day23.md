# Day 23 — Redis Caching & Performance Optimization

## What I Built

**`app/core/cache.py` — 3 improvements:**
1. **Hit/miss counters** — `r.incr("nexus:cache:hits")` on hit, `r.incr("nexus:cache:misses")` on miss
2. **KEYS → SCAN** — `invalidate_document_cache` now uses `r.scan_iter()` instead of `r.keys()` (non-blocking)
3. **`get_cache_stats()`** — returns `cached_queries`, `hits`, `misses`, `hit_rate_pct`, `redis_memory_mb`, `redis_connected`
4. **`flush_query_cache()`** — deletes all `nexus:query:*` keys using SCAN

**`app/api/v1/endpoints/cache_admin.py`** (new):
- `GET /cache/stats` — returns cache performance metrics
- `DELETE /cache/flush` — manual cache flush, returns deleted count

**`app/api/v1/router.py`** — registered cache router at `/cache`

**`app/services/trace_service.py`** — added P95 latency to `get_stats()`:
- Fetches all durations in Python, sorts, takes `durations[int(0.95 * len)]`
- `p95_duration_ms` added to response

**Observability frontend** — 2 additions:
- Cache stats panel: connected status, cached query count, hit rate with progress bar, Redis memory, Flush button
- P95 bar added to latency range chart (between Avg and Max)

---

## Key Decisions

**Why flush the entire query cache when a document is deleted?**
Cache keys are SHA256(question + filter). Without a reverse index of which questions
referenced which document, you can't know which keys to invalidate selectively. Full
flush is simple and correct — the cache rebuilds on next queries.

**Why SCAN over KEYS?**
KEYS blocks Redis until all keys are scanned. With 10,000+ keys, this freezes Redis
for hundreds of milliseconds — during which all other clients are blocked. SCAN iterates
in ~100-key batches, non-blocking between iterations.

**Why P95 instead of (or in addition to) average?**
Average latency hides outliers. If 95% of queries complete in 800ms but 5% take 8 seconds
(timeouts, model cold starts), the average might be 1100ms — misleading. P95 shows the
"worst normal case." P99 catches extreme tails but is more sensitive to small sample sizes.

**Why compute P95 in Python instead of SQL?**
PostgreSQL has `percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)` but SQLite
(used in tests) doesn't. Fetching all durations and computing in Python is ~20x slower
for millions of rows but fine for thousands. Consistent behavior across DB backends.

---

## How to Test

```bash
# Start Redis
docker compose up redis -d

# Run a few queries in the chat UI, then check stats
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/cache/stats

# Flush the cache
curl -X DELETE -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/cache/flush

# Observability dashboard shows the cache panel automatically
# Go to: http://localhost:3000/observability
```

---

## Resume Bullets

- Instrumented Redis query cache with hit/miss counters; exposed metrics via cache stats API and observability dashboard
- Fixed production safety issue: replaced blocking KEYS with SCAN for all cache invalidation operations
- Added P95 latency calculation to trace stats endpoint; displayed alongside min/avg/max in UI latency chart
- Built cache management UI: connected status indicator, hit rate progress bar, manual flush button

---

## Interview Q&As

**Q287: What is cache-aside and when do you use it?**
A: Cache-aside (lazy loading): check cache first, on miss compute and store. It's the most common pattern because it only caches data that's actually read. Use for read-heavy workloads where computation is expensive (LLM calls, complex DB queries). The first request for each key is always slow — this cold-start trade-off is acceptable when subsequent requests are fast.

**Q288: Why use SHA256 for cache keys instead of the raw question string?**
A: Two reasons: length and normalization. Redis keys can be arbitrary strings but shorter is faster. SHA256 gives a fixed 64-char key regardless of question length. Normalizing with `.strip().lower()` before hashing means "What is the policy?" and "what is the policy?" map to the same hash — maximizing hit rate without any extra logic on the lookup path.

**Q289: What is the difference between KEYS and SCAN in Redis and why does it matter?**
A: `KEYS pattern` scans all keys in one atomic operation — O(N) and blocks Redis until complete. With millions of keys, this can freeze Redis for seconds, blocking all other clients. `SCAN` iterates in small batches, allowing other clients to proceed between rounds. Functionally identical results, but SCAN never blocks more than ~1ms per round. Always use SCAN in production.

**Q290: What is P95 latency and why do companies care about it more than average?**
A: P95 means 95% of requests complete faster than that value. Average hides outliers — 9 requests at 100ms and 1 at 10,000ms gives a 1,090ms average even though 90% of users are fast. P95 shows the "worst normal case." SLAs like "99% of users see responses in under 2 seconds" are P99 latency commitments. Monitoring P95/P99 catches tail latency problems that averages mask completely.

**Q291: How do you handle cache invalidation when you can't map cached keys back to their source data?**
A: When keys are hashed (SHA256 of the question), there's no reverse index to find which cached answers referenced a specific document. Options: (1) flush the entire namespace on any data change — simple, correct, rebuilds on next use; (2) include a versioned prefix in the key (increment version on any change, old keys become unreachable and expire naturally); (3) maintain a separate index mapping document_id to cache keys — complex but enables targeted invalidation. Nexus AI uses option 1 because flush is rare (only on document delete) and rebuild is fast.
