# Day 5 — Next.js Frontend + Multi-Tenancy

## What We Built Today

| Component | File | Purpose |
|-----------|------|---------|
| Multi-tenancy | `app/models/document.py` | Added `user_id` FK on documents |
| Scoped queries | `app/services/rag_service.py` | All document ops filter by `user_id` |
| Scoped endpoints | `app/api/v1/endpoints/documents.py` | Auth required everywhere, user isolation |
| API client | `frontend/src/lib/api.ts` | Axios + auto token refresh interceptor |
| Auth helpers | `frontend/src/lib/auth.ts` | login/register/logout/getMe |
| Auth hook | `frontend/src/hooks/useAuth.ts` | React hook for protected pages |
| Types | `frontend/src/types/index.ts` | TypeScript interfaces for all API shapes |
| App layout | `frontend/src/app/(app)/layout.tsx` | Sidebar navigation, user info |
| Login page | `frontend/src/app/(auth)/login/page.tsx` | Email+password login form |
| Register page | `frontend/src/app/(auth)/register/page.tsx` | Account creation form |
| Dashboard | `frontend/src/app/(app)/dashboard/page.tsx` | Document upload/list/delete UI |
| Chat | `frontend/src/app/(app)/chat/page.tsx` | Streaming chat with conversation history |

---

## Multi-Tenancy — Why and How

### The Problem

Before today, any logged-in user could delete another user's document. The document model had no owner:

```python
# BEFORE — no owner field
class Document(Base):
    document_id: Mapped[str] = mapped_column(String(36), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    # ...
```

Any user hitting `DELETE /documents/{any-id}` could wipe someone else's work.

### The Fix — Add user_id Foreign Key

```python
# AFTER — documents are owned by a user
class Document(Base):
    document_id: Mapped[str]    = mapped_column(String(36), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"),
                                                nullable=True, index=True)
    filename: Mapped[str]       = mapped_column(String(255))
```

Why `nullable=True`? Old records in the DB have no `user_id`. Making it nullable prevents migration failures while allowing gradual adoption.

### Scoped Service Methods

```python
# BEFORE — anyone can access any document
async def get_document(self, db, document_id: str) -> Optional[Document]:
    result = await db.execute(
        select(Document).where(Document.document_id == document_id)
    )
    return result.scalar_one_or_none()

# AFTER — filtered by owner
async def get_document(self, db, document_id: str, user_id: Optional[int] = None):
    q = select(Document).where(Document.document_id == document_id)
    if user_id is not None:
        q = q.where(Document.user_id == user_id)
    result = await db.execute(q)
    return result.scalar_one_or_none()
```

With `user_id` filtering, if User A tries to access User B's document:
1. Query returns `None` (no row matches both `document_id` AND `user_id`)
2. Endpoint returns 404 — reveals nothing about whether the document exists

This is correct security behavior — don't leak information about other users' resources.

### Scoped Endpoints

```python
# documents.py
@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),   # ← auth required
):
    deleted = await rag_service.delete_document(db, document_id,
                                                user_id=current_user.id)  # ← scoped
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
```

The same `user_id` scoping applies to list, status check, and delete.

---

## Next.js App Router — Structure

```
frontend/src/
├── app/
│   ├── (auth)/            ← Route group — shared layout for login/register
│   │   ├── login/page.tsx
│   │   └── register/page.tsx
│   ├── (app)/             ← Route group — shared sidebar layout
│   │   ├── layout.tsx     ← Sidebar navigation (client component)
│   │   ├── dashboard/page.tsx
│   │   └── chat/page.tsx
│   ├── layout.tsx         ← Root layout (html, body)
│   ├── page.tsx           ← Root → redirects to /dashboard
│   └── globals.css
├── lib/
│   ├── api.ts             ← Axios instance + interceptors
│   └── auth.ts            ← Auth functions
├── hooks/
│   └── useAuth.ts         ← Auth state hook
└── types/
    └── index.ts           ← TypeScript interfaces
```

**Route groups `(auth)` and `(app)`:** Parentheses in folder names create route groups — they don't appear in the URL. `/dashboard` lives at `(app)/dashboard/page.tsx`, not at `/app/dashboard`. Groups exist purely to apply different layouts to different parts of the app.

**Layouts are nested:**
```
Root layout (html, body)
└── (app)/layout.tsx (sidebar)
    └── dashboard/page.tsx (page content)
```

The root layout wraps everything. The `(app)` layout adds the sidebar. The page renders inside the `{children}` slot.

---

## Axios Interceptors — Auto Token Management

```typescript
// lib/api.ts

// ── REQUEST interceptor: attach JWT to every call ──────────────────────────
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ── RESPONSE interceptor: refresh on 401, retry once ──────────────────────
api.interceptors.response.use(
  (res) => res,    // 2xx — pass through unchanged

  async (error) => {
    const original = error.config;

    // Only try refresh once (prevents infinite loop)
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      try {
        const refresh = localStorage.getItem("refresh_token");
        const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {
          refresh_token: refresh,
        });
        // Update stored tokens
        localStorage.setItem("access_token", data.access_token);
        localStorage.setItem("refresh_token", data.refresh_token);
        // Retry original request with new token
        original.headers.Authorization = `Bearer ${data.access_token}`;
        return api(original);    // ← retry
      } catch {
        // Refresh also failed → clear everything, redirect to login
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);
```

