# CI/CD — From Zero to Production Pipelines

## What Is CI/CD?

**CI = Continuous Integration** — every code change is automatically tested before it merges.
**CD = Continuous Delivery/Deployment** — every passing change is automatically deployed.

Real-world analogy: CI is the safety inspector who checks every batch of products off the
assembly line. CD is the forklift that ships the approved batch to the warehouse automatically.

Without CI/CD: developers push code, it works on their machine, breaks in production.
With CI/CD: every push triggers a robot that runs tests in a clean environment.

---

## 1. GitHub Actions — How It Works

GitHub Actions is GitHub's built-in CI/CD system. Free for public repos, 2000 minutes/month free for private.

**Key concepts:**

| Concept     | What it is                                         | Example                        |
|-------------|---------------------------------------------------|-------------------------------|
| Workflow    | A YAML file defining the pipeline                 | `.github/workflows/ci.yml`    |
| Trigger     | Event that starts the workflow                    | `push`, `pull_request`        |
| Job         | A group of steps that run on one machine          | `backend-tests`, `lint`       |
| Step        | One command or action inside a job               | `pip install`, `pytest`       |
| Action      | Reusable plugin for a step                        | `actions/checkout@v4`         |
| Runner      | The virtual machine that runs the job             | `ubuntu-latest`               |
| Needs       | Job dependency — this job waits for another       | `needs: lint`                 |
| Artifact    | File saved after the job runs                     | `coverage.xml`                |

**Workflow file anatomy:**
```yaml
name: CI                          # shown in GitHub UI

on:                               # triggers
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  my-job:                         # job ID
    name: Human-readable name
    runs-on: ubuntu-latest        # runner OS

    defaults:
      run:
        working-directory: backend  # all steps run from here

    steps:
      - uses: actions/checkout@v4   # clone the repo
      - name: Install
        run: pip install -r requirements.txt
      - name: Test
        run: pytest tests/
```

---

## 2. The Three Jobs in Nexus AI's CI

### Job 1: Lint (`ruff`)
- Runs first, fastest (no dependencies to install)
- Catches syntax errors, unused imports, style issues
- If this fails, tests don't even start → save runner time

**Ruff rules used:**
- `E` — pycodestyle errors (indentation, syntax)
- `F` — Pyflakes (undefined names, unused imports)
- `W` — Pyflakes warnings
- `I` — isort (import order)
- `--ignore E501` — skip line length (teams often relax this)

### Job 2: Backend Tests + Coverage
- Runs AFTER lint passes (`needs: lint`)
- Uses in-memory SQLite so no real database is needed
- Generates `coverage.xml` uploaded as artifact
- `--cov-fail-under=40` — fails if coverage drops below 40%

**Test environment strategy:**
```yaml
env:
  DATABASE_URL: "sqlite+aiosqlite:///:memory:"   # no real DB
  GROQ_API_KEY: "dummy"                           # not called in unit tests
  SECRET_KEY: "ci-test-secret-key"                # needed for JWT signing
```

### Job 3: Frontend Type Check (`tsc --noEmit`)
- Runs `npx tsc --noEmit` — checks TypeScript types without emitting files
- Catches type errors that don't crash the app but will cause runtime bugs
- Uses `npm ci` (not `npm install`) — reproducible, reads exact package-lock.json

### Summary gate: `ci-passed`
- A single job that `needs: [lint, backend-tests, frontend-checks]`
- Set THIS as the required status check in GitHub branch protection
- One check to rule them all — simpler than listing 3 required checks

---

## 3. Test Coverage

Coverage = % of your code lines that are executed when tests run.

```
app/api/v1/endpoints/auth.py       82%
app/api/v1/endpoints/feedback.py   91%
app/core/security_guard.py         96%
TOTAL                              47%
```

**Why not 100%?**
- The RAG pipeline imports heavy ML models — mocking them is complex
- Background tasks and streaming paths are hard to test without real infrastructure
- 40-60% is a realistic target for an AI/ML backend; 70%+ for critical paths

**`--cov-fail-under=40`** — a floor, not a target. Fails CI if coverage drops,
keeping the team honest without demanding perfection.

---

## 4. Dependency Caching

Without caching: every run installs all packages from scratch (60–120 seconds).
With caching: packages are restored from cache in ~5 seconds.

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
    cache: "pip"
    cache-dependency-path: backend/requirements-dev.txt
