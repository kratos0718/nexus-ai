# Day 14 — Advanced Retrieval: HyDE + Multi-query

## What we built

Two advanced retrieval techniques that improve answer quality without changing the LLM or the documents — by transforming the query itself before retrieval.

---

## Files created / modified

| File | Change |
|------|--------|
| `backend/app/services/query_processor.py` | NEW: HyDE and multi-query expansion |
| `backend/app/services/rag_service.py` | `query()` accepts `retrieval_mode` param |
| `backend/app/schemas/chat.py` | `retrieval_mode` field added to QueryRequest |
| `backend/app/api/v1/endpoints/chat.py` | Pass `retrieval_mode` through + fix bug |
| `learning/concepts/22_advanced_retrieval.md` | 8-level concept guide |

---

## The core insight

Standard RAG embeds the user's question and searches for close document chunks. The problem: questions and document chunks live in different regions of the embedding space. A question is interrogative; a chunk is declarative. Even when they're about the same topic, their embeddings aren't maximally close.

Both techniques bridge this gap in different ways.

---

## HyDE — Hypothetical Document Embeddings

```
User question: "What is the effect of chunk overlap?"

Step 1 — Generate hypothetical answer (LLM):
  "Chunk overlap controls how much text is shared between adjacent chunks.
   Higher overlap reduces information loss at chunk boundaries but increases
   storage and retrieval cost..."

Step 2 — Embed the HYPOTHETICAL (not the question)
Step 3 — Search vector store against hypothetical embedding
Step 4 — Generate answer using REAL retrieved chunks (not hypothetical)
```

The hypothetical is just a retrieval vehicle — it's phrased like a document so it embeds near real document chunks. The LLM doesn't need to be right; it just needs to sound like the answer.

```python
# backend/app/services/query_processor.py
def hyde(self, question: str) -> str:
    prompt = (
        "Write a short factual paragraph (2–4 sentences) that directly answers "
        "the question below. Do not say you cannot answer. Write only the answer.\n\n"
        f"Question: {question}\n\nAnswer:"
    )
    raw = self.llm.invoke(prompt)
    return (raw.content if hasattr(raw, "content") else str(raw)).strip() or question
```

---

## Multi-query expansion

```
User question: "What is chunking in RAG?"

Step 1 — Generate variants (LLM):
  1. "What is chunking in RAG?"  (original)
  2. "How does document splitting work in retrieval systems?"
  3. "Why do we split text before indexing?"
  4. "What is text segmentation in RAG pipelines?"

Step 2 — Retrieve top-5 for EACH variant → up to 20 candidates
Step 3 — Deduplicate by chunk_id → remove duplicates
Step 4 — Rerank merged set against ORIGINAL question → top 5
Step 5 — Generate answer from top 5
```

Different phrasings surface different chunks. "Chunking" might miss chunks that use "text splitting". Multi-query catches all of them.

```python
def _retrieve_multiquery(self, pipeline, variants: list[str], where) -> list:
    seen: set[str] = set()
    merged: list = []
    for variant in variants:
        for chunk in pipeline._retrieve(variant, where=where):
            if chunk.chunk_id not in seen:
                seen.add(chunk.chunk_id)
                merged.append(chunk)
    # Rerank against ORIGINAL question (variants[0]), not any variant
    if pipeline.reranker and len(merged) > 1:
        return pipeline.reranker.rerank(variants[0], merged, top_k=pipeline.rerank_top_k)
    return merged[:pipeline.rerank_top_k]
```

---

## API usage

```bash
# Standard retrieval (default)
POST /api/v1/chat/query
{
  "question": "What is chunking?",
  "retrieval_mode": "standard"
}

# HyDE — generate hypothetical, embed that
POST /api/v1/chat/query
{
  "question": "What is chunking?",
  "retrieval_mode": "hyde"
}

# Multi-query — expand to 3 phrasings, merge
POST /api/v1/chat/query
{
  "question": "What is chunking?",
  "retrieval_mode": "multiquery"
}
```

The mode is also tracked in LLM traces as `trace_type: "rag_hyde"` or `"rag_multiquery"` — you can compare quality across modes in the `/traces/stats` endpoint.

---

## Service layer flow

```python
# rag_service.py — query() dispatches based on retrieval_mode
async def query(self, question, ..., retrieval_mode="standard"):
    pipeline = get_pipeline()
    processor = QueryProcessor(pipeline.generator.llm)

    if retrieval_mode == "hyde":
        hyde_text = await loop.run_in_executor(None, lambda: processor.hyde(question))
        result = pipeline.generator.generate(
            query=question,                          # original question for generation
            context_results=pipeline._retrieve(hyde_text),  # hypothetical for retrieval
        )
    elif retrieval_mode == "multiquery":
        variants = await loop.run_in_executor(None, lambda: processor.expand_queries(question))
        result = pipeline.generator.generate(
            query=question,
            context_results=self._retrieve_multiquery(pipeline, variants, where),
        )
    else:
        result = pipeline.query(question, where=where, history=history)
```

---

## Graceful fallbacks

Both techniques fall back to the original question on failure:

```python
# HyDE fallback
try:
    hypothetical = self.llm.invoke(prompt).content.strip()
    return hypothetical if hypothetical else question
except Exception:
    return question  # use original question for retrieval

# Multi-query fallback
try:
    variants = [line.strip() for line in response.split("\n") if line.strip()]
    return [question] + variants[:n]
except Exception:
    return [question]  # single query, standard retrieval
```

If the LLM call for query expansion fails (rate limit, timeout), the system degrades gracefully to standard retrieval. The user's query is never dropped.

---

## Bug fixed

The `/chat/query` endpoint had a pre-existing bug on the security validation line:
```python
# Before (broken — 'question' not defined yet)
question = security_guard.validate_question(question)

# After (correct)
question = security_guard.validate_question(request.question)
```

---

## When to use each mode

| Mode | Use when |
|------|----------|
| standard | Latency matters, questions are specific and keyword-rich |
| hyde | Short/vague questions, technical docs, "What is X?" style |
| multiquery | Broad questions, maximum recall needed, offline evaluation |

Both HyDE and multi-query add one LLM call (~200-500ms) before retrieval. Cache HyDE hypotheticals in production to eliminate repeat overhead.
