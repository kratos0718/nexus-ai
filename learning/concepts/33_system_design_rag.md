# System Design: Enterprise RAG Platform

## The interview question you will get

"Design a system that lets enterprise users upload internal documents and ask questions in plain English, with answers sourced only from those documents."

This is a multi-layer system design problem. Interviewers are looking for:
1. Ability to break down a complex system into components
2. Understanding of the AI/ML layer (not just the plumbing)
3. Scalability awareness at each layer
4. Production concerns: latency, cost, security, observability

This guide walks through a production answer from scratch.

---

## Step 1 — Clarify requirements (always do this first)

**Functional requirements:**
- Upload documents (PDF, DOCX, TXT, URLs)
- Index documents for retrieval
- Ask questions, get cited answers
- Multi-user with document ownership
- Streaming responses

**Non-functional requirements:**
- Latency: first token < 500ms for cached; < 5s for fresh queries
- Scale: 1,000 concurrent users, 10M document chunks in index
- Accuracy: grounded answers with no hallucination
- Cost: LLM calls are expensive — caching is mandatory

**Out of scope (say this explicitly):**
- Multi-modal (images, audio)
- Real-time data (web crawling)
- Fine-tuning on customer data

---

## Step 2 — High-level components

```
Client (browser) → API Gateway → FastAPI Backend → RAG Pipeline
                                      │                 │
                                   PostgreSQL      Vector Store
                                   Redis Cache     (ChromaDB)
                                   Celery Worker   (embedding)
```

Four conceptually distinct layers:
1. **Ingestion pipeline** — transform raw documents into searchable chunks
2. **Retrieval layer** — find relevant chunks for a query
3. **Generation layer** — synthesize a grounded answer with an LLM
4. **API + infra layer** — serve requests, authenticate users, cache results

---

## Step 3 — Deep dive: Ingestion pipeline

When a user uploads a file, you cannot process it synchronously in the HTTP request — PDF parsing + embedding can take 30-60 seconds.

**Pattern: Async task queue**
```
POST /documents/upload → 202 Accepted (instant)
     ↓
Celery worker picks up task:
  1. Parse file (PyMuPDF for PDF, python-docx for DOCX)
  2. Chunk text (recursive splitter, 512 tokens, 10% overlap)
  3. Embed chunks (sentence-transformers all-MiniLM-L6-v2, batch of 32)
  4. Upsert into ChromaDB with metadata {doc_id, user_id, source, page}
  5. Update document status: "ready"
Frontend polls GET /documents/{id} until status="ready"
```

**Chunking strategies:**

| Strategy | How | Best for |
|----------|-----|----------|
| Fixed-size | Split every N chars with overlap | Simple, predictable |
| Recursive | Split on `\n\n`, `\n`, `. ` in order | General prose |
| Semantic | Split where embedding distance jumps | Long documents with topic shifts |

**Embedding model choice:**
- `all-MiniLM-L6-v2` — 384 dims, fast, free, runs on CPU. Good for most RAG use cases.
- `text-embedding-3-small` (OpenAI) — 1536 dims, better quality, costs money, external API.
- Rule of thumb: start with HuggingFace locally, upgrade to OpenAI if retrieval quality is poor.

**Multi-user isolation:**
- Every chunk is stored with `user_id` in metadata
- Every retrieval query filters by `user_id`
- User A cannot retrieve User B's documents — enforced at the vector store query level, not application level

---

## Step 4 — Deep dive: Retrieval layer

Naive retrieval = embed query, cosine search. Production retrieval has three additional steps.

### Hybrid retrieval

Pure semantic search misses exact keyword matches ("contract section 4.2.1"). Pure BM25 misses paraphrases. Hybrid search combines both.

```python
# Dense retrieval
dense_results = vector_store.search(query_embedding, k=20)

# Sparse retrieval  
bm25_results = bm25_index.search(query_text, k=20)

# Reciprocal Rank Fusion
def rrf(results_list, k=60):
    scores = {}
    for results in results_list:
        for rank, doc in enumerate(results):
            scores[doc.id] = scores.get(doc.id, 0) + 1 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)

fused = rrf([dense_results, bm25_results])[:10]
```

### Reranking

After retrieval, apply a cross-encoder model to re-score the top-20 results and keep top-5:
```python
# Bi-encoder (retrieval): fast, approximate
# Cross-encoder (reranking): slow, precise — reads both query AND chunk together
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
scores = reranker.predict([(query, chunk.text) for chunk in candidates])
top5 = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)[:5]
```

Cross-encoders are 10-100× slower than bi-encoders, so apply them to the small candidate set (20), not the full index.

### HyDE (Hypothetical Document Embeddings)

