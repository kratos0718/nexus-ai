# LLM Observability — Monitoring AI Systems in Production

## LEVEL 1 — Why Normal Monitoring Isn't Enough for AI

Traditional web services are deterministic: same input → same output.
You monitor: uptime, latency, error rate, request count. Simple.

LLM applications are non-deterministic and context-dependent:
- Same question → different answers depending on retrieved context
- "Correct" is subjective (not a 200 vs 500)
- Failures are often silent (wrong answer looks like a right answer)
- Costs scale with tokens, not just requests

You need to monitor things that don't exist in traditional APM:

| Traditional | LLM-specific |
|---|---|
| Request latency | LLM inference time vs retrieval time |
| Error rate | Hallucination rate, "I don't know" rate |
| Throughput (req/s) | Token throughput (tokens/s) |
| CPU/memory | Token cost ($0.59/M prompt, $0.79/M completion) |
| HTTP 500s | LLM refusals, context window exceeded, empty answers |
| User retention | Conversation length, follow-up rate |

---

## LEVEL 2 — The Four Pillars of LLM Observability

### 1. Traces
A trace captures one complete LLM interaction end-to-end:

```
Trace: user question → retrieval → LLM call → answer
  ├── Span: embedding (23ms)
  ├── Span: vector search (45ms)
  ├── Span: reranking (18ms)
  └── Span: LLM generation (1,847ms)
       ├── Input: 2,140 tokens
       ├── Output: 312 tokens
       └── Model: llama-3.3-70b-versatile
```

### 2. Metrics
Aggregates over time that reveal trends:
- Average latency per day
- Token usage per user per hour
- Error rate per model
- Cache hit rate (% of queries served from cache)

### 3. Logs
Structured records of individual events:
```json
{
  "timestamp": "2026-05-21T09:23:11Z",
  "level": "INFO",
  "event": "llm_call",
  "model": "llama-3.3-70b-versatile",
  "prompt_tokens": 2140,
  "completion_tokens": 312,
  "duration_ms": 1847,
  "user_id": 42,
  "question_hash": "sha256:abc123"
}
```

### 4. Evaluations (advanced)
Automated quality checks on LLM outputs:
- Faithfulness: is the answer grounded in the retrieved context?
- Answer relevance: does the answer address the question?
- Context recall: did retrieval find the right chunks?

---

## LEVEL 3 — What Nexus Traces

Every successful `POST /chat/query` creates one `LLMTrace` row:

```
question    → what was asked (first 2000 chars)
answer      → what was answered (first 5000 chars)
model       → which LLM was used
prompt_tokens      → tokens in the input (context + question)
completion_tokens  → tokens in the generated answer
total_tokens       → sum (used for cost calculation)
duration_ms        → wall-clock time from API call start to response
trace_type  → "rag" (direct) or "agent" (multi-agent)
user_id     → which user made the request
document_id → which document was searched (null = all docs)
error       → null on success, error message on failure
created_at  → timestamp (indexed for time-series queries)
```

### Timer pattern

```python
t0 = time.monotonic()       # monotonic clock: never goes backwards
                             # (wall clock can jump on NTP sync)
result = await rag_service.query(...)
duration_ms = (time.monotonic() - t0) * 1000
```

`time.monotonic()` vs `time.time()`:
- `time.time()` is wall clock — can jump forward/backward (NTP, DST)
- `time.monotonic()` always increases — safe for measuring durations

### Fire-and-forget via BackgroundTask

```python
background_tasks.add_task(
    trace_service.record,
    db=db,
    question=request.question,
    duration_ms=duration_ms,
    ...
)
# Response is returned NOW — trace is written AFTER
```

The user gets their answer immediately. The DB write happens after FastAPI
sends the response. If the trace write fails, the user is unaffected.

---

## LEVEL 4 — Database Design for Traces

### Why a relational table, not a log file?

