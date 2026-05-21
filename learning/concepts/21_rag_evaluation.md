# RAG Evaluation — From Zero to Production

## Why evaluation matters

You built a RAG system. It gives answers. But are the answers *good*?

Without evaluation you are flying blind. You cannot tell whether a change to chunk size made things better or worse. You cannot know if your cross-encoder reranker is actually helping. You cannot report quality metrics to stakeholders. You cannot catch regressions before users report them.

Evaluation turns "seems fine" into a number you can track.

---

## Level 1: What can go wrong in a RAG pipeline?

RAG has two stages: **retrieval** and **generation**. Each can fail independently.

**Retrieval failures:**
- Wrong chunks returned (semantic mismatch, bad embeddings)
- No relevant chunks found (coverage gap in the knowledge base)
- Right document retrieved but wrong chunk (bad chunking strategy)

**Generation failures:**
- Answer contradicts the retrieved context (hallucination)
- Answer ignores the question and regurgitates context verbatim
- Answer is correct but vague or incomplete

**Combined failures:**
- Retrieval is wrong → generation makes up an answer → looks confident
- Retrieval is right → generation adds "facts" not in the context

This is why you need separate metrics for retrieval quality and generation quality.

---

## Level 2: The three types of evaluation

### 1. Custom heuristic metrics (no LLM needed)

Fast, deterministic, zero API cost. Run in milliseconds.

- **Keyword coverage**: Are expected terms present in the answer?
- **Answer length**: Is the answer too short (refusal) or too long (padding)?
- **Refusal detection**: Did the system say "I don't know"?
- **Source count**: How many chunks were retrieved?
- **Avg source score**: Average similarity score of retrieved chunks

These are coarse signals. Good for catching obvious failures.

### 2. Reference-based metrics (compare to ground truth)

You have a human-written "correct" answer. Compare the model answer to it.

- **BLEU**: Counts n-gram overlaps. Designed for machine translation. Poor for long-form QA.
- **ROUGE**: Counts recall of n-grams. Better than BLEU but still n-gram matching.
- **BERTScore**: Compares semantic embeddings, not exact words. Better for paraphrases.

These metrics require a golden dataset — curated Q&A pairs where you wrote the answer.

### 3. LLM-as-judge metrics (no reference answer needed)

An LLM reads the question, answer, and context, then grades the answer. This is what RAGAS does.

- **Faithfulness**: Is every claim in the answer supported by the context?
- **Answer Relevancy**: Does the answer actually address the question?
- **Context Recall**: Does the retrieved context cover what the ground truth mentions?

These cost API calls but give nuanced scores close to human judgment.

---

## Level 3: RAGAS deep dive

RAGAS (Retrieval-Augmented Generation Assessment) is the standard evaluation framework for RAG systems. It was published in 2023 and has become the default for the field.

### What it measures

**Faithfulness** (0–1):
- Breaks the answer into atomic claims
- For each claim, asks the judge LLM: "Is this claim directly supported by the retrieved context?"
- Score = supported_claims / total_claims
- Low faithfulness = hallucination

**Answer Relevancy** (0–1):
- The judge generates N hypothetical questions that the answer seems to address
- Computes embedding similarity between those hypothetical questions and the actual question
- High similarity = the answer is on-topic
- Catches answers that are factually grounded but don't address the question

**Context Recall** (0–1):
- Compares the retrieved context against the ground truth answer
- Asks: "Does the context contain enough information to produce this ground truth?"
- Low recall = retrieval is missing key information

### The data format

RAGAS needs four fields per sample:

```python
SingleTurnSample(
    user_input="What is chunking?",              # the question
    response="Chunking splits documents...",     # your system's answer
    retrieved_contexts=["text from chunk 1", "text from chunk 2"],  # what was retrieved
    reference="Chunking is splitting...",        # human-written ground truth
)
```

### Running RAGAS with Groq (not OpenAI)

RAGAS defaults to OpenAI. To use Groq:

