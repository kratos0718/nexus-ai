# Docker Containerization — Multi-Stage Builds and Docker Compose

## Why Containers?

Containers package your application and all its dependencies into an isolated, reproducible unit. The three problems they solve:

**"Works on my machine"**: containers capture the exact Python/Node version, OS libraries, and package versions. If it works in the container on your laptop, it works in production.

**Dependency isolation**: Python 3.9 project and Python 3.11 project coexist without `pyenv` gymnastics.

**Deployment simplicity**: deploy by running `docker run your-image`. No SSH, no manual pip installs, no "did you update your .env?"

---

## Multi-Stage Builds — The Core Concept

A naive Dockerfile bundles build tools into the production image:

```dockerfile
FROM python:3.11
RUN apt-get install -y build-essential gcc libpq-dev  # 400MB of compilers
RUN pip install -r requirements.txt                    # compiles C extensions using those tools
COPY . .
# Final image: ~2GB — includes compilers you only needed once, at build time
```

Multi-stage builds separate the build environment from the runtime environment:

```dockerfile
# Stage 1: builder has all tools needed to compile
FROM python:3.11-slim AS deps
RUN apt-get install -y build-essential gcc libpq-dev
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: runtime only copies the compiled output
FROM python:3.11-slim AS runtime
# Copy site-packages (compiled wheels) — NOT the compilers that built them
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
# Runtime only needs the shared libs, not the dev libs
RUN apt-get install -y libpq5 curl
COPY . .
# Final image: ~400MB — no build tools, just installed packages
```

`COPY --from=deps` copies files from a previous stage. The deps stage is completely discarded — its filesystem never ships to production.

---

## Backend Dockerfile — Full Pattern

```dockerfile
FROM python:3.11-slim AS deps

WORKDIR /app

# Install system libraries needed to COMPILE Python packages
# build-essential: gcc, make, etc.
# libpq-dev: PostgreSQL client headers (needed to build psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*  # clear apt cache — reduces layer size

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy compiled packages (not compilers)
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Runtime shared libs (libpq5 = PostgreSQL client runtime, not dev headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# Non-root user — security best practice
# Running as root means a container escape = root on the host
RUN useradd -m -u 1000 nexus
COPY --chown=nexus:nexus . .
USER nexus

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run migrations, then start server
# alembic upgrade head is idempotent — safe to run on every container start
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]
```

**Why `--no-install-recommends`?** apt recommends many optional packages by default. `--no-install-recommends` installs only what you explicitly listed. Saves 50-200MB depending on the package.

**Why run migrations in CMD?** Migrations at container startup means every deployment automatically applies schema changes before traffic arrives. No separate "migration step" in the CI/CD pipeline. Safe because `alembic upgrade head` is idempotent — if no pending migrations, it exits immediately.

---

## Next.js Standalone Build

Standard Next.js Docker images need to copy `node_modules` into the image — that's 500MB+ of dev and prod dependencies.

`output: "standalone"` in `next.config.ts` tells Next.js to trace exactly which files are actually needed at runtime and bundle only those into `.next/standalone/`. Typically 50-100MB instead of 500MB+.

```typescript
// next.config.ts
const nextConfig: NextConfig = {
  output: "standalone",  // produces self-contained server in .next/standalone/
};
```

```dockerfile
# Stage 1: install dependencies
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --frozen-lockfile  # exact lockfile install, no version drift

# Stage 2: build
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time env — NEXT_PUBLIC_ vars are baked into the JS bundle at build time
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build  # produces .next/standalone/

# Stage 3: runtime
FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup -g 1001 nodejs && adduser -S nextjs -u 1001

# Copy only the standalone bundle — NOT node_modules
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0

CMD ["node", "server.js"]  # standalone server, no Next.js CLI needed
```

**`npm ci --frozen-lockfile`** vs `npm install`: `npm install` may update `package-lock.json`. `npm ci` installs exactly what's in the lockfile and errors if they diverge. Use `npm ci` in Docker and CI — reproducible builds.

**Build-time vs runtime env in Next.js**:
- `NEXT_PUBLIC_*` variables: evaluated at `npm run build` and baked into the static JS bundle. Cannot be changed after build. Use for public values like the API URL.
- Server-side variables (no `NEXT_PUBLIC_` prefix): evaluated at request time on the server. Can be injected as Docker environment variables.

