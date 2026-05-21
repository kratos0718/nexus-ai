# Advanced Retrieval — From Zero to Production

## The core problem with naive RAG retrieval

In a basic RAG system, you embed the user's question and search for the closest document chunks.

This has a hidden flaw: **questions and answers live in different parts of the embedding space.**

Think about it. A question looks like:
> "What are the effects of chunking on RAG quality?"

A document chunk looks like:
> "Chunking affects RAG quality significantly. Smaller chunks produce more precise retrieval because irrelevant surrounding context is excluded..."

Both are about the same topic, but they're phrased completely differently. One is interrogative, one is declarative. Their embeddings are similar but not identical — and in a large vector space, "similar but not identical" can mean the right chunk ranks 8th instead of 1st.

Advanced retrieval techniques close this gap.

---

## Level 1: Why does the embedding gap exist?

Neural embedding models are trained on pairs of similar texts. The model learns: "these two sentences are close in meaning, their vectors should be close."

But "close in meaning" is learned from data that's mostly sentence-sentence or paragraph-paragraph pairs. Questions paired with answers are less common in training data than answers paired with answers.

Result: a model embeddings "What is photosynthesis?" and "Photosynthesis is the process by which plants convert light..." as related, but not as close as "Photosynthesis converts sunlight to glucose" and "Plants use photosynthesis to produce energy from light."

This is the question-document embedding gap. It's inherent to how models are trained.

---

## Level 2: HyDE — Hypothetical Document Embeddings

**Core idea:** Don't embed the question. Generate a short hypothetical answer and embed THAT.

```
Standard:   embed("What is chunking?")                  → search
HyDE:       hypothetical = LLM("write an answer to: What is chunking?")
            embed(hypothetical)                          → search
```

The hypothetical answer is written in "document style" — declarative, factual. It lives in the same part of the embedding space as real document chunks.

