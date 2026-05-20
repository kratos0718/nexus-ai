# Concept: Vector Databases

**Difficulty levels:** Beginner → Intermediate → Advanced  
**Real-life examples:** Yes  
**Interview questions:** 10 included  

---

## THE REAL-LIFE ANALOGY (Never Forget This)

Think about Spotify's "songs similar to this one" feature.

Spotify doesn't say "find songs with the same word in the title."  
It says "find songs that SOUND similar" — same energy, tempo, mood, instruments.

Each song gets analyzed and described with hundreds of numbers:  
`[tempo: 0.8, energy: 0.9, danceability: 0.7, acousticness: 0.1, ...]`

When you hit "find similar," Spotify searches billions of songs and returns  
the ones whose numbers are closest to your song's numbers.

**That database of song-number-lists = a vector database.**  
**ChromaDB, Pinecone, Weaviate = different companies building this for text.**  

The difference from a regular database:
- Regular DB: "find rows WHERE genre = 'rock' AND year = 2020" (exact match)
- Vector DB: "find items CLOSEST IN MEANING to this query" (fuzzy semantic match)

---

## BEGINNER EXPLANATION

A vector database stores **embeddings** (lists of numbers representing meaning)  
and can quickly find the ones most similar to a new query.

```
Regular Database (PostgreSQL):
┌─────┬──────────┬──────┐
│ id  │ text     │ year │
├─────┼──────────┼──────┤    Query: WHERE year = 2020
│  1  │ "cats"   │ 2019 │    → exact column matching
│  2  │ "dogs"   │ 2020 │    → returns row 2
└─────┴──────────┴──────┘

Vector Database (ChromaDB):
┌─────┬──────────┬──────────────────────────────┐
│ id  │ text     │ vector (384 numbers)          │
├─────┼──────────┼──────────────────────────────┤    Query: "pets"
│  1  │ "cats"   │ [0.2, 0.8, 0.1, ...]         │    → find closest vectors
│  2  │ "dogs"   │ [0.21, 0.79, 0.12, ...]      │    → returns rows 1 AND 2
│  3  │ "stocks" │ [0.9, 0.1, 0.7, ...]         │    → (both are similar to "pets")
└─────┴──────────┴──────────────────────────────┘
```

---

## INTERMEDIATE EXPLANATION

### What a Vector Database Actually Stores

Each entry (called a **document** or **chunk**) has three things:
1. **id** — unique identifier (UUID)
2. **vector** — the embedding (e.g., 384 floats)
3. **metadata** — extra info for filtering (filename, page number, date, etc.)
4. **text** — the original text (for returning to the user)

### The Search Process

```
QUERY: "What is the company's vacation policy?"
  ↓
1. Embed the query → [0.3, 0.7, 0.2, ...]
  ↓
2. Vector DB calculates cosine similarity against ALL stored vectors
  ↓
3. Returns TOP-K most similar (e.g., top 5)
  ↓
4. Results include: text + similarity score + metadata
  ↓
RESULTS:
  [0.92] "Employees receive 15 days of paid vacation per year..."
  [0.87] "Vacation requests must be submitted 2 weeks in advance..."
  [0.71] "Public holidays are in addition to vacation days..."
```

### Metadata Filtering (Hybrid Filter)

You can combine vector search WITH metadata filters:

```python
# Only search within documents uploaded by user_id=42
results = collection.query(
    query_embeddings=[query_vector],
    where={"user_id": "42"},     # metadata filter (exact match)
    n_results=5                   # top-5 semantically similar
)
```

This is like Spotify saying "find similar songs, but only from the 1990s."

### ChromaDB vs Pinecone — When to Use Which

| Feature | ChromaDB | Pinecone |
|---------|----------|---------|
| Setup | `pip install chromadb` | API key + cloud account |
| Cost | Free | Free tier, then paid |
| Where it runs | Your machine | Pinecone's cloud |
| Ops burden | You manage it | Fully managed |
| Scale | Millions of vectors | Billions of vectors |
| Best for | Development, small scale | Production |
| Persistence | Local files | Cloud (always available) |

**Strategy (what we do):** ChromaDB locally → Pinecone in production.  
Same Python interface, swap with one config change.

---

## ADVANCED EXPLANATION

### How HNSW Indexing Works (The Algorithm Inside Vector DBs)

**Problem:** You have 5 million vectors. A new query comes in.  
Brute force: compute cosine similarity with all 5M → 5M multiplications.  
At 384 dims each: 1.9 billion multiplications per query. Too slow.

**HNSW Solution:** Build a graph structure during insert time.

```
INSERTION PHASE (happens when you add documents):

Layer 2 (coarse):    A ─────────── E ─────────── I
                     |             |
Layer 1 (medium):    A ─── B ─── E ─── F ─── I
                     |     |     |     |
Layer 0 (fine):      A─B─C─D─E─F─G─H─I─J─K─L

Each new node connects to M nearest neighbors in EACH layer.
Higher layers: fewer nodes, longer range connections (fast travel).
Lower layers: all nodes, short range (precise search).
```

