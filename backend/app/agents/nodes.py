"""
Agent node functions — each is a pure function: AgentState → partial AgentState dict.

LangGraph merges the returned dict back into the full state.

Router and Planner use structured outputs (with_structured_output) so the LLM
returns a typed Pydantic model instead of free-text — no string parsing needed.
"""

import os
from typing import Literal
from loguru import logger
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.rag.retrieval.vector_store import SearchResult


def _get_llm(max_tokens: int = 512) -> ChatGroq:
    return ChatGroq(
        api_key=os.getenv("GROQ_API_KEY", ""),
        model="llama-3.3-70b-versatile",
        temperature=0.0,
        max_tokens=max_tokens,
    )


# ── Structured output schemas ─────────────────────────────────────────────────

class RouteDecision(BaseModel):
    """Schema for the router's classification output."""
    route: Literal["simple", "complex"] = Field(
        description="'simple' if the question requires direct lookup, "
                    "'complex' if it requires comparing or synthesizing multiple sections."
    )
    reasoning: str = Field(
        description="One sentence explaining the routing decision."
    )


class ResearchPlan(BaseModel):
    """Schema for the planner's sub-question decomposition."""
    sub_questions: list[str] = Field(
        description="2 to 4 targeted sub-questions that together answer the main question.",
        min_length=2,
        max_length=4,
    )


# ── Router ────────────────────────────────────────────────────────────────────

ROUTER_PROMPT = """Classify whether this question requires simple RAG retrieval or complex multi-step reasoning.

SIMPLE: Answer lives in one focused section. Single topic. Direct lookup.
COMPLEX: Requires comparing multiple sections, multi-hop reasoning, or synthesis across topics.

Question: {question}"""


def router_node(state: AgentState) -> dict:
    """
    Classifies query complexity using structured output.
    The LLM fills a RouteDecision schema — no string parsing needed.
    """
    logger.info(f"[Router] Classifying: '{state['question'][:60]}'")

    llm = _get_llm()
    # with_structured_output makes the LLM return a RouteDecision object
    structured_llm = llm.with_structured_output(RouteDecision)

    try:
        decision: RouteDecision = structured_llm.invoke(
            ROUTER_PROMPT.format(question=state["question"])
        )
        route = decision.route
        logger.info(f"[Router] → {route} | {decision.reasoning}")
    except Exception as e:
        # Fallback: if structured output fails, default to simple
        logger.warning(f"[Router] Structured output failed, defaulting to simple: {e}")
        route = "simple"

    return {"route": route}


# ── Planner ───────────────────────────────────────────────────────────────────

PLANNER_PROMPT = """You are a research planner. Break this complex question into 2-4 targeted sub-questions.

Each sub-question should be self-contained and target a different aspect.

Main question: {question}"""


def planner_node(state: AgentState) -> dict:
    """
    Decomposes a complex question using structured output.
    The LLM fills a ResearchPlan schema with a typed list of strings.
    """
    logger.info(f"[Planner] Decomposing: '{state['question'][:60]}'")

    llm = _get_llm()
    structured_llm = llm.with_structured_output(ResearchPlan)

    try:
        plan: ResearchPlan = structured_llm.invoke(
            PLANNER_PROMPT.format(question=state["question"])
        )
        sub_questions = plan.sub_questions[:4]
        logger.info(f"[Planner] → {len(sub_questions)} sub-questions: {sub_questions}")
    except Exception as e:
        logger.warning(f"[Planner] Structured output failed, using question as-is: {e}")
        sub_questions = [state["question"]]

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
