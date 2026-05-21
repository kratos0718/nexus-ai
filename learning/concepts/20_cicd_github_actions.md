# CI/CD with GitHub Actions

## LEVEL 1 — What Problem Does CI/CD Solve?

Without CI/CD:
```
Developer writes code → pushes to GitHub → manually tests locally
                                         → forgets to test → bug reaches prod
                                         → tests pass locally but not in CI env
```

With CI/CD:
```
Developer pushes code → GitHub automatically:
  1. Installs dependencies in a clean environment
  2. Runs all tests
  3. Blocks the merge if tests fail
  4. (CD) Deploys automatically if everything passes
```

CI = Continuous Integration: automatically test every change.
CD = Continuous Delivery/Deployment: automatically ship changes that pass CI.

The core value: **you can't merge broken code** (if you enforce branch protection).

---

## LEVEL 2 — GitHub Actions Concepts

### Workflow
A YAML file in `.github/workflows/`. Defines what to run and when.

### Trigger (`on:`)
What event starts the workflow:
```yaml
on:
  push:
    branches: [main]        # runs when you push to main
  pull_request:
    branches: [main]        # runs when a PR targets main
  schedule:
    - cron: "0 6 * * *"    # runs daily at 6am UTC
  workflow_dispatch:         # allows manual trigger from GitHub UI
```

### Job
A unit of work that runs on one machine (runner). Jobs run in parallel by
default. Use `needs:` to create dependencies between jobs.

### Step
One command or action within a job. Steps run sequentially.

### Runner
The machine that runs the job. `ubuntu-latest` is a fresh Ubuntu VM.
GitHub provides Linux, Windows, macOS runners for free (limited minutes).

### Action
A reusable step defined by someone else. `actions/checkout@v4` clones your
repo. `actions/setup-python@v5` installs Python. You can write your own.

---

## LEVEL 3 — Nexus CI Workflow Breakdown

```yaml
name: CI                           # shown in GitHub UI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest         # fresh Ubuntu VM for each run

    defaults:
      run:
        working-directory: backend # all `run:` steps cd here first

    steps:
      - uses: actions/checkout@v4  # clone the repo

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"             # cache pip downloads between runs
          cache-dependency-path: backend/requirements-dev.txt

      - name: Install dependencies
        run: pip install -r requirements-dev.txt

      - name: Run tests
        env:
          DATABASE_URL: "sqlite+aiosqlite:///:memory:"
          GROQ_API_KEY: "dummy-not-needed-for-unit-tests"
        run: pytest tests/ -v --tb=short -x

      - name: Check import hygiene
        run: python -c "from app.main import app; print('App imports OK')"
```

### Why SQLite in CI?

Our tests use SQLite in-memory (`sqlite+aiosqlite:///:memory:`), not PostgreSQL.
This means:
- No database service to start in CI
- Tests run in milliseconds
- Each test gets a fresh database (no contamination between tests)
- No credentials to manage in CI secrets

The tradeoff: SQLite behavior differs from PostgreSQL in edge cases
(no `RETURNING` in older SQLite, different locking, etc.). For production
confidence, run integration tests against a real PostgreSQL service in CI.

### `pytest -x` flag

`-x` = stop on first failure. Without it, pytest runs all tests and shows
all failures at the end. With `-x`, you see the first failure immediately
and don't wait for the rest. Good for CI where you just need pass/fail.

---

## LEVEL 4 — Caching Dependencies

```yaml
- uses: actions/setup-python@v5
  with:
    cache: "pip"
    cache-dependency-path: backend/requirements-dev.txt
```

Without cache: CI downloads and installs all packages from PyPI on every run.
For a project with 50+ packages, this takes 2-3 minutes.

With cache: GitHub stores the pip download cache after the first run.
Subsequent runs restore from cache if `requirements-dev.txt` hasn't changed.
Cache hit: ~10 seconds instead of 2-3 minutes.

Cache key: GitHub automatically hashes the `cache-dependency-path` file.
If `requirements-dev.txt` changes, the cache is invalidated and rebuilt.

---

## LEVEL 5 — Environment Variables and Secrets

### Public env vars (in workflow file)
```yaml
env:
  DATABASE_URL: "sqlite+aiosqlite:///:memory:"
  GROQ_API_KEY: "dummy-not-needed-for-unit-tests"
```

