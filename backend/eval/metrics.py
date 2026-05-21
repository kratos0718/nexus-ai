"""
Custom lightweight metrics computed without an LLM call.
Used alongside RAGAS for fast, deterministic scoring.

These run instantly (no API calls) and complement RAGAS's LLM-graded metrics.
"""

import re
from typing import Optional


def keyword_coverage(answer: str, expected_topics: list[str]) -> float:
    """
    What fraction of expected_topics appear in the answer?
    Simple but useful as a sanity check — if coverage is 0, the answer is
    clearly off-topic regardless of what RAGAS says.

    Returns: 0.0 – 1.0
    """
    if not expected_topics:
        return 1.0
    answer_lower = answer.lower()
    hits = sum(1 for topic in expected_topics if topic.lower() in answer_lower)
    return round(hits / len(expected_topics), 3)


def answer_length_score(answer: str, min_words: int = 20, max_words: int = 400) -> float:
    """
    Penalizes answers that are too short (likely "I don't know") or
    too long (likely padding/hallucination dump).

    Returns: 1.0 if within range, scaled down outside range.
    """
    word_count = len(answer.split())
    if word_count < min_words:
        return round(word_count / min_words, 3)
    if word_count > max_words:
        return round(max_words / word_count, 3)
    return 1.0


def refused_answer(answer: str) -> bool:
    """
    Detect "I don't know" / refusal responses.
    Useful for measuring coverage gaps in the knowledge base.
    """
    refusal_phrases = [
        "i don't have that information",
        "i don't know",
        "i cannot find",
        "not in the provided",
        "not mentioned in",
        "no information available",
        "unable to find",
        "cannot answer",
    ]
    answer_lower = answer.lower()
    return any(phrase in answer_lower for phrase in refusal_phrases)


def source_count(sources: list[dict]) -> int:
    """Number of source chunks returned with the answer."""
    return len(sources)


def avg_source_score(sources: list[dict]) -> float:
    """Average relevance score of returned source chunks (0–1)."""
    if not sources:
        return 0.0
    scores = [s.get("score", 0) for s in sources]
    return round(sum(scores) / len(scores), 3)


def custom_score(
    answer: str,
    sources: list[dict],
    expected_topics: list[str],
    latency_ms: float,
    target_latency_ms: float = 5000,
) -> dict:
    """
    Compute all custom metrics for one eval case.
    Returns a dict suitable for JSON serialization.
    """
    coverage = keyword_coverage(answer, expected_topics)
    length_ok = answer_length_score(answer)
    refused = refused_answer(answer)
    latency_score = round(min(1.0, target_latency_ms / max(latency_ms, 1)), 3)

    # Composite: weighted average of coverage + length + latency
    composite = round(
        0.5 * coverage + 0.3 * length_ok + 0.2 * latency_score,
        3,
    )

    return {
        "keyword_coverage": coverage,
        "length_score": length_ok,
        "latency_score": latency_score,
        "is_refusal": refused,
        "source_count": source_count(sources),
        "avg_source_score": avg_source_score(sources),
        "composite_score": composite,
        "latency_ms": round(latency_ms, 1),
    }
