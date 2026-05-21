# Cloud Deployment — From Local to Production

## The Big Picture

Running your app on your laptop vs. running it for real users requires:

| Concern         | Local (laptop)           | Production (cloud)                     |
|-----------------|--------------------------|----------------------------------------|
| Availability    | You keep it running      | Cloud keeps it running 24/7            |
| Database        | SQLite file              | Managed PostgreSQL (backups, HA)       |
| Secrets         | `.env` file              | Env vars injected by platform          |
| Scaling         | One process              | Multiple workers, auto-scale           |
| Port            | Always 8000              | Platform assigns a dynamic port        |
| Restarts        | Manual                   | Automatic on crash                     |
| Deploys         | `uvicorn` manually       | Push to git → auto-deploy              |

---

## 1. Types of Cloud Hosting

### IaaS — Infrastructure as a Service
You rent raw servers (EC2, GCE). You configure everything: OS, network, load balancer.
- **More control, more ops work**
- Examples: AWS EC2, GCP Compute Engine, Azure VMs

### PaaS — Platform as a Service
You push code or a Docker image. Platform handles servers, networking, scaling.
- **Less control, much less ops work**
- Examples: Railway, Render, Fly.io, Heroku, Google Cloud Run

### SaaS — Software as a Service
You use someone else's fully managed application.
- Examples: Groq API, Pinecone, Supabase

**Day 22 uses Railway (PaaS) — best balance of control vs. simplicity.**

---

## 2. Railway — How It Works

Railway runs Docker containers. When you `railway up`:
1. Railway builds your Dockerfile in their cloud
2. The image is stored in Railway's container registry
3. A container is started with your env vars injected
4. Railway gives you a public HTTPS URL (e.g. `nexus-backend.up.railway.app`)

**Railway's key value:**
- Provisions managed PostgreSQL + Redis with one click
- Injects `DATABASE_URL` and `REDIS_URL` automatically (no copy-paste)
- Auto-HTTPS (TLS certificate managed for you)
- Logs, metrics, and rollbacks in the dashboard

---

## 3. The `$PORT` Pattern

Railway (and most PaaS) assigns a random port to your container. Your app must listen on that port.

**Wrong (hardcoded):**
```dockerfile
CMD uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Right (reads from env):**
```dockerfile
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
```

`${PORT:-8000}` means: use `$PORT` if set, fall back to 8000 otherwise.
This makes the same Dockerfile work both locally (port 8000) and on Railway (whatever Railway assigns).

---

## 4. Environment Variables in Production

### Never hardcode secrets in code or Dockerfiles
```python
# BAD — exposed in git history forever
GROQ_API_KEY = "gsk_abc123..."

# GOOD — reads from environment
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
```

### Railway variable injection
Railway uses template references to inject plugin-provided values:
```
DATABASE_URL = ${{Postgres.DATABASE_URL}}
REDIS_URL    = ${{Redis.REDIS_URL}}
```
You don't set these manually — Railway wires them up when you add the plugins.

### GitHub Secrets for CI/CD
Secrets needed in GitHub Actions (like `RAILWAY_TOKEN`) are stored in:
`repo Settings → Secrets and variables → Actions`

They appear as `${{ secrets.RAILWAY_TOKEN }}` in workflows and are masked in logs.

---

## 5. Docker in Production — Key Concepts

### Multi-stage builds (already used in Nexus AI)
```dockerfile
FROM python:3.11-slim AS deps    # install deps
RUN pip install -r requirements.txt

FROM python:3.11-slim AS runtime # copy only what's needed
COPY --from=deps /usr/local/lib/python3.11/site-packages ...
COPY . .
CMD uvicorn ...
```

**Why:** The `deps` stage has `build-essential` (compilers, headers). The `runtime` stage doesn't.
Result: smaller final image (less attack surface, faster pull).

### Non-root user
```dockerfile
RUN useradd -m -u 1000 nexus && chown -R nexus:nexus /app
USER nexus
```
Containers run as root by default — bad security practice. The non-root user `nexus`
can't install packages or write outside `/app`, limiting blast radius if compromised.

### HEALTHCHECK vs. Railway health check
- Docker `HEALTHCHECK` — probed by Docker daemon, restarts container if it fails
- Railway `healthcheckPath` in `railway.toml` — Railway's load balancer uses this to determine readiness

**Key difference:** `/ping` (no DB) vs. `/health` (full DB + Redis check).
Use `/ping` for load-balancer readiness (is the process alive?) and `/health` for monitoring dashboards.

---

## 6. `railway.toml` — Configuration File

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
healthcheckPath = "/ping"         # Railway polls this during deploy
healthcheckTimeout = 300          # Give 5 min for cold start (ML models are slow)
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3
```

