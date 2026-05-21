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
- Examples: Render, Fly.io, Heroku, Google Cloud Run

### SaaS — Software as a Service
You use someone else's fully managed application.
- Examples: Groq API, Pinecone, Supabase, Vercel

**Nexus AI deployment: Vercel (frontend, free) + Docker Compose (backend, runs anywhere).**

---

## 2. Vercel — Frontend Deployment (free, no card required)

Vercel is a PaaS built for frontend frameworks. For Next.js projects it is the natural choice.

**How it works:**
1. Connect your GitHub repo at vercel.com
2. Vercel detects Next.js automatically
3. Every push to `main` triggers a build
4. Vercel runs `npm run build` and serves the static + server-side output from its CDN
5. You get a public HTTPS URL instantly (e.g. `nexus-ai.vercel.app`)

**Why Vercel for Next.js:**
- Zero-config — it understands Next.js project structure
- Edge network — serves static assets from the CDN node closest to the user
- Preview deployments — every PR gets its own URL for testing
- Environment variables set in the Vercel dashboard, not in code

**Key env var for the frontend:**
```
NEXT_PUBLIC_API_URL=https://your-backend-url.com
```

---

## 3. The `$PORT` Pattern

Most PaaS platforms assign a random port to your container. Your app must read it.

**Wrong (hardcoded):**
```dockerfile
CMD uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Right (reads from env):**
```dockerfile
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
```

`${PORT:-8000}` means: use `$PORT` if set, fall back to 8000 otherwise.
This makes the same Dockerfile work both locally (port 8000) and on any PaaS (whatever port is assigned).

---

## 4. Environment Variables in Production

### Never hardcode secrets in code or Dockerfiles
```python
# BAD — exposed in git history forever
GROQ_API_KEY = "gsk_abc123..."

# GOOD — reads from environment
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
```

### Production env var checklist
```bash
# Required — generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=...
JWT_SECRET_KEY=...

# Free at console.groq.com
GROQ_API_KEY=...

# Your Vercel frontend URL
ALLOWED_ORIGINS=https://nexus-ai.vercel.app

# PostgreSQL (managed by your hosting provider)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/nexus_ai

# Redis (managed or self-hosted)
REDIS_URL=redis://host:6379/0
```

### GitHub Secrets for CI
Secrets used in GitHub Actions are stored in:
`repo Settings → Secrets and variables → Actions`

They appear as `${{ secrets.MY_SECRET }}` in workflows and are masked in logs.

---

## 5. Docker in Production — Key Concepts

### Multi-stage builds
```dockerfile
FROM python:3.11-slim AS deps    # install deps (has compilers)
RUN pip install -r requirements.txt

FROM python:3.11-slim AS runtime # copy only what's needed (no compilers)
COPY --from=deps /usr/local/lib/python3.11/site-packages ...
COPY . .
CMD uvicorn ...
```

**Why:** The `deps` stage has build tools (gcc, headers). The `runtime` stage doesn't.
Result: smaller final image (less attack surface, faster pull).

### Non-root user
```dockerfile
RUN useradd -m -u 1000 nexus && chown -R nexus:nexus /app
USER nexus
```
Containers run as root by default — a security risk. A non-root user
limits blast radius if the container is compromised.

### Liveness vs. readiness probes
- **Liveness probe** (`/ping`): is the process alive? Cheap endpoint, always 200 if running. Used to restart crashed containers.
- **Readiness probe** (`/health`): is the service ready to serve traffic? Checks DB, Redis, pipeline. Used to hold traffic until the app finishes loading ML models (30-60s cold start).

---

## 6. Docker Compose for Production-Like Local Stack

```yaml
# docker-compose.yml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    env_file: ./backend/.env
    depends_on: [postgres, redis]

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: nexus_ai
      POSTGRES_USER: nexus
      POSTGRES_PASSWORD: nexus

  redis:
    image: redis:7-alpine
```

```bash
# Start everything
docker compose up -d

# Run migrations
docker compose exec backend alembic upgrade head

# View logs
docker compose logs -f backend

