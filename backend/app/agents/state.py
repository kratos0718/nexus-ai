"""
AgentState — the single object that flows through every LangGraph node.

LangGraph passes this dict from node to node.
Each node reads what it needs and returns a partial dict to merge back in.
"""

import operator
from typing import Annotated, Optional

from typing_extensions import TypedDict


class AgentState(TypedDict):
    # Input fields (set before graph starts)
    question: str
    history: Optional[list[dict]]       # prior conversation turns for the LLM
    document_filter: Optional[dict]     # ChromaDB where-clause, e.g. {"document_id": "..."}

    # Set by router node
    route: str                          # "simple" | "complex"

    # Set by planner node (complex path only)
    sub_questions: list[str]

    # Set by rag or researcher node — all retrieved chunks
    # Annotated with operator.add so parallel nodes can MERGE their lists
    context: Annotated[list, operator.add]

    # Set by synthesizer node
    answer: str
    sources: list[dict]
    prompt_tokens: int
    completion_tokens: int