---

## Docker Compose — Environment Orchestration

Docker Compose defines multi-container applications as a single YAML file:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-nexus_user}   # var or default
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-nexus_pass}
      POSTGRES_DB: ${POSTGRES_DB:-nexus_db}
    volumes:
      - postgres_data:/var/lib/postgresql/data  # named volume: data survives container restarts
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-nexus_user}"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    profiles: ["prod"]  # only starts with: docker compose --profile prod up
    build:
      context: ./backend
      dockerfile: Dockerfile
    depends_on:
      postgres:
        condition: service_healthy  # wait for postgres healthcheck to pass
```

### Profiles — Dev vs Production

```yaml
# No profile → always starts
postgres:
  image: postgres:16-alpine

redis:
  image: redis:7-alpine

# profiles: ["prod"] → only with --profile prod
backend:
  profiles: ["prod"]
  build: ...

frontend:
  profiles: ["prod"]
  build: ...
```

**Development workflow**: run only the infrastructure locally:
```bash
docker compose up postgres redis -d   # start DB and cache
# FastAPI runs locally: uvicorn app.main:app --reload
# Next.js runs locally: npm run dev
# Full hot-reload, no Docker rebuild on code changes
```

**Production workflow**: containerize everything:
```bash
docker compose --profile prod up -d   # starts postgres + redis + backend + frontend
```

This pattern is industry standard: developers get fast iteration (no Docker rebuild on every code change), while production gets the reproducible containerized stack.

### Named Volumes vs Bind Mounts

```yaml
volumes:
  - postgres_data:/var/lib/postgresql/data  # named volume — managed by Docker, survives restart
  - ./backend:/app                          # bind mount — host directory, for dev hot reload
```

Named volumes live in Docker's storage area (`/var/lib/docker/volumes/`). The data persists when you `docker compose down` and comes back when you `docker compose up`. Use for databases.

Bind mounts link a host directory into the container. Code changes on the host are immediately visible inside the container. Use for dev servers with hot reload.

---

## Healthchecks

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s       # how often to check
  timeout: 10s        # max time for check to complete
  start_period: 40s   # grace period after container start (don't fail during startup)
  retries: 3          # fail after this many consecutive failures
```

`depends_on: condition: service_healthy` makes one container wait for another's healthcheck to pass. Without this, Docker starts containers in dependency order but doesn't wait for the service to be ready — your backend might try to connect to Postgres before Postgres is accepting connections.

---

## Interview Answers

**"What is a multi-stage Docker build and why use it?"**

Multi-stage builds use multiple `FROM` statements in one Dockerfile. Earlier stages compile code using build tools (gcc, make). Later stages copy only the compiled output into a clean base image. Build tools never ship to production. Result: images that are 3-5x smaller, faster to pull, and with a smaller attack surface (fewer binaries that could be exploited).

**"What's the difference between `CMD` and `ENTRYPOINT`?"**

Both define what runs when the container starts. `ENTRYPOINT` is the fixed executable that always runs. `CMD` is the default arguments — can be overridden at `docker run`. Common pattern: `ENTRYPOINT ["python"]` + `CMD ["app.py"]` — running `docker run image script.py` overrides CMD. When you use only `CMD ["sh", "-c", "..."]`, the entire command is overridable. Use `ENTRYPOINT` when the container has a single clear purpose; `CMD` when you want flexibility.

**"How do you handle secrets in Docker?"**

Never bake secrets into images — they're visible in `docker history` and pushed to registries. Pass secrets as environment variables at runtime: `docker run -e DB_PASSWORD=... image` or via Docker secrets / Kubernetes Secrets in orchestrated environments. In development, use `.env` files with `docker compose` (they're gitignored). The Dockerfile should reference `ENV VARIABLE_NAME` without a value — the value is injected at runtime.

**"What does `docker compose down -v` do vs `docker compose down`?"**

`down` stops and removes containers and networks but leaves named volumes intact. `down -v` also removes named volumes — this deletes your database data. Use `down` for normal restarts. Use `down -v` only when you want a completely fresh state (useful in dev when you want to reset the DB, catastrophic in production).
