# Day 9 — Rate Limiting + Smart Conversation Management

**Date:** 2026-05-21  
**Focus:** Protecting the API + making conversations feel intelligent

---

## What I Built

### 1. Redis Rate Limiting (`app/core/rate_limit.py`)
- Per-user: 100 requests/hour (authenticated users)
- Per-IP: 30 requests/hour (fallback, not currently wired for anonymous)
- Fixed window counter using Redis INCR (atomic, no race conditions)
- Returns `Retry-After` seconds so clients know when to retry
- Silently allows requests if Redis is down (graceful degradation)

### 2. `rate_limit_user` FastAPI Dependency (`app/core/dependencies.py`)
- Chains `get_current_user` + `check_rate_limit` into a single dependency
- Endpoints swap `Depends(get_current_user)` → `Depends(rate_limit_user)` — one word change
- Applied to `/chat/query`, `/chat/stream`, `/agent/query`, `/agent/stream`

### 3. Conversation History Window (`app/services/rag_service.py`)
- `_build_history()` now caps at the last 10 messages
- Prevents context overflow when a conversation gets long
- Old messages are dropped — the LLM only sees the most recent 5 turns (10 messages = 5 user + 5 assistant)

### 4. Auto-Title Conversations (`app/services/rag_service.py`)
- `_auto_title_conversation()` sends the first question to Groq and gets a 4-6 word title back
- Fires as a FastAPI BackgroundTask after the first query response — non-blocking
- Only triggers when conversation title is still "New Conversation"
- Title capped at 80 characters for DB storage

### 5. Conversation Rename Endpoint (`PATCH /conversations/{id}/title`)
- Users can manually rename any conversation they own
- Title trimmed and capped at 80 characters

---

## Architecture Impact

```
Before Day 9:
  Request → get_current_user → endpoint logic

After Day 9:
  Request → get_current_user → check_rate_limit → endpoint logic
                                      ↓
                              Redis INCR (atomic)
                              429 if over limit
```

```
Before: history = all messages (could be 100+)
After:  history = last 10 messages (controlled context window)
```

---

## Files Changed

```
backend/app/core/rate_limit.py              ← NEW: Redis fixed-window rate limiter
backend/app/core/dependencies.py            ← UPDATED: rate_limit_user dependency
backend/app/api/v1/endpoints/chat.py        ← UPDATED: rate_limit_user + auto-title trigger
backend/app/api/v1/endpoints/agent.py       ← UPDATED: rate_limit_user
backend/app/api/v1/endpoints/conversations.py ← UPDATED: rename endpoint added
backend/app/schemas/conversation.py        ← UPDATED: ConversationRename schema
backend/app/services/rag_service.py        ← UPDATED: history window + auto_title method
learning/concepts/16_rate_limiting.md      ← NEW
```

---

## Concepts Learned

- **Fixed window counter**: floor(timestamp / window) as key suffix = auto-reset
- **INCR atomicity**: Redis INCR is single-threaded → no race conditions under concurrency
- **Burst problem**: fixed window allows 2x burst at boundaries (sliding window solves it)
- **FastAPI dependency chaining**: `Depends(A)` inside a function that is itself used as `Depends` — chains automatically
- **Context window management**: LLMs have token limits; long conversations must be trimmed
- **BackgroundTasks for non-critical work**: auto-titling is nice-to-have, not blocking

---

## Interview Angles

**"How do you prevent a single user from abusing your AI API?"**
→ Redis-based rate limiting per user ID (100 req/hour). Fixed window counter — INCR is atomic so it works across multiple API workers. Returns 429 with Retry-After header. If Redis is down, degrades gracefully by allowing requests.

**"What happens when a conversation gets very long?"**
→ We cap the history passed to the LLM at the last 10 messages. This prevents context overflow and keeps inference costs predictable. The full history is still stored in the DB — just not all of it is sent to the model.

**"How do you auto-generate conversation titles?"**
→ After the first message exchange, we fire a FastAPI BackgroundTask that sends the user's first question to Groq with a prompt like "Generate a 4-6 word title for this conversation." The response is saved back to the conversation. It runs after the HTTP response is returned so the user doesn't wait for it.
