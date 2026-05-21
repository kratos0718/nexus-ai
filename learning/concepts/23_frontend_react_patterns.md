# Frontend React Patterns for AI Applications

## Why AI apps need different frontend patterns

A regular CRUD app: user clicks, server responds in 50ms, page updates. Done.

An AI app: user clicks, server takes 2-15 seconds, then sends a stream of tokens one by one. The UI must handle streaming, partial state, loading indicators, error recovery, and real-time updates — all at once. Standard form-submit patterns break completely.

---

## Level 1: Component structure and state

A React component is a function that takes props and returns JSX. State is what can change over time.

```tsx
// Bad — all state in one place, unmaintainable at scale
function ChatPage() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [docs, setDocs] = useState([]);
  const [conversations, setConversations] = useState([]);
  // ... 10 more useState calls

// Good — split by concern
function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  // Separate components own their own state
  return (
    <>
      <ConversationSidebar />
      <MessageList messages={messages} />
      <ChatInput input={input} setInput={setInput} onSend={send} sending={sending} />
    </>
  );
}
```

**Rules:**
- State belongs in the lowest common ancestor that needs it
- If only one component uses it, keep it there
- If multiple siblings need it, lift it to their parent
- If many components need it, use Context or a state manager

---

## Level 2: Data fetching patterns

**Pattern 1: Fetch on mount**
```tsx
useEffect(() => {
  api.get<Document[]>("/documents/").then(({ data }) => setDocs(data));
}, []); // empty array = run once on mount
```

**Pattern 2: Fetch with loading/error state**
```tsx
const [loading, setLoading] = useState(true);
const [error, setError] = useState("");

useEffect(() => {
  async function load() {
    try {
      const { data } = await api.get("/traces/stats");
      setStats(data);
    } catch {
      setError("Failed to load. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }
  load();
}, []);
```

**Pattern 3: Parallel fetches**
```tsx
// Serial (slow) — waits for each request before starting next
const stats = await api.get("/traces/stats");
const traces = await api.get("/traces/");

// Parallel (fast) — both start at the same time
const [statsRes, tracesRes] = await Promise.all([
  api.get("/traces/stats"),
  api.get("/traces/"),
]);
```

Always prefer `Promise.all` for independent requests. Two 500ms requests:
- Serial: 1000ms
- Parallel: 500ms

---

## Level 3: Polling for async state

When a long operation runs in the background (document indexing, Celery task), you need to check status periodically.

```tsx
const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

useEffect(() => {
  fetchDocs(); // initial load

  // Poll every 3s
  pollRef.current = setInterval(fetchDocs, 3000);

  // Cleanup: clear interval when component unmounts
  return () => {
    if (pollRef.current) clearInterval(pollRef.current);
  };
}, []);
```

**Important:** Always clear intervals in the cleanup function. If you don't:
- The interval keeps firing after the component unmounts
- Calls `setState` on an unmounted component (React warning)
- Memory leak in long-running sessions

**Optimization:** Only poll when needed
```tsx
const hasPending = docs.some(d => d.status === "processing");
// Clear interval when no docs are processing
useEffect(() => {
  if (!hasPending && pollRef.current) {
    clearInterval(pollRef.current);
    pollRef.current = null;
  }
}, [hasPending]);
```

---

## Level 4: SSE streaming — the core AI UI pattern

Server-Sent Events: server pushes data to the browser over a persistent HTTP connection. Perfect for token streaming.

```tsx
// Open a streaming connection with fetch (not axios — axios buffers)
const res = await fetch(`${BASE_URL}/chat/stream`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  },
  body: JSON.stringify({ question, document_id }),
});

// res.body is a ReadableStream
const reader = res.body!.getReader();
const decoder = new TextDecoder();
let accumulated = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  // Decode the chunk (may be partial — stream: true handles that)
  const text = decoder.decode(value, { stream: true });

  // SSE format: "data: <payload>\n\n"
  for (const line of text.split("\n")) {
    if (!line.startsWith("data: ")) continue;
    const payload = line.slice(6);

    if (payload === "[DONE]") break;
    if (payload.startsWith("[SOURCES]")) {
      sources = JSON.parse(payload.slice(9));
    } else {
      // Regular token
      accumulated += payload;
      setMessages(msgs => msgs.map(m =>
        m.id === assistantId ? { ...m, content: accumulated } : m
      ));
    }
  }
}
```

**Key insight:** Update state on every token chunk so the user sees text appearing in real time. Don't wait for the stream to finish.

**Why `stream: true` in TextDecoder:**
TCP/IP can split SSE data across multiple chunks. Without `stream: true`, a chunk that ends mid-UTF-8-character gets decoded as `?`. With `stream: true`, the decoder buffers incomplete multi-byte characters until the next chunk arrives.

---

## Level 5: Optimistic UI updates

Don't wait for the server to confirm before updating the UI. Show the change immediately, then reconcile with server response.