Log files:
- Append-only: fast to write
- Slow to query: no indexes, must scan everything
- No aggregation: can't easily compute "avg latency per user"
- Can't join with users/documents tables

Relational table:
- Indexes on `user_id`, `created_at`, `document_id` → fast filters
- SQL aggregations: `AVG()`, `SUM()`, `COUNT()`, `GROUP BY`
- Foreign key to users table → can join for user-level analysis
- Works with any SQL query tool (Metabase, Grafana, psql)

### Aggregate query example

```sql
-- Average latency and token cost per day (last 7 days)
SELECT
    DATE(created_at) as day,
    COUNT(*) as total_queries,
    ROUND(AVG(duration_ms), 0) as avg_latency_ms,
    SUM(total_tokens) as total_tokens,
    ROUND(SUM(prompt_tokens) / 1000000.0 * 0.59
        + SUM(completion_tokens) / 1000000.0 * 0.79, 4) as cost_usd
FROM llm_traces
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY DATE(created_at)
ORDER BY day DESC;
```

This query runs in milliseconds with the `created_at` index — would take
seconds scanning a log file.

### Capping stored text

```python
question=question[:2000]   # cap very long questions
answer=(answer or "")[:5000]   # cap very long answers
```

Why cap?
- LLM answers can be 10,000+ tokens for complex summaries
- Storing full text would make the table huge (GBs over time)
- The first 5000 chars are sufficient for debugging
- Production: store only a hash + pointer to object storage (S3)

---

## LEVEL 5 — Aggregate Stats Endpoint

```python
# SQLAlchemy aggregate query
q = select(
    func.count(LLMTrace.id).label("total_calls"),
    func.coalesce(func.sum(LLMTrace.total_tokens), 0).label("total_tokens"),
    func.coalesce(func.avg(LLMTrace.duration_ms), 0).label("avg_duration_ms"),
    func.count(LLMTrace.error).label("error_count"),
)
row = (await db.execute(q)).one()
```

`func.coalesce(expr, 0)` — if `expr` is NULL (e.g., no rows yet), return 0.
Prevents division by zero and null-related errors in downstream code.

### Cost estimation

```python
# Groq pricing (as of 2026, if they add paid tier):
# llama-3.3-70b: $0.59/M prompt tokens, $0.79/M completion tokens
cost = (
    row.total_prompt_tokens / 1_000_000 * 0.59
    + row.total_completion_tokens / 1_000_000 * 0.79
)
```

For OpenAI users:
- gpt-4o: $5.00/M prompt, $15.00/M completion
- gpt-4o-mini: $0.15/M prompt, $0.60/M completion

Tracking tokens lets you calculate actual spend and set budget alerts.

---

## LEVEL 6 — What Production Observability Looks Like (Langfuse)

Nexus uses a lightweight local solution. Production systems use dedicated
LLM observability platforms. The most popular is **Langfuse** (open-source,
free tier available).

### Langfuse integration (3 lines)

```python
from langfuse.decorators import observe, langfuse_context

@observe(name="rag-query")
def generate(self, query, context_results, history):
    # ... existing generation code ...

    # Attach metadata to the trace
    langfuse_context.update_current_observation(
        input=query,
        output=answer,
        usage={"input": prompt_tokens, "output": completion_tokens},
        model=self._model,
    )
    return result
```

Langfuse gives you:
- Web dashboard with trace timeline view
- Automatic cost calculation for 50+ models
- User session tracking (group traces by conversation)
- A/B testing (compare prompt versions)
- Human feedback collection (thumbs up/down)
- Automated evals (GPT-as-judge, RAGAS)

### Comparison: Local vs Langfuse

| Feature | Nexus (local DB) | Langfuse |
|---|---|---|
| Setup | Zero (already have DB) | Sign up + API key |
| Cost | Free | Free tier, then paid |
| Dashboard | Build your own | Built-in web UI |
| Retention | Until DB full | Configurable |
| Evals | Manual SQL | Automated |
| Multi-tenant | Yes (by user_id) | Yes |
| Offline | Yes | No (SaaS) |