# Stop
docker compose down
```

This is how you run the full production-equivalent stack locally.

---

## 7. Database Migrations in Production

Nexus AI's Dockerfile runs `alembic upgrade head` before starting the server:
```dockerfile
CMD sh -c "alembic upgrade head && uvicorn app.main:app ..."
```

This means every deploy runs migrations automatically. Safe for additive changes (new tables, new columns with defaults).

For destructive changes (dropping columns, renaming), use a two-step deploy:
1. Deploy code that works with both old and new schema
2. Run the destructive migration
3. Deploy code that drops support for the old schema

---

## 8. CORS in Production

In development: `ALLOWED_ORIGINS=http://localhost:3000`
In production: `ALLOWED_ORIGINS=https://nexus-ai.vercel.app`

Never use `*` in production for an authenticated API — CORS `*` allows any website
to make credentialed requests, enabling cross-site request forgery.

Multiple origins (dev + prod + staging):
```
ALLOWED_ORIGINS=https://nexus-ai.vercel.app,https://staging.vercel.app
```

Nexus AI reads this from env:
```python
_allowed_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
]
```

---

## 9. CI Pipeline Flow (without CD)

```
git push origin main
        ↓
GitHub Actions triggers
        ↓
Job: lint            → ruff check (10s)
Job: backend-tests   → pytest --cov (60s)      ← needs: lint
Job: frontend-checks → tsc --noEmit (30s)
        ↓ all pass
ci-passed gate is green ✓

Frontend CD: Vercel auto-deploys on push to main (separate from GitHub Actions)
Backend CD: docker compose pull && docker compose up -d on your server (manual or via webhook)
```

Keeping CI (correctness checks) and CD (deploy) separate is cleaner for solo projects.
CI runs on every push; deploy is triggered when you're ready.

---

## 10. Free Deployment Options (no card required)

| Service | What | Limits |
|---------|------|--------|
| **Vercel** | Next.js frontend | Generous free tier, no card |
| **Render** | Docker backend | 750 free hours/month, sleeps after 15min idle |
| **Fly.io** | Docker anywhere | Requires card for free tier |
| **Koyeb** | Docker backend | 1 free service, no card |
| **GitHub Actions** | CI | 2,000 min/month free for public repos |

For a portfolio project, Vercel (frontend) + Render (backend) is the no-card-required combination.

---

## Interview Questions

**Q: What is the difference between IaaS, PaaS, and SaaS?**
A: IaaS (EC2) gives you raw VMs — you manage OS, networking, scaling. PaaS (Render, Fly.io) gives you a managed runtime — you push code or containers, platform handles the rest. SaaS (Groq, Pinecone, Vercel) gives you a fully managed service — no infrastructure at all. Most startups use PaaS for web services and SaaS for managed databases and AI APIs.

**Q: Why does a PaaS use a dynamic `$PORT` instead of a fixed one?**
A: Multiple containers share one host machine. Each needs a unique port to avoid conflicts. The platform assigns ports dynamically and puts a reverse proxy in front that maps external port 443 (HTTPS) to the container's dynamic port. Your app just reads `$PORT`.

**Q: How do you run database migrations safely in a CI/CD pipeline?**
A: For small teams: run `alembic upgrade head` in the Docker CMD before starting the server — simple and works for additive changes. For larger teams: run migrations as a separate one-shot task before starting new server instances. This prevents the migration running N times if N instances start simultaneously, and lets you abort if migrations fail.

**Q: What is the difference between a liveness probe and a readiness probe?**
A: Liveness probe (`/ping`): is the process alive? If not, restart it. Cheap, always fast.
Readiness probe (`/health`): is the service ready to serve traffic? Checks DB, Redis, ML models. If not ready, hold traffic but don't restart. Important for ML apps with slow cold starts (sentence-transformers takes 30-60s to load).

**Q: What happens if a secret is accidentally committed to git?**
A: It's permanently in git history — visible to anyone who clones the repo, even after you delete the file. Correct response: immediately rotate the secret (new API key, invalidate old one), then scrub history with `git filter-repo` or BFG Repo Cleaner, then force-push. Prevention: `.gitignore` all `.env` files, pre-commit hooks with `detect-secrets` or `gitleaks`.
