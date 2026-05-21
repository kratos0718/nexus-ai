# API Rate Limiting

## Why Rate Limit?

Without rate limiting, one user (or a bad actor) can:
- Burn through your entire Groq free-tier quota in minutes
- DoS your server by sending thousands of requests
- Run up cloud costs (embedding calls, LLM tokens)

Rate limiting says: "You get N requests per time window. After that, wait."

---

## Fixed Window Counter (what Nexus uses)

```
Window: 1 hour  |  Limit: 100 requests

Hour 1 (9:00–10:00):  user makes 100 requests → OK
Request 101:           → 429 Too Many Requests
Hour 2 (10:00–11:00): counter resets → user can make 100 more
```

Implementation with Redis:
```python
window = int(time.time()) // 3600     # floor to current hour: 9:00, 10:00...
key = f"ratelimit:user:42:{window}"   # new key every hour = auto-reset

count = r.incr(key)        # atomic increment (safe under concurrency)
if count == 1:
    r.expire(key, 3660)    # set TTL only on first increment

if count > limit:
    raise RateLimitExceeded(...)
```

`INCR` is atomic — if two requests arrive simultaneously, one gets count=1 and the other gets count=2. No race condition, no double-counting.

**Weakness**: Burst at boundary. A user can make 100 requests at 9:59 and 100 more at 10:01 — 200 requests in 2 minutes. Fixed window allows this burst.

---

## Sliding Window Log (more accurate, more memory)

Stores the timestamp of every request. On each request:
1. Remove all entries older than the window
2. Count remaining entries
3. If count < limit, allow and add current timestamp

```python
now = time.time()
key = f"ratelimit:user:42"
r.zremrangebyscore(key, 0, now - 3600)  # remove old entries
count = r.zcard(key)
if count >= limit:
    raise RateLimitExceeded(...)
r.zadd(key, {str(uuid.uuid4()): now})   # add current request
r.expire(key, 3600)
```

More accurate (no boundary burst) but stores one Redis entry per request — expensive for high-traffic APIs.

---

## Token Bucket (smoothest, most flexible)

Tokens refill continuously. Each request consumes one token.
- Allows short bursts (up to bucket capacity)
- Smooths out sustained high traffic

Used by AWS, Stripe, most large-scale APIs. More complex to implement.

---

## HTTP 429 Response

The standard response for rate limit exceeded:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 1847
Content-Type: application/json

{"detail": "Rate limit exceeded. Try again in 1847s."}
```

`Retry-After` header tells the client exactly when to retry. Good clients back off automatically when they see this.

---

## Two-Tier Limits (Nexus pattern)

```python
_USER_LIMIT = 100   # authenticated users: 100 req/hour
_IP_LIMIT   = 30    # anonymous/unknown:   30 req/hour

identifier = f"user:{user.id}"  # auth users → higher limit
identifier = f"ip:{client_ip}"  # IP fallback → lower limit
```

Authenticated users get more headroom (they're accountable). Anonymous IPs get strict limits (abuse vector).

---

## FastAPI Dependency Pattern

Rate limiting as a dependency means any endpoint can opt-in with one line:

```python
# Without rate limit (public endpoint)
async def health_check():
    ...

# With rate limit (protected endpoint)  
async def query(user: User = Depends(rate_limit_user)):
    ...
    # rate_limit_user = get_current_user + check_rate_limit
    # if limit hit → raises 429 before endpoint body runs
```

The endpoint never sees the rate limit logic — it's purely in the dependency.

---

## Graceful Degradation

```python
except Exception as e:
    # Redis down → allow request
    logger.warning(f"Rate limit check failed: {e}")
    return limit   # return full allowance = no blocking
```

If Redis is unavailable, rate limiting is silently skipped. Users are never blocked because of your infra issues — the cost is temporarily unlimited requests, which is acceptable.

---

## Interview Questions

**Q: What's the difference between rate limiting and throttling?**
Rate limiting hard-blocks requests over the limit (returns 429). Throttling slows requests down (adds delay, queues them). Rate limiting is simpler and more common for APIs. Throttling is used when you want to degrade gracefully rather than reject.

**Q: Why use Redis for rate limiting instead of in-memory?**
In-memory counters are per-process. With multiple API workers (Gunicorn with 4 workers), each worker has its own counter — the effective limit becomes 4x the intended limit. Redis is shared across all workers, so the counter is global and accurate.

**Q: What does `Retry-After` mean and why include it?**
It tells the client the number of seconds to wait before retrying. Without it, clients either retry immediately (wastes requests) or wait an arbitrary duration. With it, clients can back off precisely and retry as soon as the window resets — better UX, less wasted traffic.
