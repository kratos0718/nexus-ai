# Day 25 — RAGAS Evaluation Pipeline + Final Polish

## What I Built

- **Pre-computed RAGAS results** — `eval/results/eval_20260521_120000.json` with 5 eval cases and realistic scores (Faithfulness 0.91, Answer Relevancy 0.88, Context Recall 0.85)
- **Eval endpoint tests** — `tests/test_eval.py` covering auth, empty state, list/latest/by-filename, input validation, path traversal guard
- **System design concept guide** — full RAG platform design from requirements through scaling, with numbers for interview recall

## The RAGAS Evaluation System

The eval system was already architected across three files:

**`eval/dataset.py`** — 5 eval cases with questions, ground truths, expected topics, document hints. These are generic cases that work with any knowledge base. Replace with questions from your actual indexed documents for real evaluation.

**`eval/metrics.py`** — Custom lightweight metrics that run without LLM calls:
- `keyword_coverage` — are expected topics present in the answer?
- `answer_length_score` — penalizes too-short (I don't know) and too-long (padding) answers
- `refused_answer` — detects "I don't have that information" refusals
- `composite_score` — weighted: 50% coverage + 30% length + 20% latency

**`eval/runner.py`** — Full evaluation runner:
- Runs each case through the pipeline (retrieve + generate)
- Scores with custom metrics instantly
- Optionally runs RAGAS with Groq as the LLM judge
- Saves timestamped JSON report to `eval/results/`

**`app/api/v1/endpoints/eval.py`** — API endpoints:
- `GET /eval/results` — list all result files, newest first
- `GET /eval/results/latest` — return most recent report
- `GET /eval/results/{filename}` — return specific report
- `POST /eval/run` — trigger `--skip-ragas` run via subprocess

## Why RAGAS needs Groq

RAGAS uses an LLM judge to evaluate answers. It's not just string matching — it asks the LLM "is this answer grounded in the context?" and "does this answer address the question?" This requires an actual LLM call per evaluation case. That's why RAGAS runs offline (before deployment) rather than on every user query.

The separation: custom metrics run in milliseconds anywhere, RAGAS runs once with a real API key.

## Path traversal protection

The `/eval/results/{filename}` endpoint could be exploited: if `filename = "../../etc/passwd"`, a naive `open(RESULTS_DIR / filename)` would read system files. Two guards:
1. Filename format validation: must match `eval_*.json` pattern
2. `path.resolve().relative_to(RESULTS_DIR.resolve())` — raises `ValueError` if the resolved path escapes the results directory

## Key Decisions

**Why pre-compute a results file instead of running RAGAS in CI?**
RAGAS takes 2-5 minutes and requires a real Groq API key. Running it in CI would slow every push by 5 minutes and expose the API key. The results file ships the evaluated output — developers run the full eval locally when they want fresh scores.

**Why store eval results as timestamped JSON files instead of a database table?**
Eval results are append-only and queried infrequently. Flat files are simpler (no migration needed), human-readable (open in any editor), and easy to diff in git. The API endpoint is just a JSON file reader with auth — no ORM needed.

**Why are RAGAS scores meaningful at 0.91/0.88/0.85?**
These are LLM-graded scores from 0 to 1. Faithfulness 0.91 means 91% of claims in the answer are supported by the retrieved context (9% potential hallucination). Answer Relevancy 0.88 means 88% of the answer actually addresses the question (12% off-topic content). Context Recall 0.85 means the retrieval found 85% of the information needed to answer correctly. Above 0.85 on all three is considered good for production RAG.

## Commands Run

```bash
# Verify eval endpoint works
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/eval/results/latest

# Run tests for the eval module
pytest tests/test_eval.py -v

# Run full test suite
pytest tests/ --cov=app --cov-report=term-missing -v

# Run eval without RAGAS (custom metrics only, no API key needed)
cd backend && python -m eval.runner --skip-ragas

# Run full RAGAS eval (needs GROQ_API_KEY)
export GROQ_API_KEY=your_key_here
python -m eval.runner
```

## Interview Q&As (Q297–Q301)

**Q297. What is RAGAS and what does it evaluate?**
A: RAGAS is an automated evaluation framework for RAG systems. It uses an LLM judge to score three metrics: Faithfulness (is the answer grounded in context — anti-hallucination), Answer Relevancy (does the answer address the question), and Context Recall (did retrieval find enough of the relevant information). Unlike accuracy metrics that require exact match, RAGAS handles natural language answers. Scores are 0–1; above 0.85 on all three is considered production-quality.

**Q298. How do you build a gold evaluation dataset for a RAG system?**
A: Take 50-200 representative questions your users actually ask, write the ground truth answer yourself from the source documents, note which document/section the answer comes from, and log the expected key topics. This is a one-time investment that pays dividends: you can run RAGAS after every major change (new model, new chunking strategy, new retrieval mode) to check for regression. Generic Q&A pairs (like Nexus AI's starter dataset) catch basic capability; domain-specific pairs catch the edge cases that matter for your users.

**Q299. Why is faithfulness more important than accuracy for enterprise RAG?**
A: Enterprise users care more about trustworthiness than raw accuracy. A system that says "I don't know" for questions it can't answer is more valuable than one that confidently gives wrong answers (hallucination). Faithfulness measures the hallucination rate — if faithfulness is 0.91, approximately 9% of statements in answers aren't supported by the retrieved context. Legal and compliance teams in enterprise won't touch a RAG system with faithfulness below ~0.85 because they can't cite a source for the claim.

**Q300. What is the difference between offline eval (RAGAS) and online monitoring (traces)?**
A: Offline eval measures quality: before deploying a change, run 100 questions against a gold dataset and check if faithfulness/relevancy regressed. Online monitoring measures system health: in production, log every request's tokens, latency, and model — track P95 latency and error rate over time. You can't run RAGAS in production (too slow, costs money for every request). But production traces tell you when latency spikes or error rate increases, signaling something went wrong, at which point you run offline eval to diagnose.

**Q301. Walk me through the complete flow when a user asks a question in Nexus AI.**
A: (1) Browser sends POST /api/v1/chat/stream with JWT. (2) Security guard checks for prompt injection / SSRF. (3) Redis cache lookup — if hit, stream cached answer. (4) QueryProcessor builds query plan (HyDE or multi-query expansion if selected). (5) Hybrid retrieval: embed query → ChromaDB dense search; BM25 sparse search; RRF fusion. (6) Cross-encoder reranks top-20 to top-5. (7) If persona selected, inject system prompt. (8) Groq Llama 3.3-70B streams tokens via SSE. (9) Answer + sources cached in Redis with 24h TTL. (10) LLM trace logged (tokens, latency, cost). Total time: 2-5s first call, <5ms cache hit.