**Why it works:**
- The hypothetical may not be factually correct (the LLM doesn't have the document)
- But it IS phrased like a document
- So its embedding is closer to real document embeddings than the question's embedding is
- You retrieve against the hypothetical, then generate the answer from the REAL retrieved context

**The trick:** The hypothetical's role is purely to improve the retrieval embedding. You still answer using real retrieved context — not the hypothetical itself.

```python
def hyde(self, question: str) -> str:
    prompt = (
        "Write a short factual paragraph (2–4 sentences) that directly answers "
        "the question below. Do not say you cannot answer.\n\n"
        f"Question: {question}\n\nAnswer:"
    )
    hypothetical = self.llm.invoke(prompt).content.strip()
    return hypothetical  # embed THIS, not the question

# Usage:
hyde_text = processor.hyde(question)
chunks = pipeline._retrieve(hyde_text)       # retrieve against hypothetical
answer = generator.generate(question, chunks) # answer from real chunks
```

**When HyDE helps most:**
- Factual questions where the answer is declarative ("What is X?", "How does Y work?")
- Technical documentation where question style differs sharply from document style
- Short, keyword-light questions ("chunk size?") that don't contain enough signal for embedding

**When HyDE doesn't help:**
- Conversational queries where the question is already answer-like
- Very long questions with lots of context
- When the LLM hallucinates wildly in the hypothetical (bad embedding)

---

## Level 3: Multi-query expansion

**Core idea:** Ask the question in multiple ways. Retrieve for each. Merge results.

```
User asks: "What is chunking in RAG?"

Variants:
  1. "What is chunking in RAG?" (original)
  2. "How does document splitting work in retrieval systems?"
  3. "Why do we split text before indexing for RAG?"
  4. "What is the purpose of text segmentation in RAG pipelines?"

Retrieve top-5 for each → 20 candidates → deduplicate → rerank top-5 → generate
```

**Why it works:**
Different phrasings activate different vocabulary in the vector space. "Chunking" might match different chunks than "text splitting" or "document segmentation" — even if they mean the same thing. Multi-query catches chunks that a single phrasing would miss.

```python
def expand_queries(self, question: str, n: int = 3) -> list[str]:
    prompt = (
        f"Generate {n} alternative ways to phrase the following question. "
        "Each phrasing should have different wording but the same intent. "
        "Return ONLY the questions, one per line.\n\n"
        f"Question: {question}"
    )
    variants = self.llm.invoke(prompt).content.strip().split("\n")
    return [question] + [v.strip() for v in variants if v.strip()][:n]

# Usage:
variants = processor.expand_queries(question)       # [original, v1, v2, v3]
all_chunks = []
seen = set()
for variant in variants:
    for chunk in pipeline._retrieve(variant):
        if chunk.chunk_id not in seen:
            seen.add(chunk.chunk_id)
            all_chunks.append(chunk)
# Rerank the merged set against the ORIGINAL question
final = reranker.rerank(question, all_chunks, top_k=5)
```

**Deduplication is critical.** If "chunking" and "text splitting" both retrieve the same chunk, you count it once. Without deduplication, the same chunk appears multiple times with potentially different scores.

**Rerank on original.** After merging, rerank against the original question — not any variant. The variants were for retrieval breadth; the reranker should score relevance to what the user actually asked.

---

## Level 4: Comparison of techniques

| | Standard | HyDE | Multi-query |
|---|---|---|---|
| LLM calls | 0 extra | 1 extra | 1 extra |
| Latency | baseline | +200-500ms | +200-500ms |
| Best for | general | factual Q&A | ambiguous/broad |
| Weakness | question-doc gap | hallucinated hypothetical | slow on large top-k |
| Result quality | baseline | +15-25% (factual) | +10-20% (ambiguous) |

These are approximate improvements on domain-specific benchmarks — actual gains depend heavily on your documents and questions.

**In practice:** Offer all three as a user-selectable mode. Default to standard. Power users or automated pipelines can select HyDE or multi-query for specific use cases.

---

## Level 5: Retrieval fusion — combining multiple rankings

When you have results from multiple queries (multi-query) or multiple retrieval methods (dense + sparse), you need to merge them into one ranked list.

**Reciprocal Rank Fusion (RRF):**
Score each document based on its rank in each list, then sum scores across lists.

```python
def reciprocal_rank_fusion(rankings: list[list], k: int = 60) -> list:
    scores: dict[str, float] = {}
    docs: dict[str, any] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking):
            chunk_id = doc.chunk_id
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (k + rank + 1)
            docs[chunk_id] = doc
    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [docs[cid] for cid in sorted_ids]
```

RRF is rank-based, not score-based — so it works even when dense and sparse scores are on different scales (cosine similarity vs BM25 score). This is why it's preferred over naive score averaging.

---

## Level 6: Other advanced retrieval techniques

### Step-back prompting
Generate a more general version of the question, retrieve for both specific and general.
- User: "Why does chunking overlap matter?"
- Step-back: "How does chunking work in RAG?"
- Retrieve for both; the general query finds foundational context that the specific query might miss

### Parent-child chunking
Store documents in two granularities:
- Small chunks (200-300 chars) for precise retrieval
- Parent chunks (the full paragraph the small chunk came from) for context-rich generation
Retrieve small chunks → expand to parent chunks → generate

```
Index time:  split into small chunks (precise retrieval)
             map each small chunk → parent chunk id
Query time:  retrieve top-k small chunks by embedding
             fetch their parent chunks
             pass parent chunks to LLM (more context, less fragmentation)
```

### Contextual retrieval (Anthropic)
Before embedding each chunk, prepend a short summary generated by Claude:
> "This chunk is from a document about RAG systems. It describes the effects of chunk size on retrieval precision."
The enriched embedding captures document-level context that the raw chunk lacks.

### Self-querying retrieval
Let the LLM generate metadata filters from the question:
- User: "What did the Q3 2024 earnings report say about revenue?"
- LLM generates: `{"date": "Q3 2024", "doc_type": "earnings_report"}`
- Retrieval uses both the embedding AND metadata filter

---

## Level 7: When to use each mode

**Use standard when:**
- Latency is critical (real-time chat)
- Questions are already specific and keyword-rich
- Your documents and questions have similar vocabulary

**Use HyDE when:**
- Questions are short and keyword-light ("chunk overlap?")
- You're querying technical documentation
- Users ask "what is X?" style factual questions
- You need better retrieval without paying for more top_k

**Use multi-query when:**
- Questions are ambiguous or use unusual terminology
- You want maximum recall (don't want to miss relevant chunks)
- Running an evaluation pipeline where quality matters more than latency
- Users ask broad questions ("tell me about the document")

---

## Level 8: Production considerations

### Caching HyDE hypotheticals
The hypothetical for "What is chunking?" will always be roughly the same. Cache the HyDE-transformed query (not the final result) so repeated similar questions skip the LLM call:
```python
hyde_cache_key = f"hyde:{hash(question)}"
cached_hypothetical = redis.get(hyde_cache_key)
if not cached_hypothetical:
    hypothetical = processor.hyde(question)
    redis.setex(hyde_cache_key, 3600, hypothetical)
```

### Async multi-query retrieval
Instead of calling `_retrieve()` sequentially for each variant, run in parallel:
```python
import asyncio
tasks = [loop.run_in_executor(None, pipeline._retrieve, v) for v in variants]
results = await asyncio.gather(*tasks)
# flatten and deduplicate
```
This reduces multi-query latency from `n × retrieval_time` to `1 × retrieval_time`.

### A/B testing retrieval modes
Log the retrieval_mode with each trace. Compare:
- Average RAGAS faithfulness by mode
- User satisfaction (thumbs up/down) by mode
- Latency percentiles by mode

Use this data to decide which mode to enable by default for different query types.

### Retrieval mode routing
Build a classifier that automatically selects the mode based on the question:
- Short questions → HyDE
- Questions with "how", "why", "explain" → multi-query
- Specific factual questions with document identifiers → standard

---

## Quick reference

| Term | Definition |
|------|------------|
| HyDE | Generate hypothetical answer, embed that instead of the question |
| Multi-query | Expand to N phrasings, retrieve for each, merge and rerank |
| Embedding gap | Questions and answers embed differently even for the same topic |
| RRF | Reciprocal Rank Fusion — rank-based score merging across lists |
| Step-back prompting | Ask a more general question to retrieve foundational context |
| Parent-child chunking | Small chunks for retrieval, parent chunks for generation context |
| Contextual retrieval | Prepend AI-generated context summary to each chunk before embedding |
| Self-querying | LLM generates metadata filters from the user's question |
