# Function Calling, Tool Use & Structured Outputs

## LEVEL 1 — What Problem Does This Solve?

### The fundamental limitation of LLMs

By default, an LLM is a **text-in, text-out** machine:

```
Input:  "What is 847 × 293?"
Output: "847 × 293 = 248,171"   ← WRONG. LLMs are bad at arithmetic.
```

The LLM generates plausible-sounding text. For math, dates, real-time data, or
external APIs, it will hallucinate confident wrong answers.

**Function calling** lets the LLM say: *"I don't know this, but I know a tool that does."*

```
Input:  "What is 847 × 293?"
LLM:    → calls calculator(847, 293)
Result: 248,171  ← correct, from actual math
LLM:    "847 × 293 = 248,171"
```

The LLM acts as a **decision maker** ("which tool to call, with what arguments")
rather than the executor. The actual execution happens in your Python code.

---

## LEVEL 2 — How Function Calling Works (The API Mechanism)

### Step 1: You define tools as JSON schemas

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search the knowledge base for relevant information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of results to return",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    }
]
```

### Step 2: LLM decides whether to call a tool

```python
response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": "Find info about vacation policy"}],
    tools=tools,
    tool_choice="auto",   # LLM decides: call a tool OR answer directly
)
```

The response is one of two things:
```python
# Case A: LLM wants to call a tool
response.choices[0].message.tool_calls = [
    {
        "id": "call_abc123",
        "type": "function",
        "function": {
            "name": "search_documents",
            "arguments": '{"query": "vacation policy", "max_results": 5}'
        }
    }
]

# Case B: LLM answers directly (no tool needed)
response.choices[0].message.content = "I can answer this directly..."
response.choices[0].message.tool_calls = None
```

### Step 3: You execute the tool and send the result back

```python
import json

# Parse the tool call
tool_call = response.choices[0].message.tool_calls[0]
args = json.loads(tool_call.function.arguments)

# Execute YOUR code (not the LLM's)
results = search_documents(query=args["query"], max_results=args.get("max_results", 5))

# Send result back to LLM for final answer
messages = [
    {"role": "user", "content": "Find info about vacation policy"},
    response.choices[0].message,          # the LLM's tool_call message
    {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": json.dumps(results),   # your tool's output
    }
]

final_response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=messages,
    tools=tools,
)
# Now the LLM generates a final answer using the tool result
```

---

## LEVEL 3 — Structured Outputs (What Nexus Uses)

Structured output is a **specific application of function calling** where instead of calling
an external tool, the LLM fills in a Pydantic schema you define.

### The old way — brittle string parsing

```python
# Ask the LLM to route
response = llm.invoke("Is this simple or complex? Reply with one word: " + question)
text = response.content.strip().lower()

# What if LLM says "This is a COMPLEX question." instead of just "complex"?
if "complex" in text:      # fragile substring match
    route = "complex"
elif "simple" in text:
    route = "simple"
else:
    route = "simple"       # silent fallback — wrong routing, no error
```

Problems:
- LLM might say "COMPLEX" (uppercase), "complex." (period), "This is complex"
- You write parsing code for every output format
- Failures are silent — you get wrong behavior, not exceptions

### The new way — typed Pydantic models

```python
from pydantic import BaseModel, Field
from typing import Literal

class RouteDecision(BaseModel):
    route: Literal["simple", "complex"] = Field(
        description="simple for direct lookup, complex for multi-step reasoning"
    )
    reasoning: str = Field(description="One sentence explaining the decision")

# LLM is FORCED to return valid JSON matching this schema
structured_llm = llm.with_structured_output(RouteDecision)
decision: RouteDecision = structured_llm.invoke(prompt)

# decision.route is guaranteed to be "simple" or "complex"
# decision.reasoning is guaranteed to be a string
# No parsing. No fallbacks. Type-safe.
print(decision.route)      # → "complex"
print(decision.reasoning)  # → "Requires comparing multiple sections"
```

### How `with_structured_output` works under the hood

LangChain converts your Pydantic model to a JSON Schema and sends it to the LLM
as a function definition. The LLM "calls" that function with its output — but
since there's no actual function to execute, LangChain just parses the
`tool_call.arguments` and deserializes it into your Pydantic model.

```
Your Pydantic model
        ↓ (LangChain converts to JSON Schema)
Tool definition in API request
        ↓ (LLM generates tool_call arguments)
Raw JSON string: '{"route": "complex", "reasoning": "..."}'
        ↓ (LangChain deserializes)
RouteDecision(route="complex", reasoning="...")
```

### Pydantic field constraints

```python
from pydantic import BaseModel, Field

class ResearchPlan(BaseModel):
    sub_questions: list[str] = Field(
        description="2 to 4 targeted sub-questions",
        min_length=2,    # list must have at least 2 items
        max_length=4,    # list can have at most 4 items
    )

