# Concept 10 — LangGraph Multi-Agent Systems

## The Agent Mental Model

An agent is an LLM that takes actions based on observations.

**ReAct loop (classic agent pattern):**
```
Thought: I need to find the vacation policy
Action: search_documents("vacation policy")
Observation: "Employees receive 15 days PTO per year..."
Thought: Now I can answer
Action: final_answer("15 days PTO per year")
```

Problem: the LLM decides what to do next. On complex tasks it hallucinates tools, infinite-loops, or takes wrong actions with no recovery.

**LangGraph approach:** YOU define the graph. The LLM fills in the content, but the control flow is deterministic.

---

## StateGraph — Core Concepts

```python
from langgraph.graph import StateGraph, END

graph = StateGraph(MyState)      # MyState is a TypedDict

# Nodes — functions that transform state
graph.add_node("node_a", fn_a)  # fn_a: MyState → dict (partial update)
graph.add_node("node_b", fn_b)

# Edges — flow between nodes
graph.add_edge("node_a", "node_b")  # always go a → b
graph.add_edge("node_b", END)       # b is the last node

# Conditional edges — choose next node based on state
graph.add_conditional_edges(
    "router",
    decide_fn,                        # fn(state) → str (name of next node)
    {"option_a": "node_a", "option_b": "node_b"},  # map decision → node
)

graph.set_entry_point("router")  # first node

compiled = graph.compile()      # validates graph, returns Runnable
```

---

## State Merging with Annotated

By default, when a node returns `{"field": new_value}`, it REPLACES the field.

```python
state = {"messages": ["hi"]}
node_returns = {"messages": ["hello"]}
result = {"messages": ["hello"]}   # replaced!
```

With `Annotated`:
```python
from typing import Annotated
import operator

class State(TypedDict):
    messages: Annotated[list, operator.add]   # merge with +

state = {"messages": ["hi"]}
node_returns = {"messages": ["hello"]}
result = {"messages": ["hi", "hello"]}   # appended!
```

`operator.add` works on lists (concatenation) and numbers (addition). You can use any function as the reducer.

Why it matters for our researcher node: each sub-question retrieves results. We want to accumulate ALL results, not have each retrieval overwrite the previous.

---

## Graph Execution Modes

### `invoke` — synchronous, returns final state
```python
final_state = graph.invoke(initial_state)
# Blocks until all nodes complete, returns full state dict
```

### `stream` — yields updates as nodes complete
```python
for node_name, update in graph.stream(initial_state, stream_mode="updates"):
    print(f"Node '{node_name}' completed: {update}")
# Yields after each node — great for streaming progress to clients
```

### `astream` — async version of stream
```python
async for node_name, update in graph.astream(initial_state, stream_mode="updates"):
    yield f"data: [STEP]{node_name}\n\n"
```

**`stream_mode` options:**
- `"updates"` — one dict per node showing what changed
- `"values"` — full state after each node (more data)
- `"debug"` — verbose internal events

---

## Parallel Node Execution

LangGraph supports parallel execution when nodes don't depend on each other:

```python
# Parallel research: retrieve for 3 sub-questions simultaneously
graph.add_node("researcher_1", research_fn_1)
graph.add_node("researcher_2", research_fn_2)
graph.add_node("researcher_3", research_fn_3)

# Fan-out from planner to all three simultaneously
graph.add_edge("planner", "researcher_1")
graph.add_edge("planner", "researcher_2")
graph.add_edge("planner", "researcher_3")

# Fan-in: all three must complete before synthesizer
graph.add_edge("researcher_1", "synthesizer")
graph.add_edge("researcher_2", "synthesizer")
graph.add_edge("researcher_3", "synthesizer")
```

LangGraph automatically parallelizes these nodes and waits for all to complete before proceeding to synthesizer. The `Annotated[list, operator.add]` on `context` merges their results.

**Our current implementation is sequential** — researcher iterates through sub-questions one at a time. Parallelization would 3× the speed for complex queries. This is a Day 8-9 optimization.

---

## Human-in-the-Loop

LangGraph supports pausing the graph mid-execution for human approval:

```python
compiled = graph.compile(
    interrupt_before=["delete_action"]  # pause before dangerous node
)

# Run graph until interrupt
partial_state = graph.invoke(initial_state)

# Check what the agent wants to do
print(partial_state["proposed_action"])

# Resume if approved
if approved:
    final_state = graph.invoke(Command(resume=True), config)
```

Use cases: document deletion, API calls with side effects, financial transactions — anything that needs human sign-off.

---

## Memory and Persistence

By default, graph state only exists during one `invoke` call. For persistent memory:

```python
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string("./checkpoints.db")
compiled = graph.compile(checkpointer=checkpointer)

# Each run has a thread_id — same thread_id resumes from last checkpoint
config = {"configurable": {"thread_id": "user-123-session-456"}}
result = graph.invoke(state, config=config)
```

The checkpointer saves state after every node. If the graph crashes mid-execution, restart with the same `thread_id` to resume from the last checkpoint.

---

## Comparing Agent Architectures

### Single-Agent (our Day 3-5 approach)
```
Query → Embed → Search → Rerank → Generate → Answer
```
- Fast, simple, predictable
- Fails on multi-hop, comparative questions
- One LLM call

### Multi-Agent with LangGraph (Day 6)
```
Query → Router → [Simple: RAG | Complex: Planner → Researcher] → Synthesizer → Answer
```
- Handles both simple and complex queries
- 2-4 LLM calls (router + optional planner + synthesizer)
- Transparent: shows routing decision and sub-questions
- Still deterministic (you control the graph)

### ReAct Agent (future)
```
Query → LLM decides tools → [search, calculate, lookup...] → LLM → done?
         ↑_______________________↓ (loop until LLM says done)
```
- Maximum flexibility
- Unpredictable number of steps
- Can loop/hallucinate
- Use for open-ended tasks, not RAG

### LangGraph with ReAct nodes (advanced)
Use a ReAct loop as ONE node in a LangGraph graph. Gets the flexibility where you need it, with deterministic routing around it.

---

## Interview Questions on Agents

**Q: What is an agent in the context of LLMs?**
A: An LLM that takes actions based on its observations, typically in a loop: Thought → Action → Observation → repeat until done. The LLM reasons about what to do next rather than following a fixed pipeline.

**Q: What is LangGraph and why use it over LangChain chains?**
A: LangGraph is a stateful graph framework for multi-agent applications. Use it when you need conditional routing, parallel execution, cycles, or shared state across multiple LLM calls. LangChain chains are linear — good for fixed pipelines. LangGraph is good when the control flow depends on the LLM's output.

**Q: What is the difference between `graph.invoke()` and `graph.stream()`?**
A: `invoke` runs the entire graph synchronously and returns the final state. `stream` yields partial updates after each node completes — useful for streaming progress to users or debugging node outputs without waiting for the full result.

**Q: How do you prevent an LLM agent from infinite-looping?**
A: (1) Use `recursion_limit` in LangGraph's config to cap iterations. (2) Add explicit termination conditions checked in conditional edges. (3) Track the number of tool calls in state and force END after N calls. (4) Use explicit graph structure instead of ReAct loops where possible.

**Q: How would you make the researcher nodes run in parallel?**
A: Fan-out from the planner node to multiple researcher nodes simultaneously (each gets one sub-question). Use `Annotated[list, operator.add]` on the context field so all researchers write to the same list. LangGraph executes them in parallel and waits for all before moving to synthesizer. This requires splitting the sub-questions list before the fan-out.