```

GitHub hashes `requirements-dev.txt`. When it changes, cache is busted.
When it doesn't change, packages are restored instantly.

Same for Node:
```yaml
- uses: actions/setup-node@v4
  with:
    node-version: "20"
    cache: "npm"
    cache-dependency-path: frontend/package-lock.json
```

---

## 5. `npm ci` vs `npm install`

| Command       | Reads            | Behavior                                    |
|---------------|------------------|---------------------------------------------|
| `npm install` | `package.json`   | Updates package-lock.json, installs          |
| `npm ci`      | `package-lock.json` | Exact versions, never updates lock file    |

In CI: always `npm ci`. It's faster and reproducible — same versions every run.

---

## 6. Branch Protection Rules

After setting up CI, protect your main branch in GitHub:
`Settings → Branches → Add protection rule → Require status checks to pass → ci-passed`

Effect: PRs cannot be merged until CI is green. Direct pushes to main are blocked.
This is the standard practice at any company with a real engineering process.

---

## 7. CI/CD for AI/ML Projects — Special Considerations

**Problem 1: ML models are huge (GB)**
Solution: mock the model in tests. Use `unittest.mock.patch` to replace the
pipeline with a function that returns fake data.

```python
with patch("app.services.rag_service.RAGService.index_file_background", new_callable=AsyncMock):
    res = await client.post("/upload", files=...)
```

**Problem 2: API keys shouldn't be in the repo**
Solution: GitHub Secrets. Set `GROQ_API_KEY` in repo Settings → Secrets.
Reference in workflow: `${{ secrets.GROQ_API_KEY }}`.
For tests that don't actually call the API, use a dummy value.

**Problem 3: Tests are slow with real vector DBs**
Solution: use SQLite in-memory for all relational data. For vector store,
mock at the service layer — don't let tests hit ChromaDB or Pinecone.

**Problem 4: Async tests**
Solution: `pytest-asyncio` with `asyncio_mode = auto` in `pytest.ini`.
Every `async def test_*` runs inside an event loop automatically.

---

## 8. CD — What Comes Next (Day 22)

Continuous Deployment adds a deploy step after tests pass:
```yaml
  deploy:
    needs: [lint, backend-tests, frontend-checks]
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - name: Deploy to Railway
        run: railway up --service backend
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
```

The `if:` condition makes sure it only deploys on push to main, not on PRs.
This is the "Continuous Delivery" model — code ships automatically on every green build.

---

## 9. Artifacts and Reports

Artifacts are files saved after a job runs. Useful for:
- Coverage reports (`coverage.xml`) — can be picked up by Codecov or SonarQube
- Build logs
- Test result XML

```yaml
- uses: actions/upload-artifact@v4
  if: always()          # upload even if tests fail (so you can debug)
  with:
    name: coverage-report
    path: backend/coverage.xml
```

`if: always()` ensures the artifact is uploaded even when the step before it fails.

---

## Interview Questions

**Q: What's the difference between CI and CD?**
CI validates that code is correct (tests pass, types check). CD automates shipping
that validated code to a server. CI without CD means you still deploy manually.
CD without CI means you ship untested code automatically — dangerous.

**Q: Why does the lint job run before the test job?**
Fail fast. Lint is cheap (seconds, no installs). If imports are broken or syntax is
wrong, there's no point spending 3 minutes running tests. `needs: lint` makes tests
block on lint — saves runner minutes and gives faster feedback.

**Q: What is `npm ci` and why not `npm install` in CI?**
`npm ci` installs exact versions from `package-lock.json` without ever modifying it.
`npm install` can update the lock file and install slightly different versions. In CI
you want reproducibility — same code, same deps, same result every time.

**Q: Why use SQLite in-memory for CI tests instead of PostgreSQL?**
No services to start, no Docker required, zero setup time. The SQLAlchemy ORM code is
the same for both — only the connection URL changes. For production-specific behavior
(JSONB, full-text search), integration tests against a real PostgreSQL instance are added
separately, but unit tests run faster with SQLite.

**Q: How do you keep secrets out of the CI workflow YAML?**
GitHub Secrets (or equivalent in GitLab/CircleCI). Store sensitive values in the
repository settings, reference them as `${{ secrets.KEY_NAME }}`. They're masked in
logs and never appear in the YAML file itself.

**Q: What does `--cov-fail-under=40` mean and why not set it to 100%?**
It means pytest fails if test coverage drops below 40%. 100% coverage is often
impractical for AI backends — ML pipeline code, streaming paths, and external API calls
are hard to test without real infrastructure. A minimum threshold prevents regressions
(coverage trending down) without demanding perfection in non-critical paths.
