# Concept 9 — Next.js App Router

## Pages Router vs App Router

Next.js has two routing systems. You'll see both in the wild.

| | Pages Router (old) | App Router (new, default since v13) |
|--|--|--|
| Directory | `pages/` | `app/` |
| Default component type | Client | Server |
| Layouts | `_app.tsx` (one global) | `layout.tsx` per folder (nested) |
| Data fetching | `getServerSideProps` / `getStaticProps` | `async` component body |
| Streaming | Not built-in | Built-in via `Suspense` |

Use App Router for new projects. Pages Router still works but is legacy.

---

## File Conventions

```
app/
├── layout.tsx        ← Persistent shell (navbar, sidebar) — renders around {children}
├── page.tsx          ← Route's UI — rendered inside parent layout
├── loading.tsx       ← Shown while page.tsx is loading (Suspense boundary)
├── error.tsx         ← Shown when page.tsx throws (Error boundary)
├── not-found.tsx     ← Rendered by notFound() helper
└── route.ts          ← API route handler (replaces pages/api/)
```

Special files are co-located with their route — no separate `pages/api/` directory needed.

---

## Nested Layouts

```
app/
├── layout.tsx              ← Root: <html><body>{children}</body></html>
├── (app)/
│   ├── layout.tsx          ← App shell: <Sidebar>{children}</Sidebar>
│   ├── dashboard/
│   │   └── page.tsx        ← Dashboard content
│   └── chat/
│       └── page.tsx        ← Chat content
└── (auth)/
    ├── login/
    │   └── page.tsx        ← Login form (no sidebar)
    └── register/
        └── page.tsx
```

Visiting `/dashboard`:
1. Root `layout.tsx` renders `<html><body>...</body></html>`
2. `(app)/layout.tsx` renders the sidebar
3. `dashboard/page.tsx` renders in the sidebar's `{children}` slot

Visiting `/login`:
1. Root `layout.tsx` renders
2. `(auth)` group has NO layout — login renders without sidebar

**Route groups `(name)`:** Parentheses = URL-invisible. `/dashboard` not `/app/dashboard`. Groups share a layout without affecting the URL.

---

## Server Components vs Client Components

**Server Components (default):**
```typescript
// No "use client" → Server Component
// - Rendered on the server only
// - Can be async, use await directly
// - Can access databases, secrets, file system directly
// - Smaller JS bundle (component code never sent to browser)
// - CANNOT: useState, useEffect, onClick, browser APIs

export default async function ProductPage({ params }: { params: { id: string }}) {
  const product = await db.query(`SELECT * FROM products WHERE id = ${params.id}`);
  return <h1>{product.name}</h1>;
}
```

**Client Components:**
```typescript
"use client";  // ← must be first line
// - Hydrated in the browser
// - CAN: useState, useEffect, event handlers, browser APIs
// - CANNOT: be async at component level, access server-only resources

export default function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(c => c + 1)}>{count}</button>;
}
```

**The boundary rule:** A Client Component can only import other Client Components (or shared components). A Server Component can import both. This means interactivity must be pushed to the leaves of the component tree.

```
Layout (Server) → Sidebar (Server) → SignOutButton (Client ← must be "use client")
```

---

## Data Fetching Patterns

### Server Component (recommended for initial data)
```typescript
// app/products/page.tsx — Server Component
export default async function ProductsPage() {
  // Direct fetch — no useEffect, no useState, no loading state
  const res = await fetch("https://api.example.com/products", {
    next: { revalidate: 60 },  // ISR: re-fetch every 60 seconds
  });
  const products = await res.json();
  return <ProductList products={products} />;
}
```

### Client Component with useEffect (our approach for auth-gated pages)
```typescript
"use client";
export default function Dashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/documents/").then(({ data }) => {
      setData(data);
      setLoading(false);
    });
  }, []);

  if (loading) return <Spinner />;
  return <DocumentList docs={data} />;
}
```

We use Client Components because our data requires a JWT in the request header — that token is in `localStorage`, which only exists in the browser, so we can't fetch it server-side.

In production with cookies-based auth (HttpOnly), you could use Server Components with cookies.

---

## The `next/navigation` Hooks

These replace the Pages Router's `useRouter` from `next/router`.

```typescript
import { useRouter, usePathname, useSearchParams } from "next/navigation";

// useRouter: programmatic navigation
const router = useRouter();
router.push("/dashboard");       // navigate to route
router.replace("/login");        // navigate without adding to history
router.back();                   // go back

// usePathname: current URL path
const pathname = usePathname();  // "/dashboard"

// useSearchParams: URL query params
const params = useSearchParams();
const page = params.get("page"); // ?page=2 → "2"
```

Note: `redirect()` from `next/navigation` works in Server Components and throws a special error that Next.js catches — don't try/catch it.

---

## Link Component vs `router.push`

```typescript
// Link — renders an <a> tag, prefetches on hover, no JS needed for navigation
<Link href="/dashboard">Go to Dashboard</Link>

// router.push — programmatic, requires JS, used after events
async function handleLogin() {
  await login(email, password);
  router.replace("/dashboard");  // redirect after successful login
}
```

Use `<Link>` for visible navigation. Use `router.push` for navigation after events (form submit, button click).

---

## Interview Questions on Next.js

**Q: What is the difference between SSR, SSG, and ISR?**
A: SSR (Server-Side Rendering) — renders HTML on every request. SSG (Static Site Generation) — renders at build time, same HTML for all users. ISR (Incremental Static Regeneration) — SSG with revalidation: HTML is static until the `revalidate` period, then regenerated in the background. Next.js App Router uses `fetch` cache options to control this: `cache: "no-store"` = SSR, `next: { revalidate: N }` = ISR, default = SSG.

**Q: When would you use a Server Component vs a Client Component?**
A: Server Component: data fetching, database access, secret keys, heavy computation (no JS sent to browser). Client Component: interactivity (onClick, onChange), hooks (useState, useEffect), browser APIs (localStorage, window). Rule of thumb: push interactivity to the leaves — keep layout and data fetching in Server Components.

**Q: What is hydration?**
A: The browser receives the server-rendered HTML (which is static/inert). React then "hydrates" it by attaching event listeners and state, making it interactive. If the client-rendered output doesn't match the server-rendered HTML, React logs a hydration warning. Common cause: using `localStorage` or `window` during server render (they don't exist server-side).

**Q: How do you protect routes in Next.js?**
A: Three approaches: (1) Middleware (`middleware.ts`) — runs before every request, checks token, redirects to login. (2) Layout-level check — `useEffect` in a Client layout checks auth and redirects. (3) Server Component check — read cookie, verify token, redirect if invalid. Middleware is most reliable and runs before any component code.
