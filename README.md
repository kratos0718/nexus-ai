# Nexus AI — Enterprise Multi-Agent RAG Intelligence Platform

> Transform any organization's documents into an intelligent, queryable knowledge base powered by multi-agent AI.

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-orange)](https://langchain-ai.github.io/langgraph)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## What is Nexus AI?

Nexus AI is a production-grade platform that enables organizations to:
- Upload any documents (PDF, DOCX, TXT, URLs, CSV)
- Build a semantic knowledge base automatically
- Ask complex natural language questions
- Receive accurate answers with source citations
- Powered by autonomous AI agents that research, cross-reference, and synthesize

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        NEXUS AI                              │
│                                                              │
│  ┌─────────────┐    ┌──────────────────────────────────┐    │
│  │  Next.js    │    │         FastAPI Backend            │    │
│  │  Frontend   │◄──►│  Auth │ Chat │ Documents │ Admin  │    │
│  │  (React +   │    └───────────────┬──────────────────┘    │
│  │   Tailwind) │                    │                        │
│  └─────────────┘         ┌──────────▼──────────┐            │
│                           │  LangGraph Agents   │            │
│                           │  Planner → Research │            │
│                           │  → Synthesis →      │            │
│                           │    Citation         │            │
│                           └──────────┬──────────┘            │
│                    ┌─────────────────┼─────────────────┐     │
│              ┌─────▼────┐    ┌───────▼──────┐  ┌───────▼───┐│
│              │ChromaDB/ │    │  PostgreSQL  │  │  Redis    ││
│              │Pinecone  │    │  (Users,     │  │  (Cache,  ││
│              │(Vectors) │    │   Docs, Chat)│  │   Queue)  ││
│              └──────────┘    └──────────────┘  └───────────┘│
└──────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | Next.js 15 + Tailwind + shadcn/ui | Chat UI, document management |
| Backend | FastAPI + Python 3.11 | REST API + WebSocket streaming |
| AI Orchestration | LangChain + LangGraph | RAG pipeline + multi-agent |
| LLM | Groq (Llama 3.3-70B) / OpenAI | Response generation |
| Embeddings | sentence-transformers (HuggingFace) | Semantic representation |
| Vector DB (dev) | ChromaDB | Local development |
| Vector DB (prod) | Pinecone | Production deployment |
| Database | PostgreSQL | Users, documents, chat history |
| Cache + Queue | Redis + Celery | Rate limiting, async processing |
| Monitoring | Langfuse + Loguru | LLM tracing, structured logs |
| Deployment | Docker + Railway | Containerized cloud deployment |
| CI/CD | GitHub Actions | Automated testing and deploy |

---

## Features

### Core RAG Pipeline
- Multi-format document ingestion (PDF, DOCX, TXT, CSV, URLs)
- Recursive chunking with configurable size and overlap
- Hybrid search: semantic (dense) + keyword (BM25 sparse)
- Cross-encoder reranking for precision
- Source citations with confidence scores
- Hallucination reduction through grounded generation

### Multi-Agent System (LangGraph)
- **Planner Agent**: Decomposes complex questions into sub-queries
- **Research Agent**: Parallel multi-hop retrieval across knowledge base
- **Synthesis Agent**: Combines and reconciles information
- **Citation Agent**: Maps every claim to source documents

### Production Features
- JWT authentication with refresh tokens
- Redis rate limiting (configurable per-user)
- Real-time streaming responses (WebSocket)
- Async document processing (Celery workers)
- LLM observability (Langfuse tracing)
- RAGAS evaluation pipeline
- AI guardrails and prompt injection protection
- Docker deployment with CI/CD

---

## Build Progress (25 Days)

| Phase | Days | Focus | Status |
|-------|------|-------|--------|
| 1 | 1–5 | RAG Foundation | 🟡 In Progress |
| 2 | 6–10 | LangChain + Agents | ⬜ Planned |
| 3 | 11–16 | Backend + Frontend | ⬜ Planned |
| 4 | 17–22 | Production + MLOps | ⬜ Planned |
| 5 | 23–25 | Deploy + Polish | ⬜ Planned |

---

## Getting Started

### Prerequisites
- Python 3.11+
- Docker + Docker Compose
- Groq API key (free at [console.groq.com](https://console.groq.com))

### Quick Start

```bash
# Clone
git clone https://github.com/kratos0718/nexus-ai.git
cd nexus-ai

# Environment setup
cp .env.example .env
# Add your GROQ_API_KEY to .env

# Start infrastructure (PostgreSQL + Redis + ChromaDB)
docker-compose up -d

# Backend
cd backend
conda create -n nexus-ai python=3.11 -y
conda activate nexus-ai
pip install -r requirements.txt
uvicorn app.main:app --reload

# Visit API docs
open http://localhost:8000/docs
```

---

## Learning Journal

Deep technical notes, concept explanations with real-world analogies,  
interview Q&A (100+ questions), and resume bullets are in the  
[`/learning`](./learning) directory — organized by day and concept.

- [`learning/daily/`](./learning/daily/) — Daily build logs
- [`learning/concepts/`](./learning/concepts/) — Deep concept explanations  
- [`learning/interview-prep/`](./learning/interview-prep/) — 100+ Q&As
- [`learning/resume/`](./learning/resume/) — ATS-ready resume bullets

---

*Stack: FastAPI · LangChain · LangGraph · ChromaDB · Pinecone · Next.js · PostgreSQL · Redis · Docker · Groq · HuggingFace · sentence-transformers · RAGAS · Langfuse*