class SearchQuery(BaseModel):
    query: str = Field(min_length=3, max_length=200)
    filters: dict = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)  # between 0 and 1
```

The LLM sees these constraints in the JSON Schema and tries to honor them.
Pydantic validates on deserialization and raises an error if violated.

---

## LEVEL 4 — JSON Schema Deep Dive

JSON Schema is the format used to describe the structure of JSON data.
LLMs learn from API documentation written in JSON Schema, which is why they
understand it well.

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Full name of the person",
      "minLength": 1,
      "maxLength": 100
    },
    "age": {
      "type": "integer",
      "minimum": 0,
      "maximum": 150
    },
    "role": {
      "type": "string",
      "enum": ["admin", "user", "viewer"]
    },
    "tags": {
      "type": "array",
      "items": {"type": "string"},
      "maxItems": 10
    },
    "address": {
      "type": "object",
      "properties": {
        "city": {"type": "string"},
        "country": {"type": "string"}
      },
      "required": ["city"]
    }
  },
  "required": ["name", "role"]
}
```

Pydantic generates this automatically from your model:

```python
import json
from pydantic import BaseModel

class UserProfile(BaseModel):
    name: str
    age: int
    role: str

print(json.dumps(UserProfile.model_json_schema(), indent=2))
# → the JSON Schema above (simplified)
```

---

## LEVEL 5 — Tool Use Patterns

### Pattern 1: Single tool call (most common)

LLM is given tools, decides to call one, you execute it, LLM gives final answer.
Good for: search, calculation, lookup.

```
User question → LLM decides → one tool call → result → LLM answer
```

### Pattern 2: ReAct (Reason + Act) — multi-turn tool use

LLM can call multiple tools in sequence, reasoning between each step.

```
Question: "Who wrote the longest chapter in my document and what year were they born?"

LLM: I need to find the longest chapter.
→ calls find_longest_chapter()
Result: "Chapter 3 by Dr. Sarah Chen (42 pages)"

LLM: Now I need her birth year.
→ calls search_web("Dr. Sarah Chen computer scientist born")
Result: "Sarah Chen, born 1978..."

LLM: Dr. Sarah Chen wrote the longest chapter. She was born in 1978.
```

This is a **ReAct loop**: reason about what to do → act (call tool) → observe result → repeat.

LangGraph implements this as a cycle in the graph:
```
[llm_node] → tool call? → [tool_executor] → back to [llm_node]
           → no tool call → [END]
```

### Pattern 3: Parallel tool calls

Modern LLMs (GPT-4o, Claude 3, Llama 3.3) can call multiple tools simultaneously:

```python
# LLM returns multiple tool_calls in one response
tool_calls = [
    {"function": {"name": "search", "arguments": '{"query": "revenue"}'}},
    {"function": {"name": "search", "arguments": '{"query": "expenses"}'}},
]
```

You execute them in parallel (e.g., `asyncio.gather`), send all results back, LLM synthesizes.

### Pattern 4: Forced tool use

```python
client.chat.completions.create(
    tools=tools,
    tool_choice={"type": "function", "function": {"name": "search_documents"}},
    # ↑ forces this specific tool to be called, even if LLM would answer directly
)
```

Used when you always need a structured response (e.g., classification tasks).
`with_structured_output` uses this under the hood.

---

## LEVEL 6 — Tool Design Principles

### 1. Description is everything

The LLM decides *which* tool to call based purely on the description. A vague
description leads to wrong tool selection.

```python
# Bad
{"name": "search", "description": "Search for things"}

# Good
{"name": "search_documents", "description":
 "Search the user's uploaded knowledge base for relevant document chunks. "
 "Use this when the question requires information from their documents. "
 "Do NOT use for real-time data or calculations."}
```

### 2. Arguments should be obvious from context

The LLM fills in arguments from the conversation. If an argument requires
information the LLM doesn't have (e.g., internal IDs), it will hallucinate.

```python
# Bad — LLM has no idea what document_id to pass
{"name": "get_document", "parameters": {"document_id": {"type": "string"}}}

# Good — LLM can construct this from the user's question
{"name": "search_by_keyword", "parameters": {"keyword": {"type": "string"}}}
```

### 3. Make tools idempotent

Tool calls may be retried. A search is idempotent (same result). Sending an
email is not (sends twice). Design tools that are safe to call multiple times.

### 4. Return structured results

```python
# Bad — LLM has to parse your return value
return "Found 3 results: vacation policy: 14 days, sick leave: 10 days, ..."

# Good — structured, LLM knows exactly what it got
return {
    "results": [
        {"title": "Vacation Policy", "content": "14 days PTO per year", "score": 0.94},
        {"title": "Sick Leave", "content": "10 days sick leave per year", "score": 0.87},
    ],
    "total_found": 2
}
```

---

## LEVEL 7 — LangChain Tool Integration

LangChain provides the `@tool` decorator to define tools:

