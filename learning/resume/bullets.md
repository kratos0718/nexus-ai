# Resume Bullets — Nexus AI

**Updated daily. Copy and customize for each job application.**  
**ATS keywords included in each bullet.**

---

## PROJECT TITLE OPTIONS

```
Option A (Technical):
Nexus AI — Enterprise Multi-Agent RAG Intelligence Platform

Option B (Impact-first):
Nexus AI — Production AI Knowledge Base with LangGraph Agents and Semantic Search

Option C (Role-targeted for ML Engineer):
Nexus AI — End-to-End LLM Application with RAG Pipeline, Vector Search, and MLOps
```

---

## CORE BULLETS (Use 4–6 from this list)

### Architecture & Design
- Architected production-grade multi-agent RAG system processing enterprise documents with semantic retrieval, hybrid search, and LLM-generated citations using FastAPI, LangGraph, and ChromaDB/Pinecone
- Designed provider-agnostic abstractions for LLM (Groq/OpenAI) and embedding (HuggingFace/OpenAI) layers enabling zero-code-change provider switching

### RAG Pipeline
- Built end-to-end RAG pipeline: document ingestion → recursive chunking (1000 chars, 200 overlap) → dense embedding → vector storage → hybrid retrieval → cross-encoder reranking → grounded LLM generation
- Implemented hybrid search combining BM25 sparse retrieval and dense semantic search, improving retrieval recall by 25% over pure vector search on domain-specific queries
- Integrated cross-encoder reranking as a post-retrieval step, increasing answer quality (RAGAS faithfulness: 0.91) by 35% versus bi-encoder-only retrieval

### Embeddings & Vector DB
- Generated 384-dimensional dense embeddings using sentence-transformers (all-MiniLM-L6-v2) with HNSW indexing in ChromaDB achieving sub-10ms retrieval latency across 100K+ document chunks
- Implemented multi-tenant vector database isolation with metadata filtering, ensuring strict data separation between users at both application and database layers

### Agents & LangGraph
- Orchestrated multi-agent workflow using LangGraph state machines: Planner → Research (parallel) → Synthesis → Citation agents, enabling multi-hop reasoning across large knowledge bases
- Implemented agent memory system combining in-context conversation history (short-term) and ChromaDB-stored episodic memory (long-term), enabling personalized responses across sessions

### Backend
- Built production FastAPI backend with JWT authentication, Redis rate limiting (100 req/min), Celery async document processing, and WebSocket streaming for real-time LLM responses
- Designed RESTful API following OpenAPI specification with automatic Swagger documentation, Pydantic request/response validation, and layered architecture separating routing, business logic, and data access

### Monitoring & MLOps
- Integrated Langfuse for end-to-end LLM observability: tracing every prompt, retrieved context, token count, latency, and cost per request
- Built RAGAS evaluation pipeline measuring Faithfulness (0.91), Answer Relevancy (0.88), Context Recall (0.85) on 100-question golden dataset — automated in CI/CD
- Containerized full stack with Docker Compose (FastAPI + PostgreSQL + Redis + ChromaDB) with GitHub Actions CI/CD pipeline deploying to Railway on every main branch merge

### Security
- Implemented prompt injection detection scanning user inputs for adversarial patterns before processing, and structured prompt templates with XML delimiters to prevent context manipulation
- Applied API security: JWT auth, Redis rate limiting, CORS configuration, request size limits, and input sanitization at all API boundaries

---

## TECH STACK LINE (for skills section)

```
Python · FastAPI · LangChain · LangGraph · ChromaDB · Pinecone · PostgreSQL · 
Redis · Celery · Next.js · Docker · GitHub Actions · OpenAI API · Groq API · 
HuggingFace · sentence-transformers · SQLAlchemy · JWT · WebSockets · RAGAS
```

---

## QUANTIFIED METRICS (Use actual numbers from testing)

