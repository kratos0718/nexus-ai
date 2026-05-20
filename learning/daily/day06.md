# Day 6 — LangGraph Multi-Agent System

## What We Built Today

| Component | File | Purpose |
|-----------|------|---------|
| State definition | `app/agents/state.py` | Single dict flowing through the graph |
| Agent nodes | `app/agents/nodes.py` | router, planner, rag, researcher, synthesizer |
| Graph assembly | `app/agents/graph.py` | StateGraph wiring + compile |
| Agent service | `app/services/agent_service.py` | Async wrapper, streaming via queue |
| Schemas | `app/schemas/agent.py` | Request/response validation |
| Agent endpoint | `app/api/v1/endpoints/agent.py` | POST /agent/query and /agent/stream |
| Frontend update | `frontend/src/app/(app)/chat/page.tsx` | Agent mode toggle + step progress |

---

## What is LangGraph?

LangGraph is a library for building **stateful, multi-actor** applications with LLMs.

Built on top of LangChain, but solves a different problem:
- LangChain: chains of LLM calls — linear, no branching
- LangGraph: graph of LLM calls — supports cycles, conditionals, parallel execution

Think of it as a state machine where each node is an LLM call or tool.

---

## Why Multi-Agent RAG?

Plain RAG works well for simple factual questions:
```
"What is the vacation policy?" → retrieve policy section → answer
```

But fails for complex questions:
```
"Compare the vacation policies across all three employment contracts and tell me which is most employee-friendly"
```

With plain RAG:
- Single retrieval query → gets context about ONE contract
- LLM lacks context about the other two
- Answer is incomplete and possibly wrong

With multi-agent:
- Router detects this needs multi-step reasoning
- Planner breaks it into: "vacation policy contract A?", "vacation policy contract B?", "vacation policy contract C?"
- Researcher retrieves independently for each
- Synthesizer sees ALL context → gives complete, comparative answer

---

## AgentState — The Data Model

```python
# app/agents/state.py

from typing import Annotated
import operator
from typing_extensions import TypedDict

class AgentState(TypedDict):
    # Set before graph starts
    question: str
    history: Optional[list[dict]]
    document_filter: Optional[dict]

    # Set by router
    route: str              # "simple" | "complex"

    # Set by planner (complex path only)
    sub_questions: list[str]

    # Set by rag or researcher — MERGEABLE list
    context: Annotated[list, operator.add]   # ← key detail

    # Set by synthesizer
    answer: str
    sources: list[dict]
    prompt_tokens: int
    completion_tokens: int
```

**`Annotated[list, operator.add]`** — this tells LangGraph how to merge partial updates from multiple nodes into this field. When Node A returns `{"context": [chunk1, chunk2]}` and Node B returns `{"context": [chunk3]}`, LangGraph merges them as `operator.add` → `[chunk1, chunk2, chunk3]`.

Without the annotation, the second update would OVERWRITE the first.

---

## The Graph Topology

```
START
  │
[router]
  │
  ├─── route="simple" ────────────────► [rag]
  │                                       │
  └─── route="complex" ── [planner] ─► [researcher]
                                          │
                                      [synthesizer]
                                          │
                                         END
```

Both paths converge at synthesizer. The same synthesizer node handles both cases — it just sees different amounts of context.

```python
# app/agents/graph.py

graph = StateGraph(AgentState)

graph.add_node("router",      router_node)
graph.add_node("planner",     planner_node)
graph.add_node("rag",         rag_node)
graph.add_node("researcher",  researcher_node)
graph.add_node("synthesizer", synthesizer_node)

graph.set_entry_point("router")

# Conditional fan-out based on router's decision
graph.add_conditional_edges(
    "router",
    lambda state: state["route"],    # reads the "route" field
    {"simple": "rag", "complex": "planner"},
)

graph.add_edge("planner",    "researcher")
graph.add_edge("researcher", "synthesizer")
graph.add_edge("rag",        "synthesizer")
graph.add_edge("synthesizer", END)

compiled = graph.compile()
```