```python
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_groq import ChatGroq
from langchain_community.embeddings import HuggingFaceEmbeddings

groq_llm = LangchainLLMWrapper(
    ChatGroq(api_key="...", model="llama-3.3-70b-versatile", temperature=0)
)
hf_embeddings = LangchainEmbeddingsWrapper(
    HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
)

result = evaluate(
    dataset=EvaluationDataset(samples=samples),
    metrics=[Faithfulness(), AnswerRelevancy(), ContextRecall()],
    llm=groq_llm,
    embeddings=hf_embeddings,
)
```

The judge LLM should be the most capable model you have access to — you want an accurate judge. Using the same model you're evaluating creates bias.

---

## Level 4: Building a golden dataset

A golden dataset is a curated list of (question, ground_truth) pairs that become your eval benchmark.

### How to build one

**Step 1 — Identify representative documents:**
Pick 10-20 real documents from your knowledge base. Include edge cases: short docs, long docs, technical docs, docs with tables/lists.

**Step 2 — Write questions a user would actually ask:**
For each document, write 3-5 questions. Mix:
- Factual (single-hop): "What is the minimum chunk size?"
- Synthesis (multi-hop): "How do chunk size and overlap interact?"
- Edge cases: "What if the document has no relevant information?"

**Step 3 — Write ground truth answers by reading the document yourself:**
Do not use your RAG system to write ground truths — this creates circular validation. Read the source document and write what a correct answer looks like.

**Step 4 — Size:**
- Development: 5-20 cases (fast iteration)
- Staging: 50-100 cases (meaningful statistics)
- Production: 200-500 cases (catches regressions reliably)

### The data structure

```python
@dataclass
class EvalCase:
    question: str
    ground_truth: str
    expected_topics: list[str]   # for keyword coverage metric
    document_hint: str           # human label, not used in scoring
```

---

## Level 5: Designing the eval runner

The runner orchestrates the evaluation pipeline.

```
For each EvalCase:
    1. Run retrieval:   chunks = pipeline._retrieve(question)
    2. Run generation:  result = generator.generate(question, chunks)
    3. Measure latency: t_end - t_start
    4. Compute custom metrics (instant)
    5. Collect results

After all cases:
    6. Run RAGAS (batch — one LLM call per metric per sample)
    7. Map RAGAS scores back to individual results
    8. Build aggregate report
    9. Save JSON to eval/results/<timestamp>.json
```

**Why batch RAGAS at the end?** RAGAS makes multiple LLM calls per sample. Batching lets RAGAS handle retries, rate limiting, and parallelism internally.

**CLI design:**

```bash
python -m eval.runner                  # all cases, with RAGAS
python -m eval.runner --skip-ragas     # fast run, custom metrics only
python -m eval.runner --case 0         # single case debug
```

The `--skip-ragas` flag is critical for development — running 10 cases through RAGAS takes 2-5 minutes and costs API calls. Custom-only runs take seconds.

---

## Level 6: Interpreting results

### Score benchmarks

| Metric | Poor | OK | Good | Excellent |
|--------|------|----|------|-----------|
| Faithfulness | < 0.6 | 0.6–0.75 | 0.75–0.9 | > 0.9 |
| Answer Relevancy | < 0.7 | 0.7–0.8 | 0.8–0.9 | > 0.9 |
| Context Recall | < 0.6 | 0.6–0.75 | 0.75–0.9 | > 0.9 |
| Keyword Coverage | < 0.5 | 0.5–0.7 | 0.7–0.9 | > 0.9 |

### What low scores tell you

**Low faithfulness:**
- LLM is hallucinating — answering from training data, not retrieved context
- Fix: stronger system prompt ("only answer from provided context"), add cross-encoder reranking so context is more relevant

**Low answer relevancy:**
- LLM is retrieving correct chunks but generating off-topic answers
- Could also mean the question is ambiguous
- Fix: query rewriting, better system prompt, check if your eval questions are actually answerable