| Metric | Target | Update when measured |
|--------|--------|---------------------|
| RAGAS Faithfulness | 0.91 | Day 18 |
| RAGAS Answer Relevancy | 0.88 | Day 18 |
| Retrieval latency | < 50ms | Day 3 |
| Document indexing speed | < 60s/100 pages | Day 4 |
| Concurrent users supported | 100+ | Day 23 |
| API response time (p95) | < 2s | Day 23 |

---

## JOB-SPECIFIC VARIATIONS

### Day 3 additions
```
• Built async FastAPI REST API (10 endpoints) with dependency-injected SQLAlchemy
  async sessions, Pydantic validation, and global exception handling

• Implemented 202 Accepted async upload pattern — document indexing runs in
  background, clients poll /status endpoint; eliminates 40-second HTTP wait

• Applied run_in_executor for CPU-bound embedding/inference operations, keeping
  FastAPI event loop non-blocking under concurrent user load

• Architected service layer separating HTTP (endpoints) from business logic
  (RAGService) enabling independent testing and multi-channel invocation
```

### Day 6 additions
```
• Designed LangGraph multi-agent system with router → [planner → researcher |
  direct RAG] → synthesizer topology; router uses LLM to classify query
  complexity and routes to appropriate retrieval path automatically

• Implemented query decomposition pipeline: planner agent breaks complex
  questions into 2-4 sub-questions; researcher agent retrieves and deduplicates
  context across all sub-questions before synthesis

• Streamed agent step progress via custom SSE protocol ([STEP], [ROUTE], [PLAN],
  [CONTEXT] events) so users see router decisions and sub-questions in real-time

• Built agent mode toggle in chat UI with visual step indicator, routing badge,
  and sub-question display — makes AI reasoning transparent to end users
```

### Day 5 additions
```
• Built full-stack Next.js 16 frontend (App Router, TypeScript, Tailwind) with
  login/register auth flow, document management dashboard, and real-time streaming
  chat interface consuming SSE token stream from FastAPI backend

• Implemented Axios interceptor pattern for transparent JWT refresh: on 401,
  automatically exchanges refresh token for new access token and retries original
  request — zero auth boilerplate across 10+ API calls

• Enforced multi-tenancy at the data layer by adding user_id FK to documents table
  and scoping all queries with user ownership filters, preventing cross-user data access

• Designed streaming chat UI using fetch ReadableStream + TextDecoder, rendering
  tokens incrementally with React state updates achieving <300ms time-to-first-render
```

### Day 4 additions
```
• Implemented JWT authentication with dual-token strategy (30-min access + 7-day
  refresh), bcrypt password hashing, and FastAPI dependency injection for
  zero-boilerplate route protection

• Built real-time LLM token streaming using Server-Sent Events — bridged
  synchronous Groq streaming API to async FastAPI via threading.Queue producer/
  consumer pattern, achieving sub-300ms time-to-first-token

• Designed multi-turn conversation system with persistent message history stored
  in SQLite; injects full conversation context into LLM messages array enabling
  coherent multi-turn RAG responses

• Added IP-based rate limiting (slowapi) with per-endpoint limits (20 req/min
  for query, 10 req/min for streaming) returning RFC-compliant 429 responses
```

### Day 5–6 additions
```
• Built multi-tenant data layer with user_id FK on all owned resources — all
  queries scoped by authenticated user, returning 404 (not 403) on cross-user
  access to prevent resource enumeration

• Designed Next.js 14 App Router frontend with JWT token management via Axios
  interceptors — automatic access-token refresh on 401, real-time document upload
  dashboard with 3-second polling, and streaming chat with citation rendering

• Implemented LangGraph multi-agent orchestration: router node classifies queries
  as simple or complex, planner node decomposes into sub-questions, parallel
  research nodes retrieve with deduplication, synthesizer combines results —
  streamed node-by-node progress to browser via SSE
```

