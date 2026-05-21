# Nexus AI — Enterprise Multi-Agent RAG Platform

> Upload any documents. Ask complex questions in plain English. Get accurate answers with citations — powered by a multi-agent AI pipeline.

[![CI](https://github.com/kratos0718/nexus-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/kratos0718/nexus-ai/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-15-black)](https://nextjs.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-orange)](https://langchain-ai.github.io/langgraph)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          NEXUS AI                                    │
│                                                                      │
│  ┌──────────────────┐          ┌──────────────────────────────────┐  │
│  │  Next.js 15      │  REST +  │         FastAPI Backend          │  │
│  │  Frontend        │◄──SSE──►│  Auth · Chat · Docs · Search     │  │
│  │                  │          │  Observability · Eval · Agents   │  │
│  │  • Chat (stream) │          └──────────────┬───────────────────┘  │
│  │  • Documents     │                         │                      │
│  │  • Observability │          ┌──────────────▼───────────────────┐  │
│  │  • Personas      │          │       RAG Pipeline               │  │
│  └──────────────────┘          │  Ingest → Chunk → Embed          │  │
│                                │  Retrieve (hybrid) → Rerank      │  │
│                                │  Generate (Groq/Llama 3.3-70B)   │  │
│                                └──────────────┬───────────────────┘  │
│                                               │                      │
│                         ┌─────────────────────▼──────────────────┐  │
│                         │       LangGraph Multi-Agent            │  │
│                         │  Router → Planner → Researcher (×N)   │  │
│                         │       → Synthesizer → Answer          │  │
│                         └──────────┬───────────┬────────────────┘  │
│                                    │           │                    │
│             ┌──────────────────────▼──┐  ┌────▼──────────────────┐ │
│             │  ChromaDB / Pinecone    │  │  PostgreSQL + Redis   │ │
│             │  (384-dim HNSW index)   │  │  Users · Docs · Chat  │ │
│             │  BM25 sparse index      │  │  Traces · Cache       │ │
│             └─────────────────────────┘  └───────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Features

### RAG Pipeline
- **Multi-format ingestion** — PDF, DOCX, TXT, Markdown, URLs
- **Three chunking strategies** — Recursive (default) · Semantic (embedding-based boundary detection) · Fixed-size
- **Hybrid retrieval** — dense semantic search + sparse BM25, fused with Reciprocal Rank Fusion
- **Cross-encoder reranking** — post-retrieval precision boost (sentence-transformers)
- **Three retrieval modes** — Standard · HyDE (Hypothetical Document Embeddings) · Multi-query expansion
- **Source citations** — every answer traces to specific chunks with confidence scores

### Multi-Agent System (LangGraph)
- **Router** — classifies query complexity, routes simple vs complex with Pydantic structured output
- **Planner** — decomposes complex questions into 2–4 targeted sub-questions
- **Researcher** — parallel retrieval across knowledge base per sub-question
- **Synthesizer** — combines context, generates grounded cited answer
- Real-time step streaming — routing decisions and sub-questions visible as they happen

### Backend (FastAPI)
- JWT auth — 30-min access + 7-day rotating refresh tokens, bcrypt password hashing
- Redis query cache — repeat queries served in <5ms vs 3–4s LLM call (800× speedup)
- Redis rate limiting — 100 req/hr per user, graceful Redis-down fallback
- Celery async document processing — instant 202 response, background indexing with retry
- Server-Sent Events streaming — token-by-token responses, <300ms TTFT
- Request ID middleware — `X-Request-ID` on every request for log correlation
- Security guard — 11 prompt-injection regex patterns, SSRF blocking, magic-byte file validation
- System prompts / Personas — per-user custom LLM roles, resolved at query time

### Observability & Evaluation
- LLM trace table — every query logs tokens, latency, model, cost estimate
- Aggregate stats — total calls, min/avg/P95/max latency, token breakdown, error rate
- Cache stats — hit rate, entry count, Redis memory usage, manual flush
- RAGAS evaluation pipeline — Faithfulness 0.91 · Answer Relevancy 0.88 · Context Recall 0.85
- RLHF feedback — thumbs up/down ratings, stats dashboard, JSONL export for fine-tuning

### Frontend (Next.js 15)
- Streaming chat with SSE — tokens appear in real-time
- Agent mode toggle — live routing badge and sub-question display
- Retrieval mode + persona selector in toolbar
- Document management — upload with chunking strategy picker, URL indexing, status polling
- Knowledge base explorer — browse indexed chunks, run semantic search per document
- Observability dashboard — latency bars (P95), token stats, cache panel, trace table

### DevOps
- Docker Compose — one command full stack (FastAPI + PostgreSQL + Redis + ChromaDB)
- GitHub Actions CI — lint (ruff) → backend tests with coverage gate → TypeScript check
- Frontend deploys to Vercel (free, no card) — auto-deploy on push to main via GitHub integration
- Liveness (`/ping`) + readiness (`/health`) probes — DB, Redis, pipeline, vector store

---

## Quick Start

**Prerequisites:** Python 3.11+, Node.js 18+, [free Groq API key](https://console.groq.com)

```bash
# 1. Clone and configure
git clone https://github.com/kratos0718/nexus-ai.git
cd nexus-ai
cp backend/.env.example backend/.env
# Edit backend/.env — add GROQ_API_KEY and JWT_SECRET_KEY

# 2. Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
# → http://localhost:8000/docs

# 3. Frontend (new terminal)
cd frontend
npm install && npm run dev
# → http://localhost:3000
```

> PostgreSQL and Redis are optional for local dev — the system falls back to SQLite and no-cache mode.

```bash
# Start full infrastructure stack
docker compose up postgres redis -d
```

---

## API Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/auth/register` | — | Create account |
| `POST` | `/api/v1/auth/login` | — | Get JWT tokens |
| `POST` | `/api/v1/auth/refresh` | — | Rotate refresh token |
| `GET` | `/api/v1/auth/me` | ✓ | Current user profile |
| `POST` | `/api/v1/documents/upload` | ✓ | Upload + index a file |
| `POST` | `/api/v1/documents/url` | ✓ | Index a URL |
| `GET` | `/api/v1/documents/` | ✓ | List documents |
| `DELETE` | `/api/v1/documents/{id}` | ✓ | Delete document + chunks |
| `GET` | `/api/v1/documents/{id}/chunks` | ✓ | Browse indexed chunks |
| `POST` | `/api/v1/chat/query` | ✓ | Ask question (blocking) |
| `POST` | `/api/v1/chat/stream` | ✓ | Streaming answer (SSE) |
| `POST` | `/api/v1/agent/stream` | ✓ | Multi-agent streaming (SSE) |
| `POST` | `/api/v1/search/` | ✓ | Semantic search, no LLM |
| `GET` | `/api/v1/conversations/` | ✓ | List conversations |
| `POST` | `/api/v1/system-prompts/` | ✓ | Create persona |
| `GET` | `/api/v1/system-prompts/` | ✓ | List personas |
| `POST` | `/api/v1/feedback/` | ✓ | Submit answer rating |
| `GET` | `/api/v1/feedback/stats` | ✓ | Rating stats |
| `GET` | `/api/v1/feedback/export` | ✓ | Export ratings as JSONL |
| `GET` | `/api/v1/traces/stats` | ✓ | Token usage + latency stats |
| `GET` | `/api/v1/cache/stats` | ✓ | Cache hit rate + metrics |
| `DELETE` | `/api/v1/cache/flush` | ✓ | Flush query cache |
| `GET` | `/api/v1/eval/results/latest` | ✓ | Latest RAGAS scores |
| `GET` | `/health` | — | Detailed subsystem health check |
| `GET` | `/ping` | — | Liveness probe |

Full interactive docs at `http://localhost:8000/docs` (Swagger UI).

---

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | **Yes** | — | LLM provider (console.groq.com) |
| `JWT_SECRET_KEY` | **Yes** | — | Token signing key (32+ chars) |
| `SECRET_KEY` | **Yes** | — | App secret key (32+ chars) |
| `DATABASE_URL` | No | SQLite | PostgreSQL for production |
| `REDIS_URL` | No | — | Enables caching + rate limits |
| `VECTOR_STORE_PROVIDER` | No | `chroma` | `chroma` or `pinecone` |
| `EMBEDDING_PROVIDER` | No | `huggingface` | `huggingface` or `openai` |
| `ALLOWED_ORIGINS` | No | `localhost:3000` | CORS allowed origins |
| `LOG_FORMAT` | No | `text` | `text` or `json` (prod) |

See [`backend/.env.example`](backend/.env.example) and [`backend/.env.production.example`](backend/.env.production.example) for the full reference.

---

## Testing

```bash
cd backend

# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=app --cov-report=term-missing

# Run a specific test file
pytest tests/test_auth.py -v

# Run tests matching keyword
pytest tests/ -k "feedback" -v
```

The test suite uses **in-memory SQLite** — no external services needed. It covers:
- Auth flows (register, login, refresh, token validation)
- Document CRUD with ownership isolation
- Conversation management
- System prompts CRUD
- Feedback submission and stats
- Observability traces and stats
- Cache admin endpoints
- Security guard (prompt injection, SSRF, file validation)
- JWT / password hashing unit tests
- Rate limiter with Redis mocked

---

## Project Structure

```
nexus-ai/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/   # REST endpoints (15 modules)
│   │   ├── agents/             # LangGraph nodes (router, planner, researcher, synthesizer)
│   │   ├── core/               # Auth, DB, cache, rate limiting, security guard, config
│   │   ├── middleware/         # Request ID tracing
│   │   ├── models/             # SQLAlchemy ORM (User, Document, Conversation, Trace, Feedback, SystemPrompt)
│   │   ├── rag/                # Pipeline, embeddings, retrieval, generation
│   │   └── services/           # Business logic (RAGService, TraceService, QueryProcessor)
│   ├── eval/                   # RAGAS evaluation runner + results
│   ├── tests/                  # pytest suite — 11 test modules, 90+ tests
│   ├── railway.toml            # Railway deployment config
│   └── .env.production.example # Production env vars reference
├── frontend/src/app/(app)/
│   ├── chat/                   # Streaming chat + agent mode
│   ├── dashboard/              # Document management + KB explorer
│   ├── observability/          # LLM metrics + cache stats dashboard
│   └── system-prompts/         # Persona management
├── learning/
│   ├── concepts/               # 33 deep-dive concept guides (embeddings → CI/CD → system design)
│   ├── daily/                  # Build logs for Days 1–25
│   ├── interview-prep/         # 301+ interview Q&As
│   └── resume/                 # ATS-ready resume bullets by day
├── docker-compose.yml
├── .github/workflows/ci.yml    # CI + CD pipeline
└── Makefile                    # make dev, make test, make lint
```

---

## Deployment

### Frontend → Vercel (free, no card required)

1. Push this repo to GitHub
2. Go to [vercel.com](https://vercel.com) → New Project → Import repo
3. Set **Root Directory** to `frontend`
4. Add environment variable: `NEXT_PUBLIC_API_URL=https://your-backend-url`
5. Deploy — Vercel detects Next.js automatically

### Backend → any Linux server via Docker Compose

```bash
# On your server (VPS, home lab, or any Linux machine)
git clone https://github.com/your-username/nexus-ai.git
cd nexus-ai

# Fill in your env vars
cp backend/.env.production.example backend/.env
# Edit backend/.env — set GROQ_API_KEY, SECRET_KEY, JWT_SECRET_KEY, ALLOWED_ORIGINS

# Start the full stack (FastAPI + PostgreSQL + Redis + ChromaDB)
docker compose up -d

# Run database migrations
docker compose exec backend alembic upgrade head
```

The app is then reachable at `http://your-server-ip:8000`.

> **Free hosting options (no card required):** Render free tier supports Docker deploys. Set `DATABASE_URL` and `REDIS_URL` from Render's managed add-ons. See [`backend/.env.production.example`](backend/.env.production.example) for all required variables.

---

## Learning Journal

The [`/learning`](./learning) directory is a complete study guide built alongside the project. Each concept guide goes from basics to production patterns with code examples, real-world analogies, and interview Q&A.

**33 concept guides:** Embeddings · HNSW · RAG pipeline · Hybrid search · Reranking · HyDE · Multi-query · LangGraph · Structured outputs · JWT · Redis caching · Celery · Rate limiting · Security · RAGAS · CI/CD · Docker · React SSE · Observability · Vector databases · Chunking strategies · RLHF / DPO · Prompt engineering · Cloud deployment · Caching & performance · Testing patterns · System design (RAG)

---

## Tech Stack

```
Backend    Python · FastAPI · LangChain · LangGraph · SQLAlchemy · Alembic · Celery
AI/ML      Groq (Llama 3.3-70B) · sentence-transformers · ChromaDB · Pinecone · RAGAS
Frontend   Next.js 15 · TypeScript · Tailwind CSS
Infra      PostgreSQL · Redis · Docker · GitHub Actions · Vercel
```
