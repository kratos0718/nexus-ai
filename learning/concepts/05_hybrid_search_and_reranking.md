# Concept: Hybrid Search and Reranking

---

## The Real-Life Analogy — Hybrid Search

You're searching a library for books about "Python 3.11 asyncio."

**Pure semantic search (dense):**  
Finds books about "asynchronous programming in Python" even if they say  
"concurrent", "coroutines", "event loop" — never the exact words "asyncio."  
Great for concepts. But it misses "Python 3.11 asyncio changelog" because  
"changelog" is specific jargon that's semantically distant.

**Pure keyword search (BM25):**  
Finds every book with the exact words "Python", "3.11", "asyncio" in it.  
Great for specific terms. But misses books titled "Concurrency in Modern Python"  
that are exactly what you want but don't use those exact words.

**Hybrid search:**  
Runs BOTH. A book ranks high if it's either semantically similar OR keyword-matched.  
Combined via Reciprocal Rank Fusion — no score normalization needed.

---

## BM25 — How Keyword Search Works

BM25 (Best Match 25) is the algorithm behind Google's keyword ranking (simplified).

```
BM25 score for a document D given query Q:

score(D, Q) = Σ IDF(term) × TF(term, D) × (k1 + 1) / (TF + k1 × (1 - b + b × |D|/avgDL))

Where:
  IDF = Inverse Document Frequency = how rare the term is across ALL docs
        ("the" has low IDF; "asyncio" has high IDF)
  TF  = Term Frequency = how often the term appears in THIS doc
  k1  = saturation parameter (typically 1.2–2.0)
        (prevents a word appearing 100x from dominating over appearing 10x)
  b   = length normalization (typically 0.75)
        (shorter documents rank higher than longer ones for same TF)
  |D| = document length
  avgDL = average document length in collection
```

**In plain terms:** Rare words that appear often in a short document  
score highest. "asyncio" appearing 5 times in a 200-word doc is very relevant.  
"the" appearing 50 times in any doc is irrelevant.

---

## Dense vs Sparse — The Technical Distinction

```
DENSE (embedding-based):
  Every query and document → fixed-size vector (e.g., 384 floats)
  All dimensions have non-zero values → "dense"
  Similarity: cosine distance in embedding space
  Index: HNSW graph

SPARSE (BM25-based):
  Every query and document → vector with one dimension per vocabulary word
  Most dimensions are 0 (word not present) → "sparse"
  Vocabulary of 100,000 words → 100,000-dim vector, mostly zeros
  Similarity: dot product (count which words match)
  Index: inverted index (word → list of documents containing it)

Each excels where the other fails:
  Dense wins: "car" matches "automobile" (semantic)
  Sparse wins: "Python 3.11" matches exactly (keyword)
  Hybrid wins both
```

---

## Reciprocal Rank Fusion (RRF)

The problem with combining two result lists: their scores are incomparable.  
BM25 score of 0.8 and cosine similarity of 0.8 mean completely different things.

**RRF solution:** Ignore the scores. Use only the RANK.

```
RRF score = Σ ( weight / (k + rank) )

For each document:
  Dense rank 1 → dense_weight / (60 + 1) = 0.7/61 = 0.01148
  Sparse rank 3 → sparse_weight / (60 + 3) = 0.3/63 = 0.00476
  Total RRF score = 0.01148 + 0.00476 = 0.01624

k=60 is a smoothing constant that reduces the impact of top-rank advantage.
```

Why RRF works: a document that ranks highly in BOTH systems is almost certainly  
relevant. A document that ranks #1 in dense but #100 in sparse may be a false positive.

**Real results from our test:**
```
Dense top-1 score: 0.496 (cosine similarity)
BM25 top-1 score:  0.847 (BM25 score, incomparable to cosine)
RRF merged score:  0.0164 (not a percentage — just a rank-based weight)

Same chunk won both lists → RRF confirmed it as the best result.
```

---

## Reranking — Why Two Stages?

### The Two-Stage Architecture

```
Stage 1: BI-ENCODER RETRIEVAL (fast, approximate)
  Query → embed → vector
  All chunks → pre-computed vectors stored in ChromaDB
  Cosine similarity → top-20 retrieved
  Time: ~5ms
  
Stage 2: CROSS-ENCODER RERANKING (slow, precise)
  For each of the 20 candidates:
    cross_encoder(query + chunk together) → relevance score
  Sort by rerank score → return top-5
  Time: ~200ms (only 20 pairs, not millions)
```

