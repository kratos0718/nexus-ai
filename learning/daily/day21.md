# Day 21 — GitHub Actions CI/CD Pipeline

## What I Built

**Tests (backend):**
- `tests/test_system_prompts.py` — 11 tests for persona CRUD (create, list, get, update, delete, auth, ownership isolation)
- `tests/test_feedback.py` — 10 tests for feedback submission, stats, JSONL export, user isolation

**CI Workflow (`.github/workflows/ci.yml`):**
- **Job 1: lint** — `ruff check` for syntax/import errors (runs first, fastest)
- **Job 2: backend-tests** — pytest with `--cov` coverage reporting, fails under 40%
- **Job 3: frontend-checks** — `npx tsc --noEmit` TypeScript validation
- **Job 4: ci-passed** — summary gate that requires all 3 jobs; set this as branch protection check

**Dependencies added to `requirements-dev.txt`:**
- `aiosqlite` — async SQLite driver for in-memory test database
- `ruff` — fast Python linter (replaces flake8 + isort + pylint)
- `pytest-cov` — test coverage measurement

**Makefile:**
- `make test-cov` — run tests with coverage report
- `make lint` — run ruff lint
- `make lint-fix` — auto-fix ruff issues

---

## Key Decisions

**Why SQLite in-memory for CI tests?**
No external services to start. The ORM (SQLAlchemy) code is identical for SQLite and
PostgreSQL — only the connection URL changes. Tests run in ~5 seconds instead of needing
a Postgres container and migration setup.

**Why `needs: lint` on the test job?**
Fail fast. If imports are broken, lint fails in seconds and tests never start. Saves
2-3 minutes of runner time per bad push.

**Why `--cov-fail-under=40` and not 100%?**
The RAG pipeline, streaming endpoints, and background tasks are mocked in unit tests.
Full coverage of those paths needs integration tests with real services. 40% keeps the
threshold meaningful without demanding impossible coverage of external-service code.

**Why a `ci-passed` summary gate job?**
GitHub branch protection lets you require specific check names. One check name is easier
to manage than three. If you add a 4th job later, you only update `ci-passed`'s `needs:`
list — the branch protection rule doesn't change.

---

## How to Test Locally

```bash
# Run all tests
make test

# Run tests with coverage report
make test-cov

# Lint
make lint

# Lint and auto-fix
make lint-fix

# Run a specific test file
cd backend && pytest tests/test_system_prompts.py -v

# Run tests matching a keyword
cd backend && pytest tests/ -k "feedback" -v
```

---

## Concepts Learned

- GitHub Actions: workflows, jobs, steps, triggers, runners, artifacts
- `needs:` for job dependencies (sequential jobs with parallel sub-jobs)
- `npm ci` vs `npm install` — reproducibility in CI
- Dependency caching with `actions/setup-python` and `actions/setup-node`
- `--cov-fail-under` — coverage gate that prevents regressions
- `${{ secrets.KEY }}` for storing API keys safely
- `if: always()` on artifact upload — get reports even on failure

---

## Resume Bullets

- Designed and implemented 4-job GitHub Actions CI/CD pipeline: lint → test → TypeScript check → summary gate
- Wrote 21 pytest tests for system prompts and feedback endpoints (ownership isolation, auth enforcement, JSONL export)
- Configured pytest-cov with 40% minimum threshold; added ruff linting to prevent import and style regressions
- Set up in-memory SQLite test strategy using aiosqlite + dependency override pattern for fast, isolated tests

---

## Interview Q&As

**Q276: What is GitHub Actions and how does a workflow work?**
GitHub Actions is a CI/CD system built into GitHub. A workflow is a YAML file in
`.github/workflows/`. It triggers on events (push, pull_request), runs jobs on virtual
machines (runners), and each job has steps that run shell commands or reusable Actions.
Jobs run in parallel by default; `needs:` makes them sequential.

**Q277: What is the difference between `npm install` and `npm ci`?**
`npm install` resolves versions from `package.json` and can update `package-lock.json`.
`npm ci` reads exact versions from `package-lock.json` and fails if it's out of sync.
In CI/CD, always use `npm ci` for reproducibility — same deps every run.

**Q278: How do you keep API keys secure in a GitHub Actions workflow?**
Store them in GitHub repository Secrets (Settings → Secrets → Actions). Reference them
in the workflow as `${{ secrets.MY_KEY }}`. They're never printed in logs and don't
appear in the YAML. For local dev, use a `.env` file that is git-ignored.

**Q279: How do you test a FastAPI application that depends on a real database?**
Use SQLAlchemy's `Base.metadata.create_all` on a SQLite in-memory engine in a pytest
fixture. Override FastAPI's `get_db` dependency to yield a session connected to that
test database. Each test function gets a fresh, isolated database that's dropped after
the test. The app code doesn't know — it just receives an `AsyncSession`.

**Q280: What is test coverage and what is a realistic target for an AI backend?**
Coverage is the % of code lines executed by tests. 100% is the theoretical max but
impractical for AI backends where ML pipeline initialization, streaming generators, and
external API calls require real infrastructure. A 40-60% threshold with 80%+ on critical
paths (auth, API endpoints) is realistic. The key metric is that coverage doesn't
decrease — a downward trend signals untested new code.