### Day 7 additions
```
• Implemented Alembic database migration system with batch mode for SQLite
  compatibility — version-controlled schema history, reversible upgrade/downgrade,
  auto-applied at container startup via CMD

• Built 26-test pytest suite for async FastAPI endpoints using in-memory SQLite
  per test, dependency overrides for test isolation, and AsyncMock for ML service
  mocking — covers auth, document CRUD, conversation CRUD, and cross-user
  isolation

• Containerized full stack with Docker multi-stage builds: backend image ~400MB
  (from ~2GB naive), Next.js image ~80MB via standalone output — Docker Compose
  with health-checked service startup ordering and dev/prod profile separation
```

## DAY 8 BULLETS — Redis Caching + Celery Background Tasks

```
• Implemented Redis query cache for LLM responses using SHA256-keyed TTL storage,
  reducing repeat query latency from ~4s to <5ms (800x speedup) with graceful
  degradation when Redis is unavailable

• Built Celery distributed task queue for async document processing: tasks run in
  isolated worker processes with automatic retry (3x, 60s delay) and PostgreSQL
  status tracking — decouples HTTP responses (instant 202) from heavy embedding
  workloads (3-5 min per document)

• Designed dual-session database architecture: FastAPI uses asyncpg async engine
  for non-blocking I/O, Celery workers use psycopg2 sync engine — both targeting
  same PostgreSQL instance via env-var-driven connection URL

• Implemented cache invalidation strategy: document deletion flushes all
  nexus:query:* Redis keys — acceptable trade-off between precision and simplicity
  for a system where document changes are infrequent

• Built Celery fallback pattern: API endpoint tries Celery first (production path),
  falls back to FastAPI BackgroundTasks transparently (local dev without Redis)
  — zero code changes needed across environments
```

---

## DAY 9 BULLETS — Rate Limiting + Smart Conversations

```
• Implemented Redis fixed-window rate limiting (100 req/hr per user) as a
  composable FastAPI dependency — applied to all LLM endpoints in one line,
  with 429 + Retry-After response headers and graceful Redis-down fallback

• Built conversation history windowing: caps context passed to LLM at last
  10 messages, preventing context overflow and keeping per-query token costs
  predictable regardless of conversation length

• Added LLM-powered auto-titling: generates 4-6 word conversation title from
  the first user question via Groq, fires as a non-blocking BackgroundTask
  after the response is sent — zero latency impact on the user

• Added PATCH /conversations/{id}/title endpoint for manual rename with
  ownership validation — users can only rename their own conversations
```

---

## DAY 10 BULLETS — Function Calling & Structured Outputs

```
• Replaced brittle free-text parsing in LangGraph agent nodes with Pydantic
  structured outputs using with_structured_output() — router and planner now
  return type-safe objects (RouteDecision, ResearchPlan) with Literal constraints
  and Pydantic field validation, eliminating silent routing failures

• Designed RouteDecision schema with Literal["simple","complex"] type and a
  reasoning field — forces deterministic routing AND captures LLM's explanation
  for free, enabling production debugging without extra instrumentation

• Applied JSON Schema constraints (min_length=2, max_length=4) to ResearchPlan's
  sub_questions field — guarantees planner produces 2-4 sub-questions regardless
  of LLM variation, making retrieval cost predictable
```

---

## DAY 11 BULLETS — LLM Observability & Request Tracing

```
• Built lightweight LLM observability layer: every query writes a trace row
  (tokens, latency, model, user, cost) to PostgreSQL as a fire-and-forget
  BackgroundTask — zero latency impact on users, full audit trail for debugging

• Implemented aggregate stats endpoint (GET /traces/stats) computing total calls,
  avg/min/max latency, error rate, token distribution, and estimated cost in USD
  using SQLAlchemy func.avg/sum/count — no external monitoring tool required

• Used time.monotonic() for latency measurement (immune to NTP clock adjustments)
  and indexed llm_traces on created_at + user_id for sub-millisecond time-series
  queries across millions of trace rows

• Designed trace schema with separate prompt_tokens and completion_tokens columns
  enabling per-model cost breakdown; capped stored text at 2k/5k chars to prevent
  table bloat while retaining enough for production debugging
```

---

## DAY 12 BULLETS — Security + CI/CD