```
SEARCH PHASE (happens at query time):

1. Enter at Layer 2 (few nodes, quick scan)
   → find approximate best position
2. Drop to Layer 1 (more nodes)
   → refine position using local neighbors
3. Drop to Layer 0 (all nodes)
   → do exhaustive local search in small neighborhood
4. Return top-K results

Result: O(log n) time instead of O(n). 1000x faster.
```

Parameters you tune:
- `M` — connections per node (higher = better recall, more memory, slower insert)
- `ef_construction` — search width during index building (higher = better graph, slower build)
- `ef` — search width during query (higher = better recall, slower query)

### Distance Metrics — Which to Choose

```
Cosine Similarity:
  Best for: text embeddings (what we use)
  Why: captures semantic direction regardless of vector magnitude
  Formula: (A·B) / (|A|×|B|)

Euclidean Distance (L2):
  Best for: image embeddings, spatial data
  Why: actual geometric distance in vector space
  Formula: √(Σ(Aᵢ-Bᵢ)²)

Dot Product:
  Best for: when vectors are normalized (same as cosine then)
  Why: fastest computation (no normalization needed)
  Formula: Σ(Aᵢ×Bᵢ)
```

### Chunking Strategy Effect on Vector DB Performance

The quality of what you store determines retrieval quality:

```
BAD CHUNKING (too small):
Chunk: "the company"
→ embedding is nearly meaningless, retrieval will fail

BAD CHUNKING (too large):
Chunk: [entire 50-page document]
→ embedding averages out everything, loses specific information
"What is the return policy?" retrieves a chunk that contains
return policy + hiring + benefits + office hours — LLM gets confused

GOOD CHUNKING:
Chunk: [one coherent concept, 200-500 words]
→ embedding captures ONE idea clearly
→ semantic search finds it precisely
→ LLM gets focused, relevant context
```

---

## IN OUR PROJECT (NEXUS AI)

```python
# Day 3 code preview — how we'll use ChromaDB

import chromadb
from chromadb.config import Settings

# Connect to local ChromaDB
client = chromadb.HttpClient(host="localhost", port=8001)

# Create a collection (like a table, but for vectors)
collection = client.get_or_create_collection(
    name="nexus_documents",
    metadata={"hnsw:space": "cosine"}   # use cosine similarity
)

# Store a document chunk
collection.add(
    ids=["chunk_001"],
    embeddings=[[0.2, 0.8, 0.1, ...]],   # 384-dim vector
    documents=["Employees get 15 vacation days per year"],
    metadatas=[{"file": "hr_policy.pdf", "page": 3, "user_id": "42"}]
)

# Retrieve similar chunks
results = collection.query(
    query_embeddings=[[0.25, 0.77, 0.12, ...]],  # embedded query
    n_results=5,
    where={"user_id": "42"}   # only search this user's docs
)
```

---

## INTERVIEW QUESTIONS

### Level 1 — Screening

**Q1: What is a vector database and how is it different from PostgreSQL?**  
A: A regular database like PostgreSQL stores structured data and searches by exact matching — "find rows where column equals value." A vector database stores high-dimensional vectors (embeddings) and searches by similarity — "find vectors closest to this query vector." The underlying data structure and algorithms are fundamentally different. PostgreSQL uses B-trees for indexes; vector databases use approximate nearest neighbor algorithms like HNSW or IVF. In Nexus AI, we use PostgreSQL for users, documents, and chat history (structured data), and ChromaDB/Pinecone for the document embeddings (semantic search).

**Q2: What is a collection in ChromaDB?**  
A: A collection in ChromaDB is analogous to a table in SQL. It holds a set of documents, their embedding vectors, and metadata. You can have multiple collections — for example, one per user's knowledge base, or one per document category. ChromaDB handles HNSW index creation automatically per collection.

**Q3: Why can't we just use PostgreSQL with a vector column for everything?**  
A: PostgreSQL does have the `pgvector` extension which adds vector similarity search. For smaller datasets (under 1M vectors), pgvector is excellent — it avoids running a separate service. However, dedicated vector databases like Pinecone are purpose-built for ANN search at scale — they have better performance at 100M+ vectors, built-in replication, and managed infrastructure. In production, the choice depends on scale: pgvector for simpler architectures, Pinecone/Weaviate when you need to scale vector search independently.

### Level 2 — Technical

**Q4: How does HNSW differ from IVF (Inverted File Index)?**  
A: IVF clusters vectors into groups (like k-means) during indexing. At query time it only searches within the nearest cluster(s) — ignoring other clusters entirely. Fast, but can miss results that are just across a cluster boundary. HNSW builds a navigable graph across ALL vectors — it's more accurate (higher recall) but uses more memory. HNSW is generally preferred for higher recall; IVF-PQ (with product quantization) for extreme scale where memory is the bottleneck (e.g., billions of vectors on limited RAM).