`graph.compile()` validates the graph structure (no cycles you didn't intend, all nodes reachable) and returns a Runnable — the same interface as a LangChain chain.

---

## Node Deep Dives

### Router Node — Classify query complexity

```python
# app/agents/nodes.py

ROUTER_PROMPT = """Classify whether this question requires simple RAG retrieval or complex multi-step reasoning.

SIMPLE: The answer lives in one focused section of a document.
COMPLEX: Requires comparing multiple sections, multi-hop reasoning.

Question: {question}
Respond with ONLY: "simple" or "complex"."""

def router_node(state: AgentState) -> dict:
    llm = _get_llm()
    response = llm.invoke(ROUTER_PROMPT.format(question=state["question"]))
    route = response.content.strip().lower()
    if route not in ("simple", "complex"):
        route = "simple"    # safe default if LLM hallucinates
    return {"route": route}   # ← returns PARTIAL dict, not full state
```

**Key pattern: nodes return partial dicts.** LangGraph merges the returned dict into the existing state. `router_node` only changes `route` — all other fields stay untouched.

### Planner Node — Decompose into sub-questions

```python
PLANNER_PROMPT = """Break this complex question into 2-4 targeted sub-questions.
Each should be self-contained and target a different aspect.

Question: {question}
Return ONLY sub-questions, one per line."""

def planner_node(state: AgentState) -> dict:
    llm = _get_llm()
    response = llm.invoke(PLANNER_PROMPT.format(question=state["question"]))
    sub_questions = [q.strip() for q in response.content.split("\n") if q.strip()][:4]
    return {"sub_questions": sub_questions}
```

### Researcher Node — Retrieve for each sub-question

```python
def researcher_node(state: AgentState) -> dict:
    from app.services.rag_service import get_pipeline
    pipeline = get_pipeline()

    seen_ids: set[str] = set()
    all_results: list[SearchResult] = []

    for sq in state.get("sub_questions", []):
        results = pipeline._retrieve(sq, where=state.get("document_filter"))
        for r in results:
            if r.chunk_id not in seen_ids:   # deduplicate
                seen_ids.add(r.chunk_id)
                all_results.append(r)

    return {"context": all_results}   # merged into state via operator.add
```

**Deduplication matters:** The same document chunk might be the top result for multiple sub-questions. Without deduplication, the LLM sees the same text 3 times → wastes tokens, confuses generation.

### Synthesizer Node — Generate final answer

```python
def synthesizer_node(state: AgentState) -> dict:
    from app.services.rag_service import get_pipeline
    pipeline = get_pipeline()

    result = pipeline.generator.generate(
        query=state["question"],        # original question, not sub-questions
        context_results=state["context"],
        history=state.get("history"),
    )
    return {
        "answer": result.answer,
        "sources": [...],
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
    }
```

The synthesizer always uses the ORIGINAL question, not the sub-questions. It has all the context it needs in `state["context"]` — the sub-questions were just a retrieval strategy.

---

## Streaming Agent Progress via SSE

The agent graph is synchronous — it runs nodes sequentially. But we can stream progress events to the client as each node completes.

```python
# agent_service.py — stream()

def run_graph():
    # stream_mode="updates" yields one dict per node as it finishes
    for node_name, update in graph.stream(initial_state, stream_mode="updates"):
        event_queue.put(("node_done", node_name, update))
    event_queue.put(("done", None, None))

thread = threading.Thread(target=run_graph, daemon=True)
thread.start()

# Async generator reads from queue, yields SSE events
while True:
    kind, name, data = event_queue.get_nowait()
    ...
    if kind == "node_done":
        yield f"data: [STEP]{name}\n\n"           # router started
        if name == "router":
            yield f"data: [ROUTE]{data['route']}\n\n"  # routing decision
        if name == "planner":
            yield f"data: [PLAN]{json.dumps(data['sub_questions'])}\n\n"
```

The frontend reads these `[STEP]`, `[ROUTE]`, `[PLAN]`, `[CONTEXT]` events and shows them as status indicators — the user sees the agent "thinking."

### Custom SSE Protocol

```
Server → Client events:

data: [STEP]router          ← Router node started
data: [ROUTE]complex        ← Query classified as complex
data: [STEP]planner         ← Planner started
data: [PLAN]["q1","q2"]     ← Sub-questions generated
data: [STEP]researcher      ← Researcher started
data: [CONTEXT]12           ← 12 unique chunks retrieved
data: [STEP]synthesizer     ← Synthesizer started
data: The vacation          ← Answer tokens (word by word)
data:  policy...
data: [SOURCES][{...}]      ← Citations
data: [DONE]                ← Complete
```

---

## Lazy Imports to Avoid Circular Dependencies

```python
# nodes.py — WRONG: top-level import

from app.services.rag_service import get_pipeline  # ← circular!
# rag_service imports models imports base imports...

# CORRECT: import inside the function body

def rag_node(state: AgentState) -> dict:
    from app.services.rag_service import get_pipeline   # ← lazy import
    pipeline = get_pipeline()
    ...
```

Lazy imports break circular dependency chains. Python caches modules after first import, so there's no performance penalty after the first call.

---

## LangGraph vs LangChain Chains vs Agents (ReAct)

| | LangChain Chain | LangChain Agent (ReAct) | LangGraph |
|--|--|--|--|
| Structure | Linear sequence | LLM decides next action | Explicit graph |
| Branching | No | LLM-decided | Explicit conditional edges |
| Cycles | No | Yes (tool loop) | Optional (explicit) |
| State | No shared state | Memory per run | Shared state dict |
| Predictability | High | Low | High |
| Debuggability | High | Low | High |
| Use case | Fixed pipelines | Open-ended agents | Controlled multi-step |

**LangGraph is the sweet spot:** predictable like chains, capable of complex flows like ReAct agents, but you control the graph — the LLM can't go off-rails.

---

## Files Changed Today

```
backend/app/agents/__init__.py          ← NEW: exports
backend/app/agents/state.py             ← NEW: AgentState TypedDict
backend/app/agents/nodes.py             ← NEW: all 5 node functions
backend/app/agents/graph.py             ← NEW: StateGraph assembly
backend/app/services/agent_service.py   ← NEW: async wrapper + SSE streaming
backend/app/schemas/agent.py            ← NEW: request/response schemas
backend/app/api/v1/endpoints/agent.py   ← NEW: /agent/* endpoints
backend/app/api/v1/router.py            ← UPDATED: added agent router

frontend/src/app/(app)/chat/page.tsx    ← UPDATED: agent mode toggle + step UI
```