Fine for test values that aren't secret. Visible in the workflow file and logs.

### GitHub Secrets (for real credentials)
Store in GitHub → Settings → Secrets and variables → Actions:
```yaml
env:
  GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
  DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

Secrets are:
- Encrypted at rest
- Never logged (GitHub masks them in output)
- Only accessible to workflows in the same repo
- Not passed to PRs from forks (security: anyone can fork and make a PR)

### When to use fake vs real values in CI

| Scenario | Use |
|---|---|
| Unit tests with mocks | Fake/dummy values |
| Integration tests (real LLM calls) | Secrets (costs real $) |
| DB migrations test | Real DB service or SQLite |
| E2E tests | Secrets + deployed staging env |

Nexus unit tests mock the LLM pipeline, so `GROQ_API_KEY: "dummy"` is fine.

---

## LEVEL 6 — Multi-Job Workflows

As projects grow, split into parallel jobs:

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install ruff
      - run: ruff check backend/

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r backend/requirements-dev.txt
      - run: pytest backend/tests/

  type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install mypy
      - run: mypy backend/app/

  deploy:
    needs: [lint, test, type-check]   # only runs if all three pass
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'   # only on main branch
    steps:
      - run: echo "Deploy to Railway/Vercel here"
```

`needs:` creates a dependency graph. `deploy` only runs if `lint`, `test`,
AND `type-check` all pass. If any fail, deploy is skipped automatically.

---

## LEVEL 7 — Branch Protection Rules

CI only helps if you enforce it. In GitHub Settings → Branches → Add rule:

```
Branch name pattern: main
☑ Require status checks to pass before merging
  → Add: "Backend Tests" (the job name from your workflow)
☑ Require branches to be up to date before merging
☑ Do not allow bypassing the above settings
```

With this:
- Nobody (not even the repo owner) can push broken code to `main`
- Every PR must pass CI before it can be merged
- The green checkmark is the only key to production

This is the standard at every professional software team.

---

## LEVEL 8 — Pytest Flags Reference

```bash
pytest tests/                    # run all tests
pytest tests/ -v                 # verbose: show each test name
pytest tests/ -x                 # stop on first failure
pytest tests/ --tb=short         # shorter traceback (less noise)
pytest tests/ -k "test_security" # run only tests matching pattern
pytest tests/ --cov=app          # coverage report (needs pytest-cov)
pytest tests/ -n 4               # parallel with 4 workers (needs pytest-xdist)
pytest tests/ --lf               # rerun only last-failed tests
```

Common pytest.ini settings (already in project):
```ini
[pytest]
asyncio_mode = auto     # all async tests automatically use asyncio
testpaths = tests       # default test directory
```

---

## Interview Questions

**Q: What's the difference between CI and CD?**
CI (Continuous Integration) is automatically running tests on every code change to catch issues early. CD (Continuous Delivery) is automatically preparing a release-ready build after CI passes. Continuous Deployment is automatically deploying that build to production without human approval. Most teams do CI + Continuous Delivery, with a manual approval gate before production deployment.

**Q: Why use GitHub Actions over other CI tools like Jenkins?**
GitHub Actions is hosted (no server to maintain), free for public repos, tightly integrated with GitHub (status checks on PRs, access to secrets, repository events), and has thousands of pre-built actions. Jenkins requires running your own server, gives more control but more maintenance. For a new project, Actions is the obvious choice. For large enterprises with complex on-prem requirements, Jenkins or GitLab CI may be preferred.

**Q: How do you handle secrets like API keys in CI?**
Store them as GitHub Secrets (encrypted, never logged). Reference in workflow as `${{ secrets.SECRET_NAME }}`. For tests that don't actually call the API, use fake values directly in the workflow file — this is fine because the code paths with real credentials are guarded by feature flags or mocked. Never hardcode secrets in workflow files or commit them to the repo.

**Q: What does `needs:` do in a GitHub Actions workflow?**
Creates a job dependency. A job with `needs: [test, lint]` only runs if both `test` and `lint` complete successfully. If either fails, the dependent job is skipped (not failed). This lets you create a pipeline: lint → test → deploy, where deploy only happens if all quality checks pass. Without `needs:`, all jobs run in parallel by default.