**Q5: Explain metadata filtering in vector databases. What's the challenge?**  
A: Metadata filtering adds an exact-match condition to approximate similarity search. Challenge: naively filtering after ANN search means you might retrieve K results, apply the filter, and get 0 results (if all K happened to not match the filter). Solutions: (1) Pre-filter: only search within the filtered subset (slower index on filter column). (2) Post-filter with over-fetching: retrieve 10K results, then filter down to K. (3) Hybrid: partition the index by filter values (e.g., one sub-index per user). ChromaDB uses a combination approach. Pinecone has native metadata filtering built into the ANN search.

**Q6: What is the role of ef_construction and M parameters in HNSW?**  
A: `M` is the number of bidirectional connections each node has to its neighbors during construction. Higher M = better graph connectivity = higher recall = more memory. Typical: 16-64. `ef_construction` is the size of the dynamic candidate list during construction. Higher ef_construction = better graph quality = slower index building. Typical: 100-400. At query time, `ef` (or `ef_search`) controls accuracy vs speed — higher ef means checking more candidates before returning top-K, giving better recall at the cost of latency.

### Level 3 — System Design

**Q7: How would you handle multi-tenancy in your vector database? Different users' documents should never mix.**  
A: Three approaches: (1) **Metadata filter** — store `user_id` as metadata, always filter by it at query time. Simple, but metadata filtering can be slow at scale. (2) **Separate collections per user** — complete isolation, best performance, but creates management overhead with many users. (3) **Separate namespaces** (Pinecone feature) — like separate indexes in one service, efficient management + full isolation. For Nexus AI: metadata filtering at small scale (ChromaDB), namespaces in production (Pinecone). Always include user_id in every query — defense in depth.

**Q8: Your vector database is the bottleneck — 500ms retrieval latency. How do you fix it?**  
A: Diagnose first: (1) Is it index build vs query? Re-check HNSW parameters. (2) Is it network latency (for managed Pinecone)? Move compute closer (same cloud region). Then optimize: (3) **Caching** — cache the top results for frequent queries in Redis (many users ask the same questions). (4) **Pre-compute** — if certain documents are queried constantly, keep their top results warm in cache. (5) **Index tuning** — lower `ef` for faster but slightly less accurate retrieval, compensate with reranking. (6) **Sharding** — split the index across multiple vector DB instances, query in parallel. (7) **Dimensionality reduction** — use a smaller embedding model (384 vs 1536 dims) — 4x smaller vectors = faster search.

**Q9: How do you keep the vector database and the relational database in sync?**  
A: This is a distributed consistency problem. When a document is deleted from PostgreSQL, its chunks must also be deleted from ChromaDB/Pinecone. Solutions: (1) **Two-phase deletion** — mark deleted in PostgreSQL, then delete from vector DB, then confirm. If step 2 fails, a cleanup job retries. (2) **Event sourcing** — every document lifecycle event is on a Kafka/Redis stream. A consumer handles both DB and vector DB updates atomically. (3) **Soft deletes** — don't physically delete from vector DB immediately; mark chunks as "deleted" in metadata, filter them out from search. Periodic job physically removes them. (4) **Idempotent chunk IDs** — chunk IDs are deterministic (hash of doc_id + chunk_index), so re-indexing is safe to retry.

**Q10: Compare ChromaDB, Pinecone, Weaviate, and pgvector for a production RAG system.**  

| | ChromaDB | Pinecone | Weaviate | pgvector |
|--|--|--|--|--|
| Managed | Self-hosted | Fully managed | Both | Self-hosted |
| Scale | Millions | Billions | Billions | ~10M practical |
| Multi-modal | No | No | Yes | No |
| Hybrid search | Basic | Yes | Yes | Extension |
| Cost (10M vecs) | Server cost | ~$70/mo | Server/~$25/mo | Server cost |
| Best for | Dev/small | Production ML | Multimodal AI | Already using PG |

**My choice for Nexus AI**: ChromaDB (dev) → Pinecone (prod). Reason: zero friction locally, best managed service at scale, OpenAI/LangChain native integration, simple pricing.

---

## RESUME BULLETS

```
• Built multi-tenant vector database layer using ChromaDB (development) and
  Pinecone (production), with metadata filtering ensuring strict user data isolation

• Designed HNSW-indexed semantic search achieving sub-50ms query latency
  across 100K+ document chunks with configurable ef parameters

• Implemented provider-agnostic vector store abstraction enabling zero-code
  migration between ChromaDB and Pinecone based on deployment environment

• Architected vector DB + PostgreSQL synchronization with idempotent chunk IDs
  and soft-delete pattern ensuring consistency across distributed data stores
```
