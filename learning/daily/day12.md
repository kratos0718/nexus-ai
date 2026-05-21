# Day 12 — Security + CI/CD

**Date:** 2026-05-21  
**Focus:** Prompt injection protection, SSRF/file security, automated testing pipeline

---

## What We Built

### 1. SecurityGuard (`app/core/security_guard.py`)

Three validation methods, each raising HTTP 400 on failure:

**`validate_question(question)`** — called on every chat/agent request:
- Empty question → 400
- Length > 2000 chars → 400 (blocks token-stuffing attacks)
- 11 prompt injection regex patterns → 400
- Strips null bytes and control characters
- Returns sanitized, stripped question

**`validate_file_bytes(data, extension)`** — called after file upload:
- Checks magic bytes match declared extension
- `.pdf` must start with `%PDF`
- `.docx` must start with `PK\x03\x04` (ZIP container)
- `.txt`/`.md` — no reliable magic, skipped
- Blocks MIME-type spoofing (`.exe` renamed to `.pdf`)

**`validate_url(url)`** — called before URL indexing:
- Blocks private IP ranges: `localhost`, `127.x`, `10.x`, `192.168.x`, `172.16-31.x`
- Prevents SSRF (server fetching internal metadata/services)

### 2. Wired into endpoints

- `POST /chat/query` + `POST /chat/stream` → `validate_question()`
- `POST /agent/query` + `POST /agent/stream` → `validate_question()`
- `POST /documents/upload` → `validate_file_bytes()`
- `POST /documents/url` → `validate_url()`

The sanitized `question` variable replaces `request.question` throughout
the handler — the LLM never sees the raw, unvalidated string.

### 3. Security tests (`tests/test_security.py`)

27 tests covering all guard methods:
- Valid inputs pass through
- Empty/too-long inputs blocked
- 13 different injection patterns all blocked
- Legitimate questions with "instruction" words pass (no false positives)
- SSRF URLs blocked, public URLs pass
- Magic byte checks for PDF/DOCX, skip for TXT/MD

### 4. GitHub Actions CI (`.github/workflows/ci.yml`)

Runs on every push to `main` and every PR:
1. Checks out code
2. Sets up Python 3.12 with pip cache
3. Installs `requirements-dev.txt`
4. Runs `pytest tests/ -v --tb=short -x`
5. Checks app imports cleanly

Uses SQLite in-memory for tests — no external DB service needed in CI.
`GROQ_API_KEY: "dummy"` — unit tests mock the pipeline, no real calls.

---

## Files Changed / Created

```
backend/app/core/security_guard.py              ← NEW: SecurityGuard class
backend/app/api/v1/endpoints/chat.py            ← UPDATED: validate_question on both endpoints
backend/app/api/v1/endpoints/agent.py           ← UPDATED: validate_question on both endpoints
backend/app/api/v1/endpoints/documents.py       ← UPDATED: validate_file_bytes + validate_url
backend/tests/test_security.py                  ← NEW: 27 security tests
.github/workflows/ci.yml                        ← NEW: GitHub Actions CI pipeline
learning/concepts/19_security_prompt_injection.md ← NEW (8 levels)
learning/concepts/20_cicd_github_actions.md       ← NEW (8 levels)
```

---

## Defense in Depth — What Protects Against What

```
Attack                    →  Defense
─────────────────────────────────────────────────────
Prompt injection          →  SecurityGuard.validate_question() + system prompt
Jailbreak attempt         →  11 regex patterns + system prompt framing
System prompt extraction  →  Regex block + explicit "never reveal" in prompt
Token stuffing (cost DoS) →  2000 char limit + rate limiting (Day 9)
SSRF via URL indexing     →  SecurityGuard.validate_url() private IP blocklist
MIME type spoofing        →  SecurityGuard.validate_file_bytes() magic bytes
Unauthenticated access    →  JWT (get_current_user dependency)
API abuse / scraping      →  Rate limiting (rate_limit_user dependency)
Cross-user data leak      →  user_id filter on all DB queries
```

---

## Interview Angles

**"How do you protect against prompt injection?"**
→ Three-layer defense: (1) input guard with 11 regex patterns blocks known injection phrases before they reach the LLM, (2) system prompt explicitly instructs the LLM to refuse persona changes and never reveal its instructions, (3) all LLM calls are logged in the traces table so suspicious patterns are detectable post-hoc. No single layer is sufficient — attackers can bypass any one; the combination raises the cost of attack.

**"What is SSRF and how do you prevent it?"**
→ Server-Side Request Forgery: an attacker makes our server fetch a URL they control — often targeting internal services like AWS metadata at 169.254.169.254. Our URL indexing feature is an SSRF vector. We block private IP ranges (localhost, 10.x, 192.168.x, 172.16-31.x) with a regex before making any HTTP request to user-provided URLs.

**"How does your CI pipeline work?"**
→ GitHub Actions triggers on every push to main and every PR. It runs in a fresh Ubuntu VM, installs Python 3.12 and our dev dependencies, then runs the full test suite with pytest. Tests use SQLite in-memory so no external services are needed. If any test fails, the PR is blocked from merging (with branch protection rules enabled). The whole pipeline takes about 90 seconds.
