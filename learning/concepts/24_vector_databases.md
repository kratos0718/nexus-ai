# Vector Databases — From Zero to Production

## Why vector databases exist

A traditional database stores rows of structured data: name, age, salary. You query it with exact conditions: `WHERE age = 25`. This only works when you know exactly what you're looking for.

A vector database stores high-dimensional numerical vectors and finds the ones *most similar* to a query vector. You query it by *meaning*, not by exact match. This is what makes semantic search possible.

The challenge: if you have 1 million vectors of 384 dimensions each, finding the exact nearest neighbor requires computing the distance to all 1 million vectors — that's 384 million multiplications per query. At 1,000 queries/second, that's 384 billion operations per second. Too slow.

Vector databases solve this with **approximate nearest neighbor (ANN)** algorithms that find a *very close* neighbor in milliseconds, not minutes.

---

## Level 1: What is a vector and how is similarity measured?

A vector is a list of numbers. The sentence "The cat sat on the mat" might be represented as:
```
[0.12, -0.34, 0.87, 0.05, -0.92, ...]  # 384 numbers for all-MiniLM-L6-v2
```

Similar sentences have vectors that are close in this 384-dimensional space. Dissimilar sentences have vectors that are far apart.

**Distance metrics:**
- **Cosine similarity**: measures the angle between vectors, not their length. Range: -1 to 1 (1 = identical direction, -1 = opposite). Most common for text.
- **Euclidean (L2)**: straight-line distance in the vector space. Sensitive to vector magnitude.
- **Dot product**: similar to cosine but not normalized. Used when vector magnitude carries meaning.

For text embeddings from sentence-transformers, cosine similarity is the right choice. ChromaDB converts cosine *distance* (0 to 2) to cosine *similarity* (1 to -1) by computing `1 - distance`.

---

## Level 2: HNSW — the algorithm inside every modern vector DB

HNSW (Hierarchical Navigable Small World) is the algorithm used by ChromaDB, Pinecone, Weaviate, and Qdrant for approximate nearest neighbor search.

**The intuition:**
Imagine you're looking for a specific street in a city. You don't drive down every street. Instead:
1. Look at a map of the whole country → find the right region
2. Zoom into the state → find the right city
3. Navigate to the neighborhood
4. Walk to the specific house

HNSW works the same way. It builds a multi-layer graph:

```
Layer 2 (sparse, long-range):    A ————————— G ————————— Z
Layer 1 (medium):         A — C ——— G — L ——— Z
Layer 0 (dense, all nodes):  A-B-C-D-E-F-G-H-I-J-K-L-M...Z
```

**Searching for a query vector:**
1. Start at the top layer (Layer 2) — only a few nodes, navigate greedily toward the query
2. Drop to Layer 1 — more nodes, refine position
3. Drop to Layer 0 — all nodes, find the actual nearest neighbors

**Why approximate?** At each layer, greedy navigation may miss a slightly better path if local neighbors all point away from it. In practice, HNSW finds the true nearest neighbor ~99% of the time, which is good enough for semantic search.

**Key HNSW parameters:**
- `M`: max connections per node (higher = better recall, more memory)
- `ef_construction`: search breadth during index building (higher = better quality, slower indexing)
- `ef_search`: search breadth during queries (higher = better recall, slower queries)

---

## Level 3: ChromaDB vs Pinecone — when to use each

| | ChromaDB | Pinecone |
|---|---|---|
| Where it runs | In-process, on your server | Managed cloud service |
| API | Python library | REST/gRPC API |
| Setup | `pip install chromadb` | Account + API key + create index |
| Persistence | Local filesystem | Infinite cloud storage |
| Scale | ~1M vectors comfortably | Billions of vectors |
| Cost | Free (your compute) | Free tier + paid plans |
| BM25/hybrid | Must implement yourself | Built-in hybrid search (paid) |
| Fetch all vectors | Supported | Not supported |
| Serverless-friendly | No (needs filesystem) | Yes |
| Best for | Local dev, small-medium prod | Large scale, cloud deployment |

**The abstraction pattern used in Nexus AI:**
```python
class BaseVectorStore(ABC):
    @abstractmethod
    def upsert_chunks(self, chunks, embeddings, document_id) -> int: ...
    @abstractmethod
    def search(self, query_embedding, top_k, where) -> list[SearchResult]: ...
    @abstractmethod
    def delete_document(self, document_id) -> int: ...

class VectorStore(BaseVectorStore):     # ChromaDB implementation
    ...
class PineconeVectorStore(BaseVectorStore):  # Pinecone implementation
    ...
```

Switching from ChromaDB to Pinecone is one env var: `VECTOR_STORE_PROVIDER=pinecone`. All application code uses `BaseVectorStore` — it never knows which backend is active.

---

## Level 4: Metadata filtering

Vector search finds semantically similar documents. But you often need to *also* filter by structured properties:
- "Find chunks about deployment, but only from documents uploaded by user 42"
- "Find chunks about revenue, but only from Q3 2024 reports"

This is metadata filtering — combining vector similarity with exact-match conditions.

```python
# ChromaDB metadata filter
results = collection.query(
    query_embeddings=[embedding],
    n_results=5,
    where={"document_id": "doc_abc123"}   # metadata filter
)

# Pinecone metadata filter
results = index.query(
    vector=embedding,
    top_k=5,
    filter={"document_id": {"$eq": "doc_abc123"}}
)
```

**How it works internally:**
In ChromaDB, metadata is stored alongside each vector. During ANN search, the HNSW graph is traversed as normal, but candidates that don't match the metadata filter are discarded before being returned. The search may need to find more candidates internally to return `top_k` matching ones.

