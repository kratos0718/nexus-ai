# Day 10 — Function Calling & Structured Outputs

**Date:** 2026-05-21  
**Focus:** Replacing brittle string parsing with typed Pydantic schemas in agent nodes

---

## The Problem We Fixed

The router node used to parse free-text output:

```python
# OLD — fragile
response = llm.invoke("Reply with ONLY one word: simple or complex")
route = response.content.strip().lower()
if route not in ("simple", "complex"):
    route = "simple"   # silent wrong fallback
```

What could go wrong:
- LLM says "SIMPLE" → `.lower()` fixes it, but
- LLM says "simple." → strip doesn't remove period → falls to default
- LLM says "I would classify this as complex" → falls to "simple" silently
- LLM switches languages in multilingual documents → completely wrong

The planner had the same problem — splitting newlines and stripping bullets from free text.

---

## What We Built

### Structured Output Schemas (`app/agents/nodes.py`)

```python
from pydantic import BaseModel, Field
from typing import Literal

class RouteDecision(BaseModel):
    route: Literal["simple", "complex"]   # only these two values accepted
    reasoning: str                         # LLM explains itself (good for debugging)

class ResearchPlan(BaseModel):
    sub_questions: list[str] = Field(min_length=2, max_length=4)
```

### Router Node — before vs after

```python
# BEFORE: 6 lines of parsing + silent fallback
response = llm.invoke(prompt)
route = response.content.strip().lower().replace('"', "").replace("'", "")
if route not in ("simple", "complex"):
    route = "simple"

# AFTER: 2 lines, type-safe, no parsing
structured_llm = llm.with_structured_output(RouteDecision)
decision = structured_llm.invoke(prompt)
route = decision.route   # guaranteed to be "simple" or "complex"
```

### Planner Node — before vs after

```python
# BEFORE: manual newline split + bullet strip
sub_questions = [q.strip().lstrip("-•* ") for q in response.content.split("\n") if q.strip()][:4]

# AFTER: typed list, min/max enforced by Pydantic
plan = structured_llm.invoke(prompt)
sub_questions = plan.sub_questions   # guaranteed list[str] with 2-4 items
```

---

## How `with_structured_output` Works

```
Your Pydantic model (RouteDecision)
        ↓ LangChain converts to JSON Schema
{
  "type": "object",
  "properties": {
    "route": {"type": "string", "enum": ["simple", "complex"]},
    "reasoning": {"type": "string"}
  },
  "required": ["route", "reasoning"]
}
        ↓ Sent to LLM as a tool definition
LLM generates: {"route": "complex", "reasoning": "Requires comparing sections"}
        ↓ LangChain deserializes
RouteDecision(route="complex", reasoning="Requires comparing sections")
```

The LLM doesn't "call" an external function — it just fills in the schema.
The tool mechanism is repurposed for output formatting.

---

## Concepts Learned

- **Function calling**: LLM decides to call a function → you execute → LLM uses result
- **Structured output**: LLM fills a schema → LangChain deserializes → typed object
- **JSON Schema**: Standard format for describing JSON structure. LLMs know it from training data.
- **`Literal["a", "b"]`**: Pydantic type that only allows specific string values (like an enum)
- **`Field(min_length=, max_length=)`**: Pydantic constraints enforced on deserialization
- **Graceful fallback**: `try/except` around structured output — if it fails, default to safe behavior
- **ReAct pattern**: Reason → Act (tool call) → Observe → repeat. For open-ended multi-tool tasks.
- **Tool vs structured output**: Tool executes external code; structured output just constrains format

---

## Files Changed

```
backend/app/agents/nodes.py                  ← UPDATED: structured outputs for router + planner
learning/concepts/17_function_calling_and_tools.md ← NEW (basic → advanced)
```

---

## How This Appears in Logs

Before:
```
[Router] Classifying: 'Compare the two contracts...'
[Router] → complex
```

After:
```
[Router] Classifying: 'Compare the two contracts...'
[Router] → complex | Requires comparing multiple sections across both documents
```

The `reasoning` field gives you free debugging insight — you can see WHY the router chose a path without adding any extra code.

---

## Interview Angles

**"How do you handle LLM output that doesn't match what you expected?"**
→ Use structured outputs with Pydantic schemas. Instead of parsing text, the LLM fills in a typed schema enforced by JSON Schema constraints. `Literal["simple", "complex"]` means the model can ONLY return those two values — any other response fails Pydantic validation. We wrap in try/except with a safe default as a last resort.

**"What is the difference between function calling and just asking the LLM nicely for JSON?"**
→ Asking for JSON in the prompt is unreliable — the LLM might add explanation text before/after, use single quotes, or miss required fields. Function calling is a model capability specifically trained to produce valid JSON matching a schema. The model has a separate "tool call" output path that bypasses the normal text generation, producing structured output with much higher reliability.

**"Walk me through what happens when `with_structured_output` is called."**
→ LangChain takes your Pydantic model, calls `model_json_schema()` to get a JSON Schema, wraps it as a tool definition, and attaches it to the LLM with `tool_choice=forced`. When invoked, the LLM outputs a tool call with JSON arguments. LangChain parses those arguments and calls `YourModel.model_validate(parsed_json)`, returning a typed Python object. Any validation error (wrong type, missing required field) raises a Pydantic ValidationError.
