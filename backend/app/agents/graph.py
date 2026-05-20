"""
LangGraph state machine — assembles the agent nodes into a runnable graph.

Graph topology:

    START
      │
    [router] ─── route="simple"  ──► [rag]
      │                                 │
      └─── route="complex" ──► [planner] ──► [researcher]
                                               │
                                           [synthesizer]
                                               │
                                             END

Both the simple (rag) and complex (researcher) paths converge at synthesizer
before reaching END.
"""

from loguru import logger
from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.agents.nodes import (
    router_node,
    planner_node,
    rag_node,
    researcher_node,
    synthesizer_node,
)


def _route(state: AgentState) -> str:
    """Conditional edge: read state.route set by router_node."""
    return state.get("route", "simple")


def build_agent_graph():
    """Build and compile the multi-agent graph. Call once at startup."""
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("router",      router_node)
    graph.add_node("planner",     planner_node)
    graph.add_node("rag",         rag_node)
    graph.add_node("researcher",  researcher_node)
    graph.add_node("synthesizer", synthesizer_node)

    # Entry point
    graph.set_entry_point("router")

    # Router fans out to either simple or complex path
    graph.add_conditional_edges(
        "router",
        _route,
        {
            "simple":  "rag",
            "complex": "planner",
        },
    )

    # Complex path: planner → researcher → synthesizer
    graph.add_edge("planner",    "researcher")
    graph.add_edge("researcher", "synthesizer")

    # Simple path: rag → synthesizer
    graph.add_edge("rag",        "synthesizer")

    # Both paths end here
    graph.add_edge("synthesizer", END)

    compiled = graph.compile()
    logger.info("Agent graph compiled: router → [rag | planner → researcher] → synthesizer")
    return compiled


# Type alias for the compiled graph (used in type hints elsewhere)
AgentGraph = type(build_agent_graph())