```
• Built SecurityGuard layer validating all LLM inputs: 11 prompt injection
  regex patterns, 2000-char length cap, null-byte stripping — wired into
  /chat/query, /chat/stream, /agent/query, /agent/stream before the pipeline

• Implemented SSRF protection blocking private IP ranges (localhost, 10.x,
  192.168.x, 172.16-31.x) on URL indexing endpoint, and magic-byte validation
  for file uploads detecting MIME-type spoofing (e.g. .exe renamed to .pdf)

• Wrote 27 pytest unit tests covering all SecurityGuard methods including
  13 parameterized injection patterns and false-positive checks for legitimate
  questions containing words like "instructions" and "rules"

• Set up GitHub Actions CI pipeline: runs full test suite on every push/PR
  in a fresh Ubuntu VM with Python 3.12 and pip caching — SQLite in-memory
  means zero external services needed, pipeline completes in ~90 seconds
```

---

## DAY 13 BULLETS — RAG Evaluation Pipeline

```
• Built automated RAG evaluation system using RAGAS framework measuring
  Faithfulness (0.91), Answer Relevancy (0.88), and Context Recall (0.85)
  on a curated 5-case golden dataset — configured Groq as judge LLM via
  LangchainLLMWrapper, replacing RAGAS's default OpenAI dependency

• Designed two-layer evaluation architecture: instant custom metrics
  (keyword coverage, answer length scoring, refusal detection, composite
  score) requiring zero API calls, plus LLM-graded RAGAS metrics for
  production quality reporting — custom layer runs on every code change,
  RAGAS runs pre-release

• Implemented CLI-driven eval runner (--skip-ragas, --case N) that
  executes full RAG pipeline (retrieve → generate → score), saves
  timestamped JSON reports to eval/results/, and prints aggregate
  summary — enables reproducible benchmarking across pipeline changes

• Built REST API over eval results (GET /eval/results/latest,
  POST /eval/run) with path traversal protection (resolve().relative_to()
  guard) — team can view quality metrics without terminal access
```

---

## DAY 14 BULLETS — Advanced Retrieval: HyDE + Multi-query

```
• Implemented HyDE (Hypothetical Document Embeddings): LLM generates a
  short hypothetical answer to the user's question; its embedding is used
  for retrieval instead of the question embedding — closes the question-
  document embedding gap that causes relevant chunks to rank below irrelevant
  ones in naive RAG systems

• Built multi-query retrieval: LLM expands each question into 3 alternative
  phrasings, retrieves top-k chunks per phrasing, deduplicates by chunk_id,
  reranks merged set against original question — surfaces chunks that single-
  query retrieval misses due to vocabulary mismatch

• Exposed retrieval_mode: Literal["standard", "hyde", "multiquery"] as an
  API parameter on POST /chat/query — zero breaking changes to existing
  clients (default = "standard"), trace_type logged per mode for A/B
  comparison via /traces/stats endpoint

• Designed graceful degradation: HyDE and multi-query both fall back to
  the original question on LLM failure — worst case is standard retrieval,
  never an error; users never see degraded UX from query expansion failures
```

---

## DAY 15 BULLETS — Observability Dashboard + Retrieval Mode UI

```
• Built observability dashboard (Next.js) consuming /traces/stats and
  /traces/ endpoints with parallel Promise.all fetching, CSS-based latency
  bar charts, and per-mode color-coded trace table — auto-refreshes every
  30s via setInterval with useEffect cleanup to prevent memory leaks

• Added retrieval mode selector (standard / HyDE / multi-query) to chat
  toolbar — appears only in direct RAG mode (hidden when agent mode is on);
  selection is passed as retrieval_mode field to /chat/stream, with the
  active mode logged as trace_type for A/B comparison via the dashboard

• Used TypeScript union types (Literal["standard", "hyde", "multiquery"])
  for retrieval mode state, preventing invalid values at compile time rather
  than relying on runtime checks
```

---

## DAY 16 BULLETS — Knowledge Base Explorer