`healthcheckTimeout = 300`: Railway waits up to 5 minutes for the health check to return 200.
ML models (sentence-transformers) take 30-60 seconds to load on cold start.

---

## 7. Database Migrations in Production

Nexus AI's Dockerfile runs `alembic upgrade head` before starting the server:
```dockerfile
CMD sh -c "alembic upgrade head && uvicorn app.main:app ..."
```

This means every deploy runs migrations automatically. Safe for additive changes (new tables, new columns).
For destructive changes (dropping columns), use a separate migration step.

**Why not a separate migration job?**
For small apps, running migrations in the startup command is simpler. For larger teams,
a separate migration step (run once, before the new servers start) prevents the migration
running multiple times if multiple instances start simultaneously.

---

## 8. CORS in Production

In development: `ALLOWED_ORIGINS=http://localhost:3000`
In production: `ALLOWED_ORIGINS=https://nexus-frontend.up.railway.app`

Never use `*` in production for an authenticated app — CORS `*` allows any website
to make credentialed requests to your API, enabling cross-site request forgery.

Nexus AI reads this from env:
```python
_allowed_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
]
```

Multiple origins (dev + prod + staging): `ALLOWED_ORIGINS=https://prod.example.com,https://staging.example.com`

---

## 9. The CD Pipeline Flow

```
git push origin main
        ↓
GitHub Actions triggers
        ↓
Job: lint          → ruff check (10s)
Job: backend-tests → pytest --cov (60s)
Job: frontend-checks → tsc --noEmit (30s)
        ↓ all pass
Job: deploy
  → railway up --service nexus-backend --detach
  → railway up --service nexus-frontend --detach
        ↓
Railway builds Docker image (2-5 min)
Railway starts container, probes /ping
        ↓
Old container shut down, new one serves traffic
```

`--detach` flag: `railway up` exits immediately after starting the build.
Without it, the GitHub Actions job would wait for the full build + deploy (~5 min).

---

## 10. Rollbacks

If a deploy breaks production:
```bash
# Via Railway CLI
railway rollback

# Via Railway dashboard
# Services tab → Deployments → click previous deploy → Redeploy
```

Railway keeps the last N deployments. Each deployment's image is stored in the registry,
so rollbacks are fast (seconds, not minutes) — no rebuild needed.

---

## Interview Questions

**Q: What is the difference between IaaS, PaaS, and SaaS?**
IaaS (EC2) gives you raw VMs — you manage OS, networking, scaling. PaaS (Railway, Heroku)
gives you a managed runtime — you push code or containers, platform handles the rest.
SaaS (Groq, Pinecone) gives you a fully managed service — no infrastructure at all.
Most startups use PaaS for cost-effectiveness and SaaS for managed databases/AI.

**Q: Why does Railway (and most PaaS) use a dynamic $PORT instead of a fixed one?**
Multiple containers share one host machine. Each needs a unique port to avoid conflicts.
The platform assigns ports dynamically and puts a reverse proxy in front that maps
external port 443 (HTTPS) to the container's dynamic port. Your app just reads `$PORT`.

**Q: How do you run database migrations safely in a CI/CD pipeline?**
For small teams: run `alembic upgrade head` in the Docker CMD before starting the server.
For larger teams: run migrations as a separate Railway job (one-shot task) before deploying
new server instances. This prevents the migration running N times if N instances start
simultaneously, and gives you a chance to abort if migrations fail before new servers start.

**Q: What is the difference between a liveness probe and a readiness probe?**
Liveness probe: is the process alive? If not, restart it. Uses a cheap endpoint (/ping) that
always returns 200 as long as the process is running.
Readiness probe: is the service ready to serve traffic? If not, stop sending it traffic but
don't restart. Uses a deeper endpoint (/health) that checks DB, cache, etc.
Railway's `healthcheckPath` is a readiness check — unhealthy containers don't receive traffic.

**Q: What happens if a secret is accidentally committed to git?**
The secret is now permanently in the git history, accessible to anyone with repo access.
The correct response: immediately rotate the secret (get a new API key, invalidate the old one),
then remove it from the history with `git filter-repo` or BFG Repo Cleaner. Simply deleting
the file is NOT enough — it remains in the history. Prevention: pre-commit hooks that scan for
secrets (detect-secrets, gitleaks), and never store secrets in files tracked by git.