```python
from langchain_core.tools import tool

@tool
def search_documents(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the knowledge base for relevant document chunks.
    Use this when the user's question requires information from uploaded documents.
    """
    pipeline = get_pipeline()
    results = pipeline._retrieve(query)[:max_results]
    return [{"content": r.text, "source": r.metadata.get("source"), "score": r.score}
            for r in results]

@tool
def calculate(expression: str) -> str:
    """
    Evaluate a mathematical expression. Use for arithmetic, percentages, ratios.
    Input: a Python-evaluable math expression like '847 * 293' or '(100 - 23) / 100'.
    """
    import ast
    try:
        # Safe eval — only allows math operations, no imports or function calls
        tree = ast.parse(expression, mode='eval')
        result = eval(compile(tree, '', 'eval'))
        return str(result)
    except Exception as e:
        return f"Error: {e}"

# Bind tools to LLM
llm_with_tools = llm.bind_tools([search_documents, calculate])

# Now invoke — LLM decides whether to use a tool
response = llm_with_tools.invoke("What is 23% of the 14-day vacation policy?")
```

The `@tool` decorator:
- Uses the function's docstring as the tool description (write good docstrings!)
- Uses function parameter type hints and names as the JSON Schema
- Returns a `Tool` object LangChain knows how to serialize

---

## LEVEL 8 — What Nexus Uses (Practical Implementation)

Nexus uses structured outputs in two nodes:

### Router node — `RouteDecision` schema

```
Before (string parsing):
  LLM response → parse text → fallback logic → route string

After (structured output):
  LLM response → RouteDecision object → decision.route (guaranteed "simple"/"complex")
```

The `Literal["simple", "complex"]` type means Pydantic rejects any other value.
The `reasoning` field makes the LLM explain itself (useful for debugging).

### Planner node — `ResearchPlan` schema

```
Before (string parsing):
  LLM response → split by newline → strip bullets → cap at 4

After (structured output):
  LLM response → ResearchPlan object → plan.sub_questions (guaranteed list[str])
```

`min_length=2` forces at least 2 sub-questions (a 1-item plan defeats the purpose).
`max_length=4` caps cost (more sub-questions = more vector searches = more tokens).

### Why not add full ReAct tool calling?

The existing architecture already achieves multi-step reasoning through LangGraph
nodes (planner → researcher → synthesizer). Full ReAct adds complexity
(loop detection, tool timeouts, max iterations) with marginal benefit for a
document Q&A use case. Structured outputs give 80% of the benefit with 20% of
the complexity.

---

## Key Terms Glossary

| Term | Meaning |
|---|---|
| Function calling | LLM decides to call a function, returns structured args |
| Tool use | Same as function calling (different providers use different names) |
| Structured output | Function calling where the "tool" is a Pydantic schema, no actual execution |
| JSON Schema | Standard format describing JSON structure (types, required fields, constraints) |
| Tool binding | Attaching tool definitions to an LLM instance: `llm.bind_tools(...)` |
| `with_structured_output` | LangChain shortcut for structured-output-as-tool |
| ReAct | Reason-Act loop: LLM reasons → calls tool → observes → repeats |
| Parallel tool calls | LLM calls multiple tools in one response |
| `tool_choice` | Force the LLM to call a specific tool (or any tool, or no tool) |

---

## Interview Questions

**Q: What is the difference between function calling and structured outputs?**
Function calling: LLM says "call this external function with these args" — you execute real code (search DB, call API) and send the result back for a final answer. Structured output: LLM fills in a schema you defined — there's no external execution, the LLM's response IS the result. Structured output is implemented using function calling under the hood (the schema is sent as a tool definition), but conceptually different: one runs external code, the other just constrains output format.

**Q: Why is string parsing of LLM outputs fragile?**
LLMs are trained to be helpful and natural. Ask for "one word: simple or complex" and the model might respond "SIMPLE", "simple.", "I would say simple", or switch languages under certain prompts. String parsing works on your test cases but breaks on edge cases in production. Structured outputs use the model's tool-calling capability which was specifically trained to produce valid JSON — much more reliable.

**Q: What is a JSON Schema and why do LLMs understand it?**
JSON Schema is a vocabulary for describing JSON structure — types, required fields, value constraints, nested objects. LLMs understand it because most API documentation, OpenAPI specs, and code examples on the internet use it. It was in their training data. When you send a JSON Schema as a tool definition, the model has seen thousands of examples of "here's a schema, here's valid JSON for it" and learned to follow them.

**Q: What is ReAct and when would you use it over a fixed agent graph?**
ReAct (Reason + Act) is a loop: LLM reasons about what to do, calls a tool, observes the result, decides whether to call another tool or stop. Use ReAct for open-ended tasks where you don't know in advance how many tool calls are needed (e.g., research assistant that browses the web). Use a fixed LangGraph when the task structure is known (e.g., always: route → retrieve → generate) — it's more predictable, easier to debug, and has no loop-detection issues.