**Low context recall:**
- Retrieval is missing key information
- Fix: increase chunk count (top_k), reduce chunk size for more granular retrieval, improve embeddings

**Low keyword coverage:**
- Either retrieval failed or generation didn't use the context
- Check first: is the expected topic actually in any indexed document?

---

## Level 7: Eval in CI/CD

Running evaluation on every commit catches regressions before they reach users.

### The pipeline

```yaml
# .github/workflows/eval.yml
on:
  schedule:
    - cron: '0 2 * * *'  # 2am daily
  workflow_dispatch:       # manual trigger

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run evaluation
        run: python -m eval.runner --skip-ragas
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
      - name: Check quality gate
        run: python eval/check_gates.py  # fails CI if scores drop
```

### Quality gates

A quality gate is a threshold that must be met for CI to pass:

```python
# eval/check_gates.py
GATES = {
    "keyword_coverage": 0.70,
    "composite_score": 0.65,
}

report = json.loads(Path("eval/results/latest.json").read_text())
failed = []
for metric, threshold in GATES.items():
    actual = report["custom_metrics_avg"][metric]
    if actual < threshold:
        failed.append(f"{metric}: {actual:.3f} < {threshold}")

if failed:
    print("Quality gate failures:")
    for f in failed: print(f"  {f}")
    sys.exit(1)
```

This makes quality measurable and enforceable — not just a feeling.

### Regression detection

Store eval results over time. A 5% drop in faithfulness after a chunk-size change tells you the change was harmful even if individual answers "look fine" to human review.

---

## Level 8: Advanced eval patterns

### 1. Adversarial evaluation

Add deliberately hard cases:
- Questions not answerable from the knowledge base (should get refusals, not hallucinations)
- Ambiguous questions (tests query understanding)
- Questions about topics near the knowledge boundary

### 2. Per-document-type evaluation

Break your eval dataset by document type. Technical docs may score differently from narrative docs. This tells you where your chunking strategy is weakest.

### 3. Human-in-the-loop evaluation

For production systems: sample 1% of live queries, show them to a human reviewer who rates: relevant / irrelevant / partially relevant. Compare human ratings to automated RAGAS scores. Where they diverge, improve your automated metrics.

### 4. LLM panel judging

Instead of one judge LLM, use 2-3 different models and average their scores. Reduces bias from any one model's preferences. Expensive but more reliable.

### 5. Component-level ablation

Evaluate each component independently:
- Retrieval only: compare retrieved chunks to ground truth (context recall)
- Generation only: give the LLM the perfect context and measure faithfulness
- End-to-end: full pipeline

This isolates whether a score improvement came from better retrieval or better generation.

### 6. Sensitivity analysis

Systematically vary one parameter, hold others constant, measure eval score:
- chunk_size: [256, 512, 1000, 2000] → plot faithfulness vs chunk_size
- top_k: [3, 5, 10, 20] → plot context_recall vs top_k
- temperature: [0, 0.3, 0.7, 1.0] → plot faithfulness vs temperature

This produces empirical evidence for parameter choices, not just intuition.

### 7. Continuous evaluation with sampling

In production: capture 5% of live queries (with consent/anonymization). Feed them through your golden evaluator nightly. Alert if scores drop more than 10% week-over-week. This catches data drift (new document types added, user query patterns shifting) before users complain.

---

## Quick reference

| Term | Definition |
|------|------------|
| RAGAS | Retrieval-Augmented Generation Assessment — eval framework |
| Faithfulness | Claims in answer supported by context (0–1) |
| Answer Relevancy | Answer addresses the question (0–1) |
| Context Recall | Retrieved context covers ground truth (0–1) |
| LLM-as-judge | Using an LLM to score another LLM's output |
| Golden dataset | Curated Q&A pairs used as eval benchmark |
| Quality gate | Minimum score threshold required for CI pass |
| Ablation | Removing one component to measure its individual contribution |
| Data drift | Distribution shift in real queries vs. eval dataset over time |