**Why `_retry` flag?** Without it: request fails with 401 → refresh → retry → retry also fails 401 → refresh again → infinite loop. `_retry = true` breaks the cycle.

**Why `axios.post` (not `api.post`) for refresh?** If we used `api.post`, the response interceptor would catch the refresh request's 401 and try to refresh... forever. Using the base `axios` bypasses our interceptor.

---

## SSE Streaming — Reading in the Browser

For streaming, we can't use Axios — it buffers the full response. We use the browser's native `fetch` API:

```typescript
// chat/page.tsx — streaming fetch

const res = await fetch(`${BASE_URL}/chat/stream`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  },
  body: JSON.stringify({ question, conversation_id: convId }),
});

const reader = res.body!.getReader();
const decoder = new TextDecoder();
let accumulated = "";

while (true) {
  const { done, value } = await reader.read();  // Uint8Array chunk
  if (done) break;

  const text = decoder.decode(value, { stream: true });  // decode bytes → string

  // Parse SSE lines: "data: <content>\n\n"
  const lines = text.split("\n");
  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    const payload = line.slice(6);    // remove "data: " prefix

    if (payload === "[DONE]") break;
    if (payload.startsWith("[SOURCES]")) {
      sources = JSON.parse(payload.slice(9));
    } else {
      accumulated += payload;
      // Update React state on every token — re-renders with new text
      setMessages((msgs) =>
        msgs.map((m) =>
          m.id === assistantId ? { ...m, content: accumulated } : m
        )
      );
    }
  }
}
```

**`TextDecoder({ stream: true })`:** Important flag. Without it, multi-byte UTF-8 characters split across two chunks would decode incorrectly. `stream: true` tells the decoder to hold incomplete byte sequences until the next chunk.

**Why update state on every token?** Each `setMessages` call triggers a React re-render. React batches rapid state updates in React 18, so updating 100 times/second won't cause 100 DOM updates — React coalesces them.

---

## React State Patterns Used

### Optimistic UI

```typescript
// Add user message immediately — before API responds
const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: question };
setMessages((m) => [...m, userMsg]);

// Add streaming placeholder
const assistantId = crypto.randomUUID();
setMessages((m) => [...m, { id: assistantId, role: "assistant", content: "", streaming: true }]);

// Update in-place as tokens arrive
setMessages((msgs) =>
  msgs.map((m) => m.id === assistantId ? { ...m, content: accumulated } : m)
);
```

The key insight: immutable updates. Never mutate the existing array — always return a new one with `.map()`. React uses reference equality to detect changes.

### Polling for Document Status

```typescript
useEffect(() => {
  fetchDocs();
  pollRef.current = setInterval(fetchDocs, 3000);
  return () => {
    if (pollRef.current) clearInterval(pollRef.current);  // cleanup on unmount
  };
}, []);
```

`useRef` for the interval ID (not `useState`) because changing the ref doesn't trigger re-renders.
The cleanup function prevents memory leaks — interval keeps running even after the component unmounts without it.

---

## Next.js App Router — Server vs Client Components

```typescript
// Default in App Router: Server Component
// - Renders on server, sends HTML to browser
// - Can be async, can fetch data directly (no useEffect needed)
// - Cannot use useState, useEffect, event handlers, browser APIs

export default async function ServerPage() {
  const data = await fetch("https://api.example.com/data");  // direct fetch, no useEffect
  return <div>{data}</div>;
}

// "use client" directive: Client Component
// - Renders in the browser (hydrated from server-rendered HTML)
// - Can use hooks, event handlers, browser APIs (localStorage, etc.)
// - Cannot be async at component level

"use client";
export default function ClientPage() {
  const [state, setState] = useState(...);  // hooks work here
  ...
}
```

**Our pages are all Client Components** because they:
- Use `useState` and `useEffect`
- Access `localStorage` for tokens
- Use `useRouter` for navigation
- Handle events (form submissions, button clicks)

In production, you'd use Server Components for the initial data fetch (faster, no loading states) and Client Components for interactive elements.

---

## Files Changed Today

```
backend/app/models/document.py              ← UPDATED: user_id FK added
backend/app/services/rag_service.py         ← UPDATED: all doc methods scoped by user_id
backend/app/api/v1/endpoints/documents.py   ← UPDATED: auth required + user_id passed through

frontend/                                   ← NEW: entire Next.js frontend
frontend/src/types/index.ts                 ← TypeScript interfaces
frontend/src/lib/api.ts                     ← Axios instance + interceptors
frontend/src/lib/auth.ts                    ← Auth functions
frontend/src/hooks/useAuth.ts               ← Auth state hook
frontend/src/app/layout.tsx                 ← Root layout
frontend/src/app/globals.css                ← Global styles (dark theme)
frontend/src/app/page.tsx                   ← Root redirect
frontend/src/app/(auth)/login/page.tsx      ← Login form
frontend/src/app/(auth)/register/page.tsx   ← Register form
frontend/src/app/(app)/layout.tsx           ← Sidebar layout
frontend/src/app/(app)/dashboard/page.tsx   ← Document management UI
frontend/src/app/(app)/chat/page.tsx        ← Streaming chat interface
```