```tsx
// Without optimistic update (slow — user waits for server)
async function handleDelete(docId: string) {
  await api.delete(`/documents/${docId}`);
  const { data } = await api.get("/documents/");
  setDocs(data.documents);
}

// With optimistic update (fast — UI updates instantly)
async function handleDelete(docId: string) {
  setDocs(d => d.filter(x => x.document_id !== docId)); // instant
  try {
    await api.delete(`/documents/${docId}`);
  } catch {
    // Rollback on failure
    fetchDocs(); // re-fetch to restore correct state
  }
}
```

When to use optimistic updates:
- Destructive actions (delete) — usually succeed
- Status changes (mark as read)
- Low-consequence actions

When NOT to use:
- Payment processing
- Actions that might fail due to business rules
- Actions where showing wrong state is harmful

---

## Level 6: JWT token management with Axios interceptors

Every API request needs the JWT access token. Tokens expire. You need to refresh them transparently.

```tsx
// Attach token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On 401: try refresh → retry
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true; // prevent infinite retry loops
      try {
        const refresh = localStorage.getItem("refresh_token");
        const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {
          refresh_token: refresh,
        });
        localStorage.setItem("access_token", data.access_token);
        original.headers.Authorization = `Bearer ${data.access_token}`;
        return api(original); // retry original request
      } catch {
        // Refresh failed — session expired
        localStorage.removeItem("access_token");
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);
```

**Why `!original._retry`:**
If the retry itself returns 401 (refresh token also expired), we don't want to try again — that's an infinite loop. The `_retry` flag breaks the cycle.

**Why `axios.post` (not `api.post`) for the refresh call:**
Using the `api` instance would trigger the interceptor again if the refresh call fails with 401, causing a loop. Use a clean axios instance without the interceptor for the refresh call itself.

---

## Level 7: Real-time auto-refresh patterns

For data that changes in the background (observability dashboard, document status), automatically refresh without requiring user action.

**Simple interval:**
```tsx
useEffect(() => {
  fetchData(); // initial load
  const interval = setInterval(fetchData, 30_000); // every 30s
  return () => clearInterval(interval);
}, []);
```

**Visibility-aware refresh (don't poll when tab is hidden):**
```tsx
useEffect(() => {
  let interval: ReturnType<typeof setInterval>;

  function startPolling() {
    fetchData();
    interval = setInterval(fetchData, 30_000);
  }

  function stopPolling() {
    clearInterval(interval);
  }

  // Start when tab becomes visible, stop when hidden
  document.addEventListener("visibilitychange", () => {
    document.hidden ? stopPolling() : startPolling();
  });

  startPolling();
  return () => {
    stopPolling();
    document.removeEventListener("visibilitychange", stopPolling);
  };
}, []);
```

**When to use each real-time strategy:**

| Technique | How it works | Best for |
|-----------|--------------|----------|
| Polling | Client asks every N seconds | Document status, simple dashboards |
| SSE | Server pushes when data changes | Token streaming, notifications |
| WebSocket | Bidirectional, persistent connection | Collaborative editing, live cursors |

SSE is simpler than WebSocket and sufficient for most AI app needs. WebSocket is overkill unless you need to push messages from client to server in real time too.

---

## Level 8: TypeScript patterns for API responses

Never use `any`. Type every API response — TypeScript will catch mismatches between your API and frontend at compile time.

```tsx
// Define types that mirror the API schema exactly
interface Stats {
  total_calls: number;
  avg_duration_ms: number;   // matches backend's field name
  total_tokens: number;
  estimated_cost_usd: number;
}

// Generic API call with type parameter
const { data } = await api.get<Stats>("/traces/stats");
// data is now typed — TypeScript knows data.avg_duration_ms is a number
// data.avg_latency_ms would be a compile error
```

**The enum/literal pattern for constrained values:**
```tsx
// Bad — any string can be assigned
const [mode, setMode] = useState("standard");

// Good — only valid values compile
type RetrievalMode = "standard" | "hyde" | "multiquery";
const [mode, setMode] = useState<RetrievalMode>("standard");

// onChange handler
onChange={(e) => setMode(e.target.value as RetrievalMode)}
// The cast is safe because the select options are bounded
```

**Null safety:**
```tsx
// source.page is number | null from the API
{source.page && <span>, p.{source.page}</span>}
// Only renders if page is non-null and non-zero

// Better: explicit null check
{source.page !== null && <span>, p.{source.page}</span>}
```

---

## Quick reference

| Pattern | When to use |
|---------|-------------|
| `useEffect(fn, [])` | Fetch on mount |
| `Promise.all([...])` | Multiple independent requests |
| `setInterval` + cleanup | Status polling |
| `fetch` + `ReadableStream` | SSE token streaming |
| Axios interceptor | JWT attach + refresh |
| Optimistic update | Delete/toggle operations |
| `as const` / Literal types | Constrained API field values |
| `document.visibilitychange` | Pause polling when tab is hidden |