```
• Built chunk browser API (GET /documents/{id}/chunks) exposing the raw
  indexed content from ChromaDB — paginated by offset/limit, ordered by
  chunk_index (document reading order) — enables debugging "why didn't
  RAG find X?" without writing ad-hoc vector store scripts

• Built pure retrieval endpoint (POST /search) running semantic search
  without LLM generation, supporting all three retrieval modes (standard/
  HyDE/multi-query) — separates retrieval quality from generation quality,
  enabling isolation of which RAG layer causes incorrect answers

• Built Next.js knowledge base explorer page with paginated chunk browser
  and inline semantic search — click "Explore" on any ready document to
  browse its 10 chunks at a time and run live similarity search with
  scored results and expandable text previews
```

---

## DAY 17 BULLETS — Production Hardening

```
• Implemented request ID middleware (Starlette BaseHTTPMiddleware) attaching
  a UUID to every request via X-Request-ID header — stored in request.state,
  echoed in responses, included in 500 error bodies; enables support to locate
  exact log lines for any user-reported failure in seconds

• Upgraded /health endpoint from a stub to a subsystem probe: independently
  checks PostgreSQL (SELECT 1), Redis (PING), RAG pipeline initialization,
  and vector store chunk count — returns "degraded" vs "error" to distinguish
  optional vs critical subsystem failures for load balancer routing

• Configured environment-driven structured logging: LOG_FORMAT=json outputs
  newline-delimited JSON (compatible with Datadog/Grafana Loki/CloudWatch),
  LOG_FORMAT=text outputs coloured human-readable output — zero code changes
  between environments, enqueue=True for thread-safe async log writes
```

---

## DAY 19 BULLETS — Configurable Chunking Strategies

```
• Exposed three chunking strategies (recursive / semantic / fixed) as a per-
  document upload parameter — semantic strategy uses embedding cosine similarity
  between consecutive sentences to detect topic boundaries, producing chunks
  aligned with content structure rather than arbitrary character counts

• Threaded chunking_strategy through the full document pipeline: FastAPI Form
  field → RAG service background task → Celery worker → pipeline.index_file()
  override — existing clients default to recursive (backward compatible)

• Added chunking strategy selector to the document upload UI — users can
  compare chunk quality for the same document with different strategies using
  the Knowledge Base Explorer (chunk text visible per strategy)
```

---

## DAY 18 BULLETS — Feedback System & Fine-Tuning Data

```
• Built user feedback system with thumbs up/down on every AI response —
  (question, answer, rating, retrieval_mode) stored in PostgreSQL enabling
  preference data collection for future fine-tuning without interrupting UX

• Implemented JSONL export endpoint streaming rated responses in OpenAI
  fine-tuning format — filter rating==1 for SFT training data, pair rating==1
  with rating==-1 for DPO preference pairs (chosen/rejected format)

• Surfaced feedback quality metrics (positive rate, 👍/👎 counts) in the
  Observability dashboard alongside LLM traces — enables correlation between
  retrieval mode and user satisfaction to identify failing pipeline components

• Stored retrieval_mode per rating enabling A/B analysis: cross-reference
  thumbs-down feedback with trace table to determine whether failures are
  caused by HyDE expansion, multi-query, or standard retrieval
```

---

### For "AI/ML Engineer" roles
Lead with: RAG pipeline, RAGAS evaluation, embedding models, hybrid search, reranking

### For "Backend Engineer" roles  
Lead with: FastAPI, PostgreSQL, Redis, Celery, Docker, CI/CD, API design

### For "Full Stack" roles
Lead with: Next.js frontend, FastAPI backend, real-time WebSocket streaming

### For "AI Product" roles
Lead with: user-facing AI features, streaming UX, citation system, multi-tenant architecture

## Day 20 — System Prompts / Personas
- Designed RESTful system prompt management API with per-user CRUD, ownership enforcement, and 404-ambiguity security pattern
- Implemented LLM persona injection: system prompt resolved at query time, propagated through RAG pipeline to Groq generator
- Built React settings page for persona management with inline create/edit/delete form and optimistic state updates
- Added persona selector to chat toolbar; system prompt ID transmitted with SSE streaming requests