For sparse or ambiguous queries, generate a hypothetical answer first, embed it, and search with that embedding:
```python
hyp_answer = llm.complete("Write a short answer to: " + query)
hyp_embedding = embed(hyp_answer)  # embed the answer, not the question
results = vector_store.search(hyp_embedding, k=10)
```

HyDE works because document embeddings cluster by topic, and a generated answer is closer to real documents than a short question fragment.

### Multi-query expansion

For complex queries, generate 3 variations and retrieve for each:
```python
variations = llm.complete(f"Generate 3 different search queries for: {query}")
all_results = []
for q in variations:
    all_results.extend(vector_store.search(embed(q), k=10))
final = rrf([all_results])[:10]  # deduplicate via RRF
```

---

## Step 5 — Deep dive: Generation layer

**Prompt construction:**
```python
SYSTEM = """You are a precise document assistant. Answer using ONLY the provided context.
If the answer is not in the context, say "I don't have that information."
Always cite your sources."""

context = "\n\n".join([
    f"[Source: {r.metadata['source']}, score: {r.score:.2f}]\n{r.text}"
    for r in top_results
])

user_message = f"Context:\n{context}\n\nQuestion: {query}"
```

**Streaming with SSE:**
```python
async def stream_answer(query, context):
    async for token in groq_client.stream(messages=[...]):
        yield f"data: {json.dumps({'token': token})}\n\n"
    yield "data: [DONE]\n\n"
```

Server-Sent Events push tokens to the browser as they're generated — first token in <300ms, full answer streams progressively.

**LLM selection:**
- Groq + Llama 3.3-70B: 800 tokens/sec, free tier, great for demo and dev
- GPT-4o: slower, expensive, better instruction following
- Claude 3.5 Sonnet: best at long context, citation extraction
- Rule: Groq for speed, GPT-4/Claude for quality

---

## Step 6 — Multi-agent architecture

For complex questions ("Compare the warranty terms in documents A and B and identify conflicts"), a single RAG call is insufficient.

**LangGraph agent graph:**
```
Query → Router
           ├── simple → Standard RAG (single retrieval + generate)
           └── complex → Planner
                            └── 2-4 sub-questions
                                    → Researcher (parallel retrieval, one per sub-question)
                                            → Synthesizer (combine all contexts + generate)
```

**Router (structured output):**
```python
class RouterDecision(BaseModel):
    route: Literal["simple", "complex"]
    reasoning: str

decision = llm.with_structured_output(RouterDecision).invoke(query)
```

Pydantic structured output forces the LLM to return valid JSON that maps directly to your Python model — no regex parsing.

**Parallel researchers:**
LangGraph supports concurrent node execution:
```python
graph.add_node("researcher_1", research_node)
graph.add_node("researcher_2", research_node)
graph.add_edge("planner", ["researcher_1", "researcher_2"])  # parallel edges
graph.add_edge(["researcher_1", "researcher_2"], "synthesizer")
```

---

## Step 7 — Caching strategy

LLM calls cost ~$0.001-0.01 per query and take 2-5 seconds. Caching is the highest-leverage optimization.

**Query cache (Redis):**
- Key: `SHA256(user_id + query.strip().lower())`
- TTL: 24 hours (or invalidate on document change)
- Hit rate in practice: 30-60% for enterprise users (repeat questions common)
- Speedup: 5ms (cache hit) vs 3-4s (LLM call) = 800× speedup

**What NOT to cache:**
- Agent streaming responses (state depends on sub-question results)
- Personalized responses (system prompt changes the answer)
- Real-time data queries

**Cache invalidation:**
When a document is deleted or updated, invalidate all cached queries for that user:
```python
keys = list(redis.scan_iter(f"nexus:query:{user_id}:*"))
if keys:
    redis.delete(*keys)
```
Use `SCAN` not `KEYS` — `KEYS` blocks Redis, `SCAN` iterates non-blocking.

---

## Step 8 — Security

**Prompt injection defense:**
```python
INJECTION_PATTERNS = [
    r"ignore (all )?previous instructions",
    r"you are now",
    r"disregard (your|the) (system|previous)",
    r"<\s*script",
]
for pattern in INJECTION_PATTERNS:
    if re.search(pattern, query, re.IGNORECASE):
        raise SecurityViolation("Potential prompt injection detected")
```

**File validation (magic bytes):**
```python
MAGIC_BYTES = {
    b"%PDF": "pdf",
    b"PK\x03\x04": "docx",  # ZIP-based format
}
header = file.read(8)
if not any(header.startswith(sig) for sig in MAGIC_BYTES):
    raise ValueError("File type not recognized by content inspection")
```

Never trust the file extension alone — it can be spoofed.

**SSRF protection:**
Before fetching a URL for indexing, validate it:
```python
import ipaddress
parsed = urlparse(url)
ip = socket.gethostbyname(parsed.hostname)
addr = ipaddress.ip_address(ip)
if addr.is_private or addr.is_loopback or addr.is_link_local:
    raise SSRFViolation("Internal network addresses not allowed")
```

