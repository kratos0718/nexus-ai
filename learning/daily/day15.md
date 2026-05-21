# Day 15 — Observability Dashboard + Retrieval Mode UI

## What we built

Connected the backend's observability layer (Day 11 traces) and advanced retrieval modes (Day 14 HyDE/multi-query) to the frontend with a new Observability page and a retrieval mode selector in the chat toolbar.

---

## Files created / modified

| File | Change |
|------|--------|
| `frontend/src/app/(app)/observability/page.tsx` | NEW: stats dashboard + traces table |
| `frontend/src/app/(app)/layout.tsx` | Added Observability to sidebar nav |
| `frontend/src/app/(app)/chat/page.tsx` | Retrieval mode dropdown in toolbar |
| `learning/concepts/23_frontend_react_patterns.md` | 8-level concept guide |

---

## Observability page

Shows the `/traces/stats` aggregate data and `/traces/` recent calls table.

```
┌─────────────┬────────────────┬──────────────┬─────────────────┐
│ Total calls │  Avg latency   │ Total tokens │   Est. cost     │
│     47      │    1,234 ms    │   124,500    │    < $0.01      │
└─────────────┴────────────────┴──────────────┴─────────────────┘

Latency range                    Token breakdown
Min ████░░░░░░  380 ms           Prompt tokens     98,200
Avg ████████░░  1,234 ms         Completion tokens 26,300
Max ██████████  3,920 ms         Total            124,500 ←accent
                                 Error rate        0.0% ←green

Recent queries
Question         Mode          Tokens  Latency  Time    Status
─────────────────────────────────────────────────────────────────
What is RAG?     rag_standard   2,341   1,234ms  14:22   OK
Explain chunking rag_hyde       2,891   1,678ms  14:19   OK
...
```

**Auto-refreshes every 30 seconds** while on the page — uses `setInterval` with cleanup in `useEffect` return function.

**Parallel fetches:**
```tsx
const [statsRes, tracesRes] = await Promise.all([
  api.get<Stats>("/traces/stats"),
  api.get<{ traces: Trace[]; count: number }>("/traces/"),
]);
```
Both requests fire simultaneously — total wait is max(t1, t2) not t1 + t2.

---

## Retrieval mode selector in chat

When agent mode is OFF, a dropdown appears:

```
[All documents ▾] [⚡ Agent mode OFF] [Standard retrieval ▾]
                                       Standard retrieval
                                       HyDE — hypothetical doc
                                       Multi-query expansion
```

The selected mode is passed to the `/chat/stream` endpoint:
```tsx
body: JSON.stringify({
  question,
  document_id: selectedDoc || null,
  conversation_id: convId,
  retrieval_mode: agentMode ? "standard" : retrievalMode,
})
```

Agent mode always uses standard retrieval (the agent handles query routing internally).

---

## Mode badge coloring in traces table

Each retrieval mode gets a distinct color badge so you can spot patterns at a glance:

```tsx
const modeColors: Record<string, string> = {
  rag_hyde:      "#8b5cf6",   // purple
  rag_multiquery: "#0ea5e9",  // blue
  rag_standard:  "#10b981",   // green
  rag:           "#10b981",   // green (fallback)
  agent:         "#f59e0b",   // amber
};
// Applied as background: `${color}1a` (10% opacity) + text: color
```

---

## API shape alignment

The traces API returns:
- `trace_id` (string UUID) — not `id` (integer)
- `count` in the list response — not `total`
- `avg_duration_ms`, `min_duration_ms`, `max_duration_ms` — not `latency_ms`

TypeScript catches mismatches at compile time if you type your `api.get<T>()` calls correctly:
```tsx
// TypeScript error if you access data.avg_latency_ms — field doesn't exist
const { data } = await api.get<Stats>("/traces/stats");
// data.avg_duration_ms ✓
// data.avg_latency_ms  ✗ compile error
```

---

## Key patterns used

**`Promise.all` for parallel requests:**
Two sequential requests at 500ms each = 1000ms.
`Promise.all` = 500ms (both run simultaneously).

**`setInterval` with cleanup:**
```tsx
const interval = setInterval(fetchData, 30_000);
return () => clearInterval(interval); // runs on unmount
```
Without cleanup: interval fires after component unmounts → React warning + memory leak.

**Optimistic delete in dashboard (existing pattern):**
```tsx
setDocs(d => d.filter(x => x.document_id !== docId)); // instant UI
await api.delete(`/documents/${docId}`);              // confirm with server
```
User sees instant feedback; no spinner needed for a simple delete.

**TypeScript literal types for enum-like state:**
```tsx
type RetrievalMode = "standard" | "hyde" | "multiquery";
const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("standard");
// Only these three values compile — impossible to assign "invalid_mode"
```