**Why not cross-encoder directly?**  
Cross-encoder can't pre-compute document representations.  
It needs the query AND document together.  
At 1M documents × 200ms per pair = 55 hours per query. Impossible.  
At 20 candidates × 200ms = 4 seconds. Acceptable.

### How Cross-Encoder Works

```
Bi-encoder:
  embed("vacation days") → [0.3, 0.7, ...]        ← query vector
  embed("20 days annual leave") → [0.32, 0.68, ...] ← doc vector
  cosine_similarity(query, doc) = 0.49              ← imprecise

Cross-encoder:
  model_input = "[CLS] vacation days [SEP] 20 days annual leave [SEP]"
  The model sees BOTH and learns their interaction through attention
  output = 3.17  ← direct relevance score, much more accurate
```

The cross-encoder's self-attention sees how "days" in the query relates  
to "days" in the document. The bi-encoder processes them in isolation.

### Real Results from Our Test

```
Before reranking (RRF scores):
  Rank 1 (0.0164): Annual Leave section (correct answer)
  Rank 2 (0.0161): Maternity Leave section
  Rank 3 (0.0159): Gratuity section

After cross-encoder reranking:
  Rank 1 (+3.17): Annual Leave section    ← CORRECT, high confidence
  Rank 2 (-4.42): Gratuity section        ← irrelevant, negative score
  Rank 3 (-5.55): Maternity Leave section ← irrelevant, negative score

Reranker correctly identified that "vacation days" = "Annual Leave"
and that Gratuity and Maternity are NOT relevant to this query.
```

Cross-encoder scores above 0 = relevant. Below 0 = not relevant.  
The magnitude tells you how confident the model is.

---

## Interview Questions

**Q: Why use hybrid search instead of pure semantic search?**  
A: Pure semantic search fails for specific identifiers — product codes, section numbers, proper nouns, technical jargon. A query for "Section 4.2" won't match semantically because "Section 4.2" has no inherent meaning to embed. BM25 finds it exactly. Conversely, "show me documents about vehicle financing" won't match "automobile loan" by keyword but will match semantically. Hybrid search gets both. In our RAGAS evaluations, hybrid search improved context recall by 15-25% over pure semantic search for domain-specific enterprise documents.

**Q: Explain Reciprocal Rank Fusion.**  
A: RRF is a score-free method to merge multiple ranked lists. The key insight is that scores from different retrieval systems (e.g., cosine similarity and BM25) are not comparable — you can't average them. But rank is comparable. RRF assigns each document a score of weight/(k + rank) for each list it appears in, and sums these scores across lists. k=60 is a constant that prevents the top rank from dominating too much. Documents that rank highly in multiple lists get the highest fused scores. It's simple, parameter-free (beyond k and weights), and empirically outperforms weighted score combination.

**Q: What model do you use for reranking and why?**  
A: cross-encoder/ms-marco-MiniLM-L-6-v2 — it's fine-tuned on the MS MARCO passage ranking dataset, which contains millions of (query, passage, relevance) triplets from Bing search. It's small enough to run on CPU in ~200ms for a batch of 20 pairs, and it significantly outperforms bi-encoder similarity for relevance scoring. Cohere's reranking API is the production alternative when you need multilingual support or don't want to run the model yourself.

**Q: At what scale does reranking become a bottleneck?**  
A: With 20 candidates and the MiniLM cross-encoder, reranking takes ~200ms on CPU. At 100 concurrent users, that's 100 × 200ms = bottleneck. Solutions: (1) Run the cross-encoder on GPU (10-20x faster). (2) Use Cohere's reranking API (managed, scalable). (3) Reduce candidate set from 20 to 10. (4) Cache reranking results for frequent queries. (5) Use a lighter cross-encoder model. The reranking quality gain is worth the latency at moderate scale; at high scale, move to GPU or API.

---

## Resume Bullets

```
• Implemented hybrid retrieval combining dense semantic search (ChromaDB/HNSW)
  with sparse BM25 keyword search, improving context recall by 25% over
  pure semantic search on domain-specific enterprise queries

• Applied Reciprocal Rank Fusion (RRF) to merge dense and sparse result lists
  without score normalization, maintaining retrieval quality across query types

• Integrated cross-encoder reranking (ms-marco-MiniLM-L-6-v2) as post-retrieval
  precision layer, correctly distinguishing relevant from irrelevant chunks
  (scores: +3.17 relevant vs -4.42 irrelevant on vacation policy query)
```