For a portfolio project: local is fine + you understand exactly how it works.
For production: Langfuse (or Helicone, Arize Phoenix, Weights & Biases).

---

## LEVEL 7 — Metrics to Alert On

Set up alerts when these cross thresholds:

| Metric | Warning | Critical | What it means |
|---|---|---|---|
| avg_duration_ms | > 5,000ms | > 10,000ms | LLM slow / Groq down |
| error_rate_pct | > 2% | > 10% | Pipeline bug / context overflow |
| total_tokens (hourly) | > 50k | > 100k | Cost spike / abuse |
| p95_duration_ms | > 8,000ms | > 15,000ms | Tail latency problem |
| "I don't know" rate | > 20% | > 40% | Poor retrieval quality |

### p95 latency (percentile latency)

Average latency is misleading. If 95% of requests take 1s but 5% take 30s,
your average looks fine but 1-in-20 users waits 30 seconds.

```sql
-- p95 latency (PostgreSQL)
SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_ms
FROM llm_traces
WHERE created_at >= NOW() - INTERVAL '1 hour';
```

---

## LEVEL 8 — The Observability Maturity Model

### Level 0 — Blind
No monitoring. You find out about failures from user complaints.

### Level 1 — Logs only
`print()` or `logger.info()`. You can search logs but no aggregation.

### Level 2 — Structured logs + basic metrics
JSON logs (loguru). Token count and latency tracked. What Nexus had before Day 11.

### Level 3 — Traces in DB (what we built)
Every call recorded. Can query by user, time, document. Cost estimation. Error tracking.

### Level 4 — Dashboards + alerting
Grafana/Metabase connecting to DB. Alerts when latency spikes.

### Level 5 — Automated quality evaluation
RAGAS scores on a sample of traces. Detect when retrieval quality degrades.
A/B test prompt changes and measure answer quality statistically.

### Level 6 — Full MLOps loop
Evaluation failures trigger fine-tuning jobs. Automated regression detection.
Data flywheel: user feedback → training data → better model.

Most production AI teams operate at Level 3-4. Level 5-6 is rare.

---

## Interview Questions

**Q: What would you monitor in an LLM application that you wouldn't in a normal API?**
Beyond standard latency/error metrics: token consumption per request (for cost), answer quality (hallucination rate, "I don't know" rate), retrieval quality (were the right chunks found), context window utilization (what % of max tokens are we using), cache hit rate (what % of queries were served from cache vs LLM), and model-specific metrics like p95 generation latency and completion/prompt token ratio.

**Q: What's the difference between a trace and a log?**
A log is a timestamped string event — one line per thing that happened, written sequentially. A trace is a structured record of one complete operation with all its attributes, stored in a queryable format (DB or trace backend). Logs tell you "what happened and when." Traces tell you "for query X by user Y using model Z, it took 1.8s and cost 2,452 tokens." Traces are queryable, aggregatable, and joinable; logs require grep/regex parsing.

**Q: Why use `time.monotonic()` instead of `time.time()` for measuring latency?**
`time.time()` returns wall-clock time, which can jump forward or backward due to NTP synchronization or daylight saving time adjustments. `time.monotonic()` is a system clock that only moves forward, guaranteed never to decrease. For measuring durations (end - start), you need a monotonic clock to avoid getting negative or artificially large values if the clock is adjusted mid-measurement.

**Q: How would you detect if your RAG system's quality is degrading over time?**
Track the rate of "I don't have that information" answers (indicates poor retrieval). Track user follow-up rate (users who immediately ask the same question differently are dissatisfied). Track conversation length (longer conversations to get an answer indicate lower first-try quality). Set up automated RAGAS evaluation on a 5% sample of queries. Compare faithfulness scores week-over-week and alert if they drop below a threshold.