**JWT auth:**
- Access token: 30-minute expiry, used in Authorization header
- Refresh token: 7-day expiry, httpOnly cookie, rotated on each use
- Bcrypt for password hashing (cost factor 12, ~300ms per hash — intentionally slow)

---

## Step 9 — Observability

**What to instrument:**
- Every LLM call: tokens, latency, model, cost estimate
- Cache: hit/miss counts, memory usage
- Retrieval: number of chunks retrieved, average score
- Errors: type, endpoint, user

**P95 latency:**
The 95th percentile latency — 95% of requests are faster than this. Average hides outliers. P95 shows the "worst normal case." SLAs are written in P95/P99 terms.

```python
durations = sorted(all_durations)
p95 = durations[int(0.95 * len(durations))]
```

**RAGAS evaluation:**
Automated quality evaluation without human labeling:
- **Faithfulness** — is the answer grounded in the retrieved context? (anti-hallucination)
- **Answer Relevancy** — does the answer address the question asked?
- **Context Recall** — how much of the reference answer is covered by retrieved chunks?

Run RAGAS on a gold dataset (50-200 question/answer/ground-truth triples) before shipping.

---

## Step 10 — Scaling

| Bottleneck | Solution |
|-----------|---------|
| Embedding (CPU-bound) | GPU inference server, batch embeddings |
| Vector search (I/O) | Pinecone (managed), HNSW index sharding |
| LLM calls (external API) | Cache aggressively, async queuing |
| DB reads | PostgreSQL read replicas, connection pooling (asyncpg) |
| File processing | Celery workers, auto-scaling on queue depth |

**From 100 to 10,000 users:**
1. Move from SQLite → PostgreSQL (done from day 1 in Nexus AI)
2. Add Redis cluster (cache + rate limiting)
3. Move ChromaDB → Pinecone (managed vector store, serverless pricing)
4. Add worker autoscaling (Celery + Kubernetes HPA on queue length)
5. CDN for frontend, multi-region API

---

## Interview answer framework

When asked "design a document QA system":

1. **Clarify** (2 min): functional + non-functional requirements, scale
2. **High-level** (2 min): draw the 4-layer diagram, name each component
3. **Ingest deep dive** (3 min): async Celery, chunking, embedding, vector store
4. **Query deep dive** (3 min): hybrid retrieval, reranking, LLM generation, streaming
5. **Scaling** (2 min): cache, queue, managed services
6. **Trade-offs** (2 min): quality vs latency (HyDE slower, more accurate), cost vs freshness (TTL), open-source vs managed

**Numbers to remember:**
- all-MiniLM-L6-v2: 384 dims, ~60ms per batch of 32 on CPU
- Groq: ~800 tokens/sec (fast!), free tier 30 req/min
- Redis cache hit: <5ms vs LLM call 3-4s = 800× speedup
- P95 target for RAG: <5s, good systems hit <3s
- RAGAS scores: Faithfulness >0.85 is acceptable, >0.9 is good

---

## 25-Day Project Summary — What You Built

| Day | Feature | Key concept |
|-----|---------|-------------|
| 1 | FastAPI skeleton | REST API design |
| 2 | SQLAlchemy + Alembic | Database migrations |
| 3 | JWT auth | Stateless authentication |
| 4 | Document upload + parse | Async file processing |
| 5 | Embeddings + ChromaDB | Vector representations |
| 6 | Basic RAG pipeline | Retrieval-augmented generation |
| 7 | Groq LLM integration | LLM API patterns |
| 8 | SSE streaming | Server-sent events |
| 9 | Hybrid retrieval (BM25) | Sparse + dense fusion |
| 10 | Cross-encoder reranking | Precision post-retrieval |
| 11 | HyDE retrieval mode | Query expansion |
| 12 | Multi-query expansion | Robustness |
| 13 | LangGraph router | Structured agent output |
| 14 | Planner + sub-questions | Task decomposition |
| 15 | Parallel researchers | Concurrent LangGraph nodes |
| 16 | Synthesizer agent | Multi-context generation |
| 17 | RAGAS evaluation | Automated RAG quality metrics |
| 18 | Security guard | Prompt injection, SSRF, magic bytes |
| 19 | Redis caching | Cache-aside, TTL, key design |
| 20 | System prompts / Personas | Per-user LLM role injection |
| 21 | CI pipeline | GitHub Actions, ruff, coverage gate |
| 22 | Railway deployment | PaaS, probes, Dockerfiles |
| 23 | Cache observability | Hit/miss counters, P95, SCAN |
| 24 | Test suite expansion | Fixtures, mocks, ownership isolation |
| 25 | Eval pipeline + system design | RAGAS runner, final polish |
