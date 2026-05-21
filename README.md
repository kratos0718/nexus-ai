# Nexus AI — Enterprise Multi-Agent RAG Platform

> Upload any documents. Ask complex questions in plain English. Get accurate answers with citations — powered by a multi-agent AI pipeline.

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
│  │  • KB Explorer   │          │       RAG Pipeline               │  │
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
- **Recursive chunking** — 800-char chunks, 150-char overlap, configurable
- **Hybrid retrieval** — dense semantic search + sparse BM25, fused with Reciprocal Rank Fusion
- **Cross-encoder reranking** — post-retrieval precision boost
- **Advanced retrieval modes** — Standard | HyDE (Hypothetical Document Embeddings) | Multi-query expansion
- **Source citations** — every answer traces to specific document chunks with confidence scores

### Multi-Agent System (LangGraph)
- **Router** — classifies query complexity, routes simple vs complex with Pydantic structured output
- **Planner** — decomposes complex questions into 2–4 targeted sub-questions
- **Researcher** — parallel retrieval across knowledge base per sub-question
- **Synthesizer** — combines context, generates grounded cited answer
- Real-time step streaming — users see routing decisions and sub-questions as they happen

### Backend (FastAPI)
- JWT auth with 30-min access + 7-day refresh tokens, bcrypt password hashing
- Redis query cache — repeat queries served in <5ms vs 3–4s LLM call (800× speedup)
- Redis rate limiting — 100 req/hr per user with graceful Redis-down fallback
- Celery async document processing — instant 202 response, background indexing with retry
- Server-Sent Events streaming — token-by-token real-time responses, <300ms TTFT
- Request ID middleware — `X-Request-ID` header on every request for log correlation
- Security guard — 11 prompt injection regex patterns, SSRF blocking, magic byte file validation

### Observability & Evaluation
- LLM trace table — every query logs tokens, latency, model, cost
- Aggregate stats API — total calls, avg/min/max latency, token breakdown, error rate
- Retrieval mode tracking — compare standard vs HyDE vs multi-query performance
- RAGAS evaluation pipeline — Faithfulness 0.91 · Answer Relevancy 0.88 · Context Recall 0.85

### Frontend (Next.js 15)
- Streaming chat with SSE — tokens appear in real-time
- Agent mode toggle — live routing badge and sub-question display
- Retrieval mode selector — standard / HyDE / multi-query per query
- Document management — upload files, index URLs, status polling
- **Knowledge base explorer** — browse indexed chunks, run semantic search per document
- **Observability dashboard** — latency bars, token stats, per-mode trace table

### DevOps
- Docker Compose — one command local stack (FastAPI + PostgreSQL + Redis + ChromaDB)
- GitHub Actions CI — full test suite on every push in ~90 seconds
- Detailed `/health` endpoint — probes DB, Redis, pipeline, vector store independently
- Provider abstraction — swap ChromaDB → Pinecone or HuggingFace → OpenAI via one env var

---

## Quick Start

**Prerequisites:** Python 3.11+, Node.js 18+, [free Groq API key](https://console.groq.com)

```bash
# 1. Clone and configure
git clone https://github.com/kratos0718/nexus-ai.git
cd nexus-ai
cp .env.example .env
# Edit .env — add GROQ_API_KEY and JWT_SECRET_KEY

# 2. Backend
cd backend
conda create -n nexus-ai python=3.11 -y && conda activate nexus-ai
pip install -r requirements.txt
uvicorn app.main:app --reload
# → http://localhost:8000/docs

# 3. Frontend (new terminal)
cd frontend
npm install && npm run dev
# → http://localhost:3000
```

> Infrastructure (PostgreSQL + Redis) is optional for local dev. The system uses SQLite and no-cache mode by default.

```bash
# Start full infrastructure when needed
docker compose up postgres redis -d
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/register` | Create account |
| `POST` | `/api/v1/auth/login` | Get JWT tokens |
| `POST` | `/api/v1/documents/upload` | Upload and index a file |
| `GET` | `/api/v1/documents/{id}/chunks` | Browse indexed chunks |
| `POST` | `/api/v1/chat/stream` | Streaming answer (SSE) |
| `POST` | `/api/v1/agent/stream` | Multi-agent streaming (SSE) |
| `POST` | `/api/v1/search/` | Semantic search, no LLM |
| `GET` | `/api/v1/traces/stats` | Token usage + latency stats |
| `GET` | `/api/v1/eval/results/latest` | Latest RAGAS scores |
| `GET` | `/health` | Subsystem health check |

Full interactive docs at `/docs` (Swagger UI).

---

## Configuration

See [`.env.example`](.env.example) for the complete reference with explanations.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | **Yes** | — | LLM provider key |
| `JWT_SECRET_KEY` | **Yes** | — | Token signing key |
| `DATABASE_URL` | No | SQLite | PostgreSQL for production |
| `REDIS_URL` | No | — | Enables caching + rate limits |
| `VECTOR_STORE_PROVIDER` | No | `chroma` | `chroma` or `pinecone` |
| `EMBEDDING_PROVIDER` | No | `huggingface` | `huggingface` or `openai` |
| `LOG_FORMAT` | No | `text` | `text` or `json` |

---

## Project Structure

```
nexus-ai/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/   # REST endpoints (auth, chat, docs, search, eval…)
│   │   ├── agents/             # LangGraph nodes (router, planner, researcher…)
│   │   ├── core/               # Auth, DB, cache, rate limiting, security guard
│   │   ├── middleware/         # Request ID tracing
│   │   ├── models/             # SQLAlchemy ORM (User, Document, Conversation, Trace…)
│   │   ├── rag/                # Pipeline, embeddings, retrieval, generation
│   │   └── services/           # Business logic (RAGService, TraceService…)
│   ├── eval/                   # RAGAS + custom metrics evaluation runner
│   └── tests/                  # pytest test suite (security, auth, CRUD)
├── frontend/src/app/(app)/
│   ├── chat/                   # Streaming chat with SSE
│   ├── dashboard/              # Document management + [documentId] KB explorer
│   └── observability/          # LLM usage dashboard
├── learning/
│   ├── concepts/               # 24 deep-dive concept guides (basics → production)
│   ├── daily/                  # Build logs for Days 1–17
│   ├── interview-prep/         # 230+ interview Q&As
│   └── resume/                 # ATS-ready resume bullets by day
├── docker-compose.yml
└── .github/workflows/ci.yml
```

---

## Learning Journal

The [`/learning`](./learning) directory is a complete study guide — written to replace external sources. Each concept guide covers basics through production patterns with code examples and interview Q&A.

**Concepts:** Embeddings · HNSW · RAG pipeline · Hybrid search · Reranking · HyDE · Multi-query · LangGraph · Structured outputs · JWT · Redis caching · Celery · Rate limiting · Security · RAGAS · CI/CD · Docker · React SSE · Observability · Vector databases

---

## Tech Stack

```
Backend    Python · FastAPI · LangChain · LangGraph · SQLAlchemy · Alembic · Celery
AI/ML      Groq (Llama 3.3-70B) · sentence-transformers · ChromaDB · Pinecone · RAGAS
Frontend   Next.js 15 · TypeScript · Tailwind CSS
Infra      PostgreSQL · Redis · Docker · GitHub Actions
```
