"""
Agent node functions — each is a pure function: AgentState → partial AgentState dict.

LangGraph merges the returned dict back into the full state.
"""

import os
from loguru import logger
from langchain_groq import ChatGroq

from app.agents.state import AgentState
from app.rag.retrieval.vector_store import SearchResult


# Shared LLM instance — lightweight calls (routing, planning) use a fast model
def _get_llm() -> ChatGroq:
    return ChatGroq(
        api_key=os.getenv("GROQ_API_KEY", ""),
        model="llama-3.3-70b-versatile",
        temperature=0.0,    # deterministic for routing and planning
        max_tokens=512,
    )


# ── Router ────────────────────────────────────────────────────────────────────

ROUTER_PROMPT = """Classify whether this question requires simple RAG retrieval or complex multi-step reasoning.

SIMPLE: The answer lives in one focused section of a document. Single topic. Direct lookup.
Examples:
- "What is the vacation policy?"
- "Who is the CEO?"
- "What does the contract say about termination?"

COMPLEX: Requires comparing multiple sections, multi-hop reasoning, or synthesizing across different topics.
Examples:
- "Compare the vacation policies across all three employment contracts."
- "What are the main differences between product A and product B, and which is better for enterprise use?"
- "How do the Q1 results relate to the strategic goals mentioned in the annual report?"

Question: {question}

Respond with ONLY one word: "simple" or "complex"."""


def router_node(state: AgentState) -> dict:
    """Classifies query complexity → routes to simple RAG or complex planning path."""
    logger.info(f"[Router] Classifying: '{state['question'][:60]}'")

    llm = _get_llm()
    response = llm.invoke(ROUTER_PROMPT.format(question=state["question"]))
    route = response.content.strip().lower().replace('"', "").replace("'", "")

    if route not in ("simple", "complex"):
        route = "simple"

    logger.info(f"[Router] → {route}")
    return {"route": route}


# ── Planner ───────────────────────────────────────────────────────────────────

PLANNER_PROMPT = """You are a research planner. Break this complex question into 2-4 targeted sub-questions.

Each sub-question should:
- Be self-contained (answerable on its own)
- Target a different aspect of the main question
- Be specific enough for document retrieval

Main question: {question}

Return ONLY the sub-questions, one per line. No numbering, no explanations."""


def planner_node(state: AgentState) -> dict:
    """Decomposes a complex question into 2–4 targeted sub-questions."""
    logger.info(f"[Planner] Decomposing: '{state['question'][:60]}'")

    llm = _get_llm()
    response = llm.invoke(PLANNER_PROMPT.format(question=state["question"]))

    sub_questions = [
        q.strip().lstrip("-•* ")
        for q in response.content.strip().split("\n")
        if q.strip()
    ][:4]  # cap at 4

    logger.info(f"[Planner] → {len(sub_questions)} sub-questions: {sub_questions}")
    return {"sub_questions": sub_questions}


# ── RAG node (simple path) ────────────────────────────────────────────────────

def rag_node(state: AgentState) -> dict:
    """
    Simple path: retrieve directly for the original question.
    Imports pipeline lazily to avoid circular imports.
    """
    from app.services.rag_service import get_pipeline

    logger.info(f"[RAG] Retrieving for: '{state['question'][:60]}'")
    pipeline = get_pipeline()
    results: list[SearchResult] = pipeline._retrieve(
        state["question"],
        where=state.get("document_filter"),
    )
    logger.info(f"[RAG] → {len(results)} chunks")
    return {"context": results}


# ── Researcher node (complex path) ───────────────────────────────────────────

def researcher_node(state: AgentState) -> dict:
    """
    Complex path: retrieve for each sub-question, deduplicate by chunk_id.
    Returns the union of all relevant chunks across all sub-questions.
    """
    from app.services.rag_service import get_pipeline

    pipeline = get_pipeline()
    seen_ids: set[str] = set()
    all_results: list[SearchResult] = []

    for sq in state.get("sub_questions", []):
        logger.info(f"[Researcher] Retrieving for sub-q: '{sq[:60]}'")
        results = pipeline._retrieve(sq, where=state.get("document_filter"))
        for r in results:
            if r.chunk_id not in seen_ids:
                seen_ids.add(r.chunk_id)
                all_results.append(r)

    logger.info(f"[Researcher] → {len(all_results)} unique chunks across all sub-questions")
    return {"context": all_results}


# ── Synthesizer ───────────────────────────────────────────────────────────────

def synthesizer_node(state: AgentState) -> dict:
    """
    Generates the final answer from the accumulated context.
    Uses the existing GroqGenerator so prompts and token counting stay consistent.
    """
    from app.services.rag_service import get_pipeline

    pipeline = get_pipeline()
    context = state.get("context", [])

    if not context:
        return {
            "answer": "I couldn't find relevant information to answer this question.",
            "sources": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    logger.info(f"[Synthesizer] Generating from {len(context)} chunks")

    result = pipeline.generator.generate(
        query=state["question"],
        context_results=context,
        history=state.get("history"),
    )

    sources = [
        {
            "chunk_id": r.chunk_id,
            "source": r.metadata.get("source", ""),
            "page": r.metadata.get("page"),
            "score": round(r.score, 4),
        }
        for r in context
    ]

    return {
        "answer": result.answer,
        "sources": sources,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
    }
