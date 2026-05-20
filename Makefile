CONDA_ENV = nexus-ai
BACKEND_DIR = backend
FRONTEND_DIR = frontend

# ── First-time setup ──────────────────────────────────────────────────────────
setup:
	@echo "Setting up backend..."
	cp -n $(BACKEND_DIR)/.env.example $(BACKEND_DIR)/.env 2>/dev/null || true
	conda run -n $(CONDA_ENV) pip install -r $(BACKEND_DIR)/requirements-dev.txt
	@echo "Setting up frontend..."
	cd $(FRONTEND_DIR) && npm install
	@echo ""
	@echo "Done. Edit backend/.env and add your GROQ_API_KEY, then run: make dev"

# ── Database ──────────────────────────────────────────────────────────────────
migrate:
	cd $(BACKEND_DIR) && conda run -n $(CONDA_ENV) alembic upgrade head

# ── Development servers ───────────────────────────────────────────────────────
backend:
	cd $(BACKEND_DIR) && conda run -n $(CONDA_ENV) uvicorn app.main:app --reload --port 8000

frontend:
	cd $(FRONTEND_DIR) && npm run dev

# Run both in parallel (opens two background processes, logs to terminal)
dev:
	@make migrate
	@echo "Starting backend on :8000 and frontend on :3000"
	@trap 'kill 0' INT; \
	(cd $(BACKEND_DIR) && conda run -n $(CONDA_ENV) uvicorn app.main:app --reload --port 8000) & \
	(cd $(FRONTEND_DIR) && npm run dev) & \
	wait

# ── Testing ───────────────────────────────────────────────────────────────────
test:
	cd $(BACKEND_DIR) && conda run -n $(CONDA_ENV) pytest tests/ -v

# ── Utilities ─────────────────────────────────────────────────────────────────
reset-db:
	rm -f $(BACKEND_DIR)/nexus.db
	make migrate

.PHONY: setup migrate backend frontend dev test reset-db
