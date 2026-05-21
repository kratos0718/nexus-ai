"""
RAG Evaluation Runner.

Runs each EvalCase through the RAG pipeline, scores with:
  1. Custom metrics (keyword coverage, latency, source quality)  — instant
  2. RAGAS metrics (faithfulness, answer relevancy, context recall) — LLM-graded

Output: JSON report saved to eval/results/<timestamp>.json

Usage:
    cd backend
    python -m eval.runner                        # run all cases
    python -m eval.runner --skip-ragas           # custom metrics only (faster)
    python -m eval.runner --case 0               # run one specific case
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

from loguru import logger

from eval.dataset import EVAL_DATASET, EvalCase
from eval.metrics import custom_score


RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ── Pipeline access ───────────────────────────────────────────────────────────

def _get_pipeline():
    """Lazy import to avoid loading models until we actually run."""
    # Must set env vars before importing
    if not os.getenv("GROQ_API_KEY"):
        raise EnvironmentError(
            "GROQ_API_KEY not set. Export it before running:\n"
            "  export GROQ_API_KEY=your_key_here"
        )
    from app.services.rag_service import get_pipeline
    return get_pipeline()


# ── Single case evaluation ────────────────────────────────────────────────────

def evaluate_case(pipeline, case: EvalCase) -> dict:
    """Run one EvalCase through the pipeline and return scored result."""
    logger.info(f"Evaluating: '{case.question[:70]}'")

    t0 = time.monotonic()
    try:
        # Retrieve context chunks
        context_results = pipeline._retrieve(case.question)

        # Generate answer
        gen_result = pipeline.generator.generate(
            query=case.question,
            context_results=context_results,
        )
        latency_ms = (time.monotonic() - t0) * 1000

        answer = gen_result.answer
        sources = [
            {"source": r.metadata.get("source", ""), "score": r.score, "text": r.text[:300]}
            for r in context_results
        ]
        context_texts = [r.text for r in context_results]
        error = None

    except Exception as e:
        latency_ms = (time.monotonic() - t0) * 1000
        logger.error(f"Pipeline error for '{case.question[:50]}': {e}")
        answer = ""
        sources = []
        context_texts = []
        error = str(e)

    scores = custom_score(
        answer=answer,
        sources=sources,
        expected_topics=case.expected_topics,
        latency_ms=latency_ms,
    )

    return {
        "question": case.question,
        "ground_truth": case.ground_truth,
        "answer": answer,
        "context_texts": context_texts,
        "sources": sources,
        "custom_metrics": scores,
        "ragas_metrics": None,   # filled in later if RAGAS is run
        "error": error,
        "document_hint": case.document_hint,
    }


# ── RAGAS evaluation ──────────────────────────────────────────────────────────

def run_ragas(results: list[dict]) -> list[dict]:
    """
    Score results with RAGAS metrics.
    Requires GROQ_API_KEY (LLM judge) and sentence-transformers (embeddings).

    RAGAS metrics used:
      - Faithfulness: is the answer grounded in the retrieved context?
      - AnswerRelevancy: does the answer address the question?
      - ContextRecall: how much of ground_truth is covered by context?
    """
    try:
        from ragas import EvaluationDataset, SingleTurnSample, evaluate
        from ragas.metrics import Faithfulness, AnswerRelevancy, ContextRecall
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from langchain_groq import ChatGroq
        from langchain_community.embeddings import HuggingFaceEmbeddings
    except ImportError as e:
        logger.warning(f"RAGAS import failed: {e}. Skipping RAGAS metrics.")
        return results

    logger.info("Running RAGAS evaluation (requires LLM calls — may take a few minutes)...")

    # Configure RAGAS to use Groq instead of OpenAI
    groq_llm = LangchainLLMWrapper(
        ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model="llama-3.3-70b-versatile",
            temperature=0,
        )
    )
    hf_embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    )

    # Build RAGAS dataset from results that have actual answers
    samples = []
    valid_indices = []
    for i, r in enumerate(results):
        if r["error"] or not r["answer"] or not r["context_texts"]:
            continue
        samples.append(
            SingleTurnSample(
                user_input=r["question"],
                response=r["answer"],
                retrieved_contexts=r["context_texts"],
                reference=r["ground_truth"],
            )
        )
        valid_indices.append(i)

    if not samples:
        logger.warning("No valid samples for RAGAS evaluation.")
        return results

    try:
        dataset = EvaluationDataset(samples=samples)
        ragas_result = evaluate(
            dataset=dataset,
            metrics=[Faithfulness(), AnswerRelevancy(), ContextRecall()],
            llm=groq_llm,
            embeddings=hf_embeddings,
        )

        # Map scores back to result dicts
        scores_df = ragas_result.to_pandas()
        for df_idx, result_idx in enumerate(valid_indices):
            row = scores_df.iloc[df_idx]
            results[result_idx]["ragas_metrics"] = {
                "faithfulness": round(float(row.get("faithfulness", 0) or 0), 3),
                "answer_relevancy": round(float(row.get("answer_relevancy", 0) or 0), 3),
                "context_recall": round(float(row.get("context_recall", 0) or 0), 3),
            }

    except Exception as e:
        logger.error(f"RAGAS evaluation failed: {e}")

    return results


# ── Report ────────────────────────────────────────────────────────────────────

def build_report(results: list[dict]) -> dict:
    """Aggregate results into a summary report."""
    valid = [r for r in results if not r["error"]]
    n = len(valid)

    def avg(key_path: list[str]) -> float:
        vals = []
        for r in valid:
            obj = r
            for k in key_path:
                obj = obj.get(k) or {}
            if isinstance(obj, (int, float)):
                vals.append(obj)
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_cases": len(results),
        "successful_cases": n,
        "error_cases": len(results) - n,
        "custom_metrics_avg": {
            "keyword_coverage": avg(["custom_metrics", "keyword_coverage"]),
            "composite_score": avg(["custom_metrics", "composite_score"]),
            "avg_latency_ms": avg(["custom_metrics", "latency_ms"]),
            "refusal_rate": round(
                sum(1 for r in valid if r["custom_metrics"].get("is_refusal", False)) / max(n, 1),
                3,
            ),
        },
        "ragas_metrics_avg": None,
        "results": results,
    }

    # RAGAS averages (only if any results have RAGAS scores)
    ragas_results = [r for r in valid if r.get("ragas_metrics")]
    if ragas_results:
        report["ragas_metrics_avg"] = {
            "faithfulness": avg(["ragas_metrics", "faithfulness"]),
            "answer_relevancy": avg(["ragas_metrics", "answer_relevancy"]),
            "context_recall": avg(["ragas_metrics", "context_recall"]),
        }

    return report


def print_summary(report: dict) -> None:
    print("\n" + "=" * 60)
    print("NEXUS AI — RAG EVALUATION REPORT")
    print("=" * 60)
    print(f"Cases: {report['successful_cases']}/{report['total_cases']} successful")

    cm = report["custom_metrics_avg"]
    print(f"\nCustom Metrics (avg):")
    print(f"  Keyword Coverage : {cm['keyword_coverage']:.1%}")
    print(f"  Composite Score  : {cm['composite_score']:.1%}")
    print(f"  Avg Latency      : {cm['avg_latency_ms']:.0f} ms")
    print(f"  Refusal Rate     : {cm['refusal_rate']:.1%}")

    rm = report.get("ragas_metrics_avg")
    if rm:
        print(f"\nRAGAS Metrics (avg):")
        print(f"  Faithfulness     : {rm['faithfulness']:.3f}")
        print(f"  Answer Relevancy : {rm['answer_relevancy']:.3f}")
        print(f"  Context Recall   : {rm['context_recall']:.3f}")
    else:
        print("\nRAGAS metrics: not run (use --ragas flag to enable)")

    print("=" * 60 + "\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run RAG evaluation")
    parser.add_argument("--skip-ragas", action="store_true",
                        help="Skip RAGAS metrics (faster, no extra LLM calls)")
    parser.add_argument("--case", type=int, default=None,
                        help="Run only a single case by index")
    args = parser.parse_args()

    # Select cases
    cases = EVAL_DATASET
    if args.case is not None:
        cases = [EVAL_DATASET[args.case]]

    logger.info(f"Starting evaluation: {len(cases)} case(s)")
    pipeline = _get_pipeline()

    # Run custom evaluation
    results = [evaluate_case(pipeline, case) for case in cases]

    # RAGAS evaluation (optional)
    if not args.skip_ragas:
        results = run_ragas(results)

    # Build and save report
    report = build_report(results)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = RESULTS_DIR / f"eval_{ts}.json"
    report_path.write_text(json.dumps(report, indent=2))
    logger.info(f"Report saved: {report_path}")

    print_summary(report)
    return report


if __name__ == "__main__":
    main()
