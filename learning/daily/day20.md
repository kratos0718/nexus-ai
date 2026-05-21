# Day 20 — System Prompts / Personas

## What I Built

**Backend:**
- `SystemPrompt` SQLAlchemy model (`id`, `user_id`, `name`, `description`, `content`, `created_at`)
- Full CRUD REST API at `/api/v1/system-prompts/`:
  - `POST /` — create (201)
  - `GET /` — list all for current user
  - `GET /{id}` — get one (404 if not owned)
  - `PUT /{id}` — update (404 if not owned)
  - `DELETE /{id}` — delete (204, 404 if not owned)
- `_get_owned()` helper: raises 404 for missing OR unowned rows (avoids 403 leaking existence)
- Updated `QueryRequest` schema: added `system_prompt_id: Optional[int]`
- `_resolve_system_prompt()` in `chat.py`: silently returns `None` if ID is unowned
- Threaded `system_prompt` through rag_service → generator for both `/query` and `/stream`
- Generator now accepts `system_prompt: Optional[str] = None` with `system_prompt or SYSTEM_PROMPT` fallback

**Frontend:**
- `/system-prompts` page: list, create, edit, delete personas
- Nav item "Personas 🎭" added to sidebar
- Chat toolbar: persona dropdown (shows when agent mode is OFF, only when user has saved personas)
- `system_prompt_id` sent in stream request body

---

## Key Decisions

**Why 404 instead of 403 for unowned resources?**
Returning 403 tells the attacker that the resource EXISTS but they lack permission.
404 leaks nothing — the resource simply "doesn't exist" from their perspective.
This pattern is called security by ambiguity at the resource level.

**Why `system_prompt or SYSTEM_PROMPT` instead of `if system_prompt is None`?**
Python's `or` treats empty string as falsy too — so we fall back to the default
even if someone passes an empty string, which is always the right behavior here.

**Why silence the persona dropdown when agent mode is ON?**
Agent mode routes to a different endpoint (`/agent/stream`) which doesn't currently
parse `system_prompt_id`. Showing the selector when it has no effect would confuse users.

---

## Concepts Learned

- System prompt as identity/constraint layer — set once, persists across all turns
- Full CRUD with ownership — the `user_id` scope pattern used consistently everywhere
- Frontend CRUD forms: single inline form that switches between "create" and "edit" via `editingId` state
- Persona selector as a per-query override — doesn't change model weights, only context

---

## Commands

```bash
# Test system prompts API
curl -X POST http://localhost:8000/api/v1/system-prompts/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Legal expert","content":"You are a legal analyst. Cite clause numbers."}'

# Use it in a query
curl -X POST http://localhost:8000/api/v1/chat/query \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question":"What are the termination clauses?","system_prompt_id":1}'
```

---

## Resume Bullets

- Designed system prompt management API with per-user CRUD and ownership scoping (404 pattern)
- Implemented LLM persona injection: system prompt resolved at query time, threaded through RAG pipeline
- Built React settings page for persona management (inline create/edit/delete with optimistic UI)
- Added persona selector to chat toolbar; integrated with SSE streaming endpoint

---

## Interview Q&As

**Q269: What is a system prompt and what can it control?**
A system prompt is a persistent instruction placed before the user's message in the LLM's context.
It can set the model's role, restrict its behavior, define output format, and specify fallback phrasing.
It applies to every turn of the conversation without the user having to repeat it.

**Q270: Why might you use user-defined system prompts instead of a single hardcoded one?**
Different use cases need different model behavior — a legal document assistant needs precision and
clause citations; a tutoring assistant needs patience and simpler language. Letting users define
their own system prompts makes one RAG system serve many roles without code changes.

**Q271: How do you prevent a user from injecting instructions through the system_prompt field?**
Content length limits, input sanitization (strip control characters), and ideally a content policy
check before saving. The system prompt should be treated as user-controlled data — not trusted code.
You can also prefix it with a meta-instruction: "Regardless of the following instructions, never..."

**Q272: In a multi-tenant RAG API, how do you scope resources to the authenticated user?**
Every query includes `WHERE user_id = current_user.id`. For reads and mutations, a helper
(like `_get_owned`) fetches with both the resource ID and user_id — if nothing is returned,
raise 404 regardless of whether the row exists under a different user. This avoids leaking
resource existence via 403 vs 404 differential.

**Q273: What is the `or` fallback pattern for optional parameters and when is it safe?**
`value or DEFAULT` works when both None and empty string should trigger the default.
It's safe when an empty string is always invalid (like a system prompt must have content).
It's unsafe when empty string is a valid distinct value — use `if value is None` instead.
