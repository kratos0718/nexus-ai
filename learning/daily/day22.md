# Day 22 — Cloud Deployment (Railway)

## What I Built

**Production hardening:**
- `/ping` endpoint in `main.py` — lightweight liveness probe, no DB dependency
- Backend Dockerfile CMD updated: `--port ${PORT:-8000}` (Railway injects `$PORT`)
- HEALTHCHECK updated to probe `/ping` with 60s `start_period` (ML models are slow to load)

**Railway configuration:**
- `backend/railway.toml` — Dockerfile builder, `/ping` health check, 300s timeout, restart policy
- `frontend/railway.toml` — Dockerfile builder, `/` health check, build arg for API URL
- `backend/.env.production.example` — documented all required env vars with Railway-specific notes

**CD pipeline:**
- Added `deploy` job to `.github/workflows/ci.yml`
- Triggers ONLY on `push` to `main` (not PRs), runs AFTER lint + tests + tsc all pass
- Deploys both `nexus-backend` and `nexus-frontend` services via Railway CLI
- `continue-on-error: true` until `RAILWAY_TOKEN` secret is configured (placeholder)

**README:**
- Added "Deploy to Railway" section with step-by-step CLI commands

---

## Key Decisions

**Why `/ping` instead of `/health` for Railway's healthcheckPath?**
The `/health` endpoint checks the database. On cold start, the database might not be
ready yet (migrations are running). `/ping` always returns 200 as long as the Python
process is alive — no external dependencies. This prevents Railway from cycling containers
during normal startup.

**Why `continue-on-error: true` on the deploy steps?**
The `RAILWAY_TOKEN` secret won't exist until the user sets it up on railway.app.
Without `continue-on-error`, the deploy job would fail and block all future CI runs.
Once the token is configured, remove this flag — deploy failures should fail the pipeline.

**Why 300 second healthcheckTimeout?**
sentence-transformers downloads ~90MB model on first container start (cold start).
Without a long timeout, Railway kills the container before the model loads, causing
an infinite restart loop.

**Why $PORT instead of hardcoded 8000?**
Railway assigns ports dynamically. Multiple containers on the same host need unique ports.
Railway puts a reverse proxy in front that maps HTTPS:443 → container's dynamic port.
Hardcoding 8000 would break Railway deployment.

---

## Railway Setup Checklist (one-time)

```bash
# Install CLI
npm install -g @railway/cli

# Login
railway login

# Create project (run from repo root)
cd backend && railway init

# Add plugins
railway add --plugin postgresql
railway add --plugin redis

# Check that Railway injected DATABASE_URL and REDIS_URL
railway variables

# Set required secrets in Railway dashboard (Variables tab):
#   SECRET_KEY        = (generate: python -c "import secrets; print(secrets.token_hex(32))")
#   JWT_SECRET_KEY    = (generate another one)
#   GROQ_API_KEY      = gsk_...
#   ALLOWED_ORIGINS   = https://nexus-frontend.up.railway.app  (set after frontend is deployed)
#   LOG_FORMAT        = json

# Deploy backend manually (first time)
railway up --service nexus-backend

# Get the backend URL from Railway dashboard
# Set NEXT_PUBLIC_API_URL in frontend Railway service
# Deploy frontend
cd ../frontend && railway up --service nexus-frontend

# Add RAILWAY_TOKEN to GitHub Secrets for auto-deploy
# railway.app → Account → Tokens → Create token
# GitHub → repo Settings → Secrets → Actions → New → RAILWAY_TOKEN
```

---

## Concepts Learned

- PaaS vs IaaS vs SaaS — where Railway sits in the hosting hierarchy
- `$PORT` dynamic port pattern — how PaaS load balancers work
- Liveness vs readiness probes — why two different health endpoints
- Multi-stage Docker builds — `deps` stage vs `runtime` stage separation
- Non-root container users — security principle of least privilege
- Railway plugin variables — `${{Postgres.DATABASE_URL}}` auto-injection
- CD with `railway up --detach` — fire-and-forget deploy step
- Migration strategy — `alembic upgrade head` in CMD before server start

---

## Resume Bullets

- Deployed FastAPI + Next.js to Railway PaaS using Dockerfiles with multi-stage builds and non-root user
- Configured Railway service health checks with separate /ping (liveness) and /health (readiness) endpoints
- Implemented end-to-end CD pipeline: push to main → CI passes → Railway auto-deploys both services
- Documented production environment setup with Railway plugin variable injection pattern

---

## Interview Q&As

**Q282: What is a PaaS and why use it over raw cloud VMs?**
PaaS (Platform as a Service) manages servers, networking, load balancing, and TLS for you.
You push code or a Docker image; the platform runs it. Raw VMs (IaaS) give you more control
but require you to manage everything yourself. For startups and MVPs, PaaS reduces ops burden
significantly — Railway, Render, and Fly.io all provision databases, handle SSL, and give
you logs/metrics with zero additional config.

**Q283: Why does Railway inject $PORT instead of using a fixed port?**
Multiple containers share physical host machines. Each needs a unique port. Railway's reverse
proxy maps HTTPS:443 → container's dynamic port. Hardcoding port 8000 would conflict when
multiple containers run on the same host. The `${PORT:-8000}` pattern reads Railway's injected
port in production and falls back to 8000 locally.

**Q284: What is the difference between a liveness probe and a readiness probe?**
Liveness: is the process alive? Check with `/ping` — always 200 as long as Python is running.
If it fails, restart the container.
Readiness: is the service ready to serve traffic? Check with `/health` — verifies DB, cache, etc.
If it fails, stop routing traffic to this instance (but don't restart it — it might be warming up).
Railway's `healthcheckPath` acts as a readiness check.

**Q285: How do you run database migrations in a CD pipeline?**
Simple approach (used here): include `alembic upgrade head` in the Docker CMD before starting uvicorn.
Every container runs migrations on startup. Safe for additive migrations (add column, add table).
Scalable approach: run a one-shot migration job before deploying new app containers. This prevents
N containers running N migrations simultaneously and gives a clear failure point if migrations break.

**Q286: What happens when a secret is committed to a git repository?**
The secret is permanently in git history — accessible to anyone who can clone the repo,
even after deleting the file. Correct response: (1) rotate the secret immediately at the provider,
(2) remove from history with `git filter-repo` or BFG Repo Cleaner, (3) force-push all branches.
Prevention: pre-commit hooks (detect-secrets, gitleaks), .gitignore for .env files, and
storing secrets only in platform-managed secret stores.