**Multi-tenant isolation in Nexus AI:**
Every chunk is stored with `document_id` in its metadata. User A's documents have different `document_id` values than User B's. Queries always filter by `document_id` when scoped to a document, ensuring users can only retrieve their own documents' chunks.

---

## Level 5: Indexing pipeline — how chunks get into the store

```
Document file (.pdf, .txt, .md)
    ↓
Loader (PyPDF, UnstructuredLoader)
    → raw text + page numbers

Text splitter (RecursiveCharacterTextSplitter)
    → chunks of 800 chars, 150 overlap
    → each chunk has: text, chunk_index, metadata

Embedder (all-MiniLM-L6-v2 or text-embedding-3-small)
    → 384-dim or 1536-dim vectors

Vector store upsert
    → ids: ["{doc_id}_chunk_0", "{doc_id}_chunk_1", ...]
    → embeddings: [[0.12, -0.34, ...], ...]
    → metadata: [{"document_id": "...", "chunk_index": 0, "source": "file.pdf"}, ...]
```

**Why store chunk text in metadata (Pinecone only)?**
Pinecone stores only vectors + metadata — it doesn't have a separate document storage. To return chunk text in search results, you must store the text in the metadata field. ChromaDB stores text separately via its `documents` parameter. This is a key architectural difference: Pinecone is a pure vector index, ChromaDB is a vector + document store.

---

## Level 6: The chunks endpoint — debugging RAG retrieval

A chunks browsing endpoint is invaluable for debugging. Common questions:
- "Why is the RAG system not finding X?" → look at the chunks → X isn't indexed
- "Why are these two topics getting confused?" → look at chunk boundaries → they're in the same chunk
- "Is my chunking strategy good?" → browse chunks → too short / too long / splitting badly

```
GET /documents/{document_id}/chunks?offset=0&limit=20

Response:
{
  "filename": "technical_spec.pdf",
  "total_chunks": 147,
  "chunks": [
    {
      "chunk_id": "doc123_chunk_0",
      "chunk_index": 0,
      "text": "This document describes the architecture of...",
      "page": 1,
      "char_count": 756
    },
    ...
  ]
}
```

**Pagination:** Don't return all chunks at once — a 200-page PDF might have 500+ chunks. Use offset/limit to paginate.

**Ordering:** Sort by `chunk_index` (document reading order), not insertion order or random. The user wants to see how the document was split, in sequence.

---

## Level 7: Pure retrieval search — separating retrieval from generation

Standard RAG: retrieve → generate. If the answer is wrong, is it a retrieval problem or a generation problem? Hard to tell.

A pure retrieval endpoint separates the two:
```
POST /search
{
  "query": "What is chunking?",
  "document_id": "doc123",
  "top_k": 5,
  "retrieval_mode": "standard"
}

Response: { "chunks": [{"text": "...", "score": 0.87}, ...] }
```

**Use cases:**
1. **Debugging**: run the query, see what chunks are retrieved — if the retrieved chunks don't contain the answer, the retrieval is wrong (try HyDE or multi-query). If they do contain the answer but the LLM gets it wrong, the generation is wrong (fix the prompt).
2. **Evaluation**: RAGAS `context_recall` measures whether retrieved chunks contain the ground truth — you can compute this manually using the search endpoint.
3. **UI exploration**: let users see why the system answered the way it did.
4. **Pre-retrieval auditing**: before deploying a new document, search for known questions and verify the right chunks are returned.

---

## Level 8: Production vector database considerations

### Index size and memory
HNSW is memory-resident — the entire index must fit in RAM for fast search. Rule of thumb:
- `dimension × 4 bytes × num_vectors = minimum RAM`
- 1M vectors × 384 dims × 4 bytes = 1.5 GB just for vectors (plus HNSW graph overhead ~2-4x)
- For 10M vectors, you need ~15-60 GB RAM

At this scale: use Pinecone (managed, scales automatically), or Qdrant/Weaviate with SSD-backed quantized indexes.

### Vector quantization
To reduce memory usage, quantize 32-bit floats to 8-bit integers (4x compression). Recall drops slightly (~1-2%) but memory drops 75%. Pinecone does this automatically in serverless mode.

### Multi-tenancy strategies
**Approach 1: Metadata filtering** (what Nexus uses) — all users share one index, filter by `user_id`. Simple, scales to thousands of users. Risk: one user's vectors can affect HNSW routing for others (rare in practice).

**Approach 2: Namespace isolation** (Pinecone namespaces) — separate partition per user/tenant. Stronger isolation, slightly more overhead. Good for enterprise with strict data boundaries.

**Approach 3: Separate indexes** — one index per tenant. Maximum isolation, very expensive. Only for high-value enterprise customers.

### Batch upsert
Always upsert in batches. Pinecone recommends ≤100 vectors per request. ChromaDB can handle larger batches but benefits from batching for large documents.

```python
batch_size = 100
for i in range(0, len(vectors), batch_size):
    index.upsert(vectors=vectors[i:i + batch_size])
```

### Deduplication on re-index
Use `upsert` (not insert) when indexing. Upsert = insert if ID doesn't exist, update if it does. If a document is re-indexed after editing, the old chunks at the same `chunk_id` are replaced rather than duplicated.

---

## Quick reference

| Term | Definition |
|------|------------|
| ANN | Approximate Nearest Neighbor — finds close-enough neighbors fast |
| HNSW | Algorithm for ANN — multi-layer graph, O(log n) search |
| Cosine similarity | Angle between vectors — most common for text |
| Metadata filtering | Combine vector search with exact-match conditions |
| Upsert | Insert if new, update if exists (prevents duplicate chunks) |
| Namespace | Pinecone's per-tenant partition within an index |
| Quantization | Compress 32-bit floats to 8-bit ints to save 75% memory |
| ef_search | HNSW search breadth — higher = better recall, slower |
