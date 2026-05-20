# Day 1 — Project Setup, Architecture, First Embeddings

**Date:** 2026-05-20  
**Phase:** Foundation  
**Time spent:** ~3 hours  

---

## What I Built Today

- Complete project folder structure for Nexus AI
- Python conda environment (nexus-ai, Python 3.11)
- FastAPI application skeleton with config system
- HuggingFace embedding engine using all-MiniLM-L6-v2
- Tested real semantic similarity — dog/puppy = 0.54, dog/pizza = 0.009
- `.env.example` with Groq + HuggingFace setup (no OpenAI key needed)
- `docker-compose.yml` for PostgreSQL + Redis + ChromaDB
- README.md (portfolio quality)

---

## Concepts I Learned Today

### 1. What is an Embedding?

Text → list of numbers that captures meaning.  
Similar meaning → similar numbers → close in vector space.

Real example: "dog" and "puppy" → similarity 0.54.  
"dog" and "pizza" → similarity 0.009.

The model was pre-trained on billions of sentences and learned these  
relationships. That's what "pre-trained" means.

### 2. What is a Vector Database?

Stores embeddings. Finds the ones most similar to a query vector.  
Not exact matching (like SQL) — approximate semantic matching.

Like Spotify's "songs similar to this" — finding similarity in number-space.

### 3. What is RAG?

Like an open-book exam.  
- Without RAG: LLM answers from memory → can hallucinate
- With RAG: LLM first looks up your documents → grounded answers

### 4. Why Layered Architecture?

API layer (HTTP) → Service layer (business logic) → Data layer (DB)

Each layer has ONE job. You can test the service without HTTP.  
You can change the database without touching the API.  
This is the pattern used at every serious engineering company.

### 5. 12-Factor App (Config from Environment)

Never hardcode secrets in code. Always read from environment variables.  
Same code → different behavior in dev/staging/prod.  
With Pydantic Settings, the config is validated at startup.

### 6. Why Groq instead of OpenAI?

Groq is a hardware company that built custom chips (LPUs) for inference.  
250 tokens/second vs OpenAI's 50 tokens/second.  
Free tier: 14,400 requests/day.  
Uses the same API format as OpenAI → zero code change to switch.

---

## Code Patterns I Used

### Abstract Base Class (Provider Abstraction)
```python
class BaseEmbedder(ABC):
    @abstractmethod
    def embed_text(self, text: str) -> List[float]: ...
    
class HuggingFaceEmbedder(BaseEmbedder):
    def embed_text(self, text): ...  # implements it
    
class OpenAIEmbedder(BaseEmbedder):
    def embed_text(self, text): ...  # implements it differently
```
The rest of the code uses `BaseEmbedder` — never cares which one.

### Factory Pattern
```python
def get_embedder(provider: str) -> BaseEmbedder:
    if provider == "huggingface": return HuggingFaceEmbedder()
    if provider == "openai": return OpenAIEmbedder()
```
Change config → get different implementation. No code change in callers.

### Pydantic Settings (Config from .env)
```python
class Settings(BaseSettings):
    openai_api_key: str
    class Config:
        env_file = ".env"
```
Reads `OPENAI_API_KEY` from `.env` automatically. Validates type.

---

## Tools I Used Today

| Tool | What it does |
|------|-------------|
| conda | Python environment isolation per project |
| FastAPI | Async Python web framework, auto API docs |
| Pydantic | Data validation and settings management |
| sentence-transformers | HuggingFace library for local embeddings |
| loguru | Better Python logging (colors, structured) |
| ChromaDB | Local vector database |
| LangGraph | Multi-agent orchestration (will use in Week 2) |

---

## Results I Verified

```
Embedding Test Results:
  "dog sentence" vs "puppy sentence" → 0.5368 (HIGH ✅)
  "ML sentence"  vs "deep learning"  → 0.4251 (HIGH ✅)
  "dog sentence" vs "pizza"          → 0.0091 (LOW ✅)
  "dog sentence" vs "ML"             → 0.0587 (LOW ✅)

Embedding dimension: 384
Model: all-MiniLM-L6-v2
Provider: HuggingFace (local, free)
```

---

## Interview Questions I Can Answer Now

1. What is an embedding and why do we use them?
2. What is cosine similarity?
3. Why FastAPI over Flask?
4. What is the 12-Factor App methodology?
5. Explain the layered architecture pattern
6. What is the abstract factory pattern and when do you use it?
7. What is a vector database?
8. Explain RAG in simple terms

---

## What Confused Me / Need to Review

- [ ] HNSW algorithm details — read concepts/02_vector_databases.md
- [ ] Pydantic v2 validators (Field, model_validator) — will use tomorrow
- [ ] How ChromaDB persists data (in-memory vs disk)

---

## Tomorrow — Day 2

**Goal:** Build the complete document ingestion pipeline

1. Load real PDF files (PyPDF)
2. Implement chunking strategies (compare 3 types)
3. Connect ChromaDB (start Docker container)
4. Store first real document chunks
5. Run first semantic search on real data

**Setup needed:**
- Get Groq API key at console.groq.com (free, 2 minutes)
- Start Docker Desktop so ChromaDB runs
