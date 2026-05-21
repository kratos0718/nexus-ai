# Day 13 — RAG Evaluation Pipeline

## What we built

A complete evaluation system for the RAG pipeline with two layers of metrics — instant custom heuristics and LLM-graded RAGAS scores — plus API endpoints to view results without touching the terminal.

---

## Files created / modified

| File | Change |
|------|--------|
| `backend/eval/__init__.py` | Package marker |
| `backend/eval/dataset.py` | 5 EvalCase objects with ground truths |
| `backend/eval/metrics.py` | Custom metrics: keyword coverage, length, refusal, composite |
| `backend/eval/runner.py` | End-to-end eval runner with RAGAS integration |
| `backend/app/api/v1/endpoints/eval.py` | REST endpoints to view eval results |
| `backend/app/api/v1/router.py` | Registered `/eval` router |
| `learning/concepts/21_rag_evaluation.md` | 8-level concept guide |

---

## Architecture

```
EVAL DATASET (5–200 EvalCase objects)
    ↓
RUNNER (eval/runner.py)
    ├── For each case:
    │       pipeline._retrieve(question)     → context chunks
    │       generator.generate(question, ...) → answer
    │       custom_score(...)                 → instant metrics
    │
    ├── After all cases:
    │       RAGAS evaluate(...)               → LLM-graded metrics
    │
    └── build_report() → eval/results/eval_<timestamp>.json

API ENDPOINTS (app/api/v1/endpoints/eval.py)
    GET  /eval/results         → list result files
    GET  /eval/results/latest  → view newest report
    GET  /eval/results/{name}  → view specific report
    POST /eval/run             → trigger custom-only run
```

---

## Custom metrics (eval/metrics.py)

These run in milliseconds with zero API calls:

```python
# keyword_coverage: what fraction of expected_topics appear in the answer?
keyword_coverage("RAG uses vector databases", ["vector", "retrieval"])
# → 0.5  (only "vector" matched, not "retrieval")

# answer_length_score: penalizes too-short or too-long answers
answer_length_score("yes", min_words=20)  # → 0.067 (1/15 words)
answer_length_score("word " * 500)        # → 0.8   (400/500 max)

# refused_answer: detects "I don't know" responses
refused_answer("I cannot find information about this topic")  # → True

# composite: weighted average
composite = 0.5 * coverage + 0.3 * length_score + 0.2 * latency_score
```

---

## RAGAS metrics (eval/runner.py → run_ragas())

These require LLM calls (2-5 min for 10 cases):

```python
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.metrics import Faithfulness, AnswerRelevancy, ContextRecall

samples = [
    SingleTurnSample(
        user_input=r["question"],
        response=r["answer"],
        retrieved_contexts=r["context_texts"],
        reference=r["ground_truth"],
    )
    for r in results
]

result = evaluate(
    dataset=EvaluationDataset(samples=samples),
    metrics=[Faithfulness(), AnswerRelevancy(), ContextRecall()],
    llm=groq_llm,           # Groq as judge (not OpenAI)
    embeddings=hf_embeddings,
)
```

---

## Running evaluation

```bash
cd backend

# Full eval with RAGAS (2-5 min, requires GROQ_API_KEY)
python -m eval.runner

# Fast run — custom metrics only, no LLM calls (seconds)
python -m eval.runner --skip-ragas

# Debug one specific case
python -m eval.runner --case 0 --skip-ragas
```

Result saved to: `eval/results/eval_YYYYMMDD_HHMMSS.json`

---

## Eval API endpoints

After running the evaluator, view results via the API without needing terminal access:

```bash
# List all result files
GET /api/v1/eval/results

# View the most recent report
GET /api/v1/eval/results/latest

# View a specific run
GET /api/v1/eval/results/eval_20260521_143022.json

# Trigger a quick eval run (custom metrics only)
POST /api/v1/eval/run
```

All endpoints require JWT auth — they read from `eval/results/` which is on the backend filesystem.

---

## JSON report structure

```json
{
  "timestamp": "2026-05-21T14:30:22+00:00",
  "total_cases": 5,
  "successful_cases": 5,
  "error_cases": 0,
  "custom_metrics_avg": {
    "keyword_coverage": 0.82,
    "composite_score": 0.79,
    "avg_latency_ms": 1243.0,
    "refusal_rate": 0.0
  },
  "ragas_metrics_avg": {
    "faithfulness": 0.91,
    "answer_relevancy": 0.88,
    "context_recall": 0.85
  },
  "results": [
    {
      "question": "What is RAG?",
      "ground_truth": "RAG combines retrieval...",
      "answer": "RAG (Retrieval-Augmented Generation)...",
      "context_texts": ["chunk 1 text", "chunk 2 text"],
      "sources": [{"source": "doc.pdf", "score": 0.87, "text": "..."}],
      "custom_metrics": {
        "keyword_coverage": 1.0,
        "length_score": 1.0,
        "latency_score": 0.94,
        "is_refusal": false,
        "source_count": 5,
        "avg_source_score": 0.82,
        "composite_score": 0.89,
        "latency_ms": 1134.2
      },
      "ragas_metrics": {
        "faithfulness": 0.92,
        "answer_relevancy": 0.89,
        "context_recall": 0.87
      },
      "error": null,
      "document_hint": "AI/ML documentation"
    }
  ]
}
```

---

## Key concepts

**Why two layers of metrics?**
Custom metrics are free and instant — good for fast feedback loops. RAGAS is expensive but nuanced — good for reporting quality to stakeholders. You run custom metrics on every change; RAGAS once a day or before a release.

**Why Groq as judge?**
RAGAS defaults to OpenAI. We configured it to use Groq's llama-3.3-70b so evaluation is consistent with the rest of the stack and uses the same API key.

**Why save results to JSON?**
Results are immutable artifacts — you can compare today's run against last week's. JSON is readable by humans, parseable by scripts, viewable via the API, and importable into Pandas for analysis.

**Why `--skip-ragas`?**
10 RAGAS evaluations = ~30 LLM calls + embedding calls = 2-5 minutes. During development, you run `--skip-ragas` dozens of times a day. RAGAS runs weekly or before releases.

---

## Metrics interpretation cheat sheet

| Score | Faithfulness | Meaning |
|-------|-------------|---------|
| > 0.9 | Excellent | Answer is almost entirely grounded in context |
| 0.75–0.9 | Good | Minor unsupported claims |
| 0.6–0.75 | OK | Noticeable hallucination |
| < 0.6 | Poor | Significant hallucination — fix retrieval |

| Score | Context Recall | Meaning |
|-------|---------------|---------|
| > 0.85 | Excellent | Retrieval covers the answer well |
| 0.7–0.85 | Good | Minor coverage gaps |
| < 0.7 | Poor | Knowledge base gap or bad chunking |
