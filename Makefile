# =============================================================================
# HireFlow AI - developer entry points. `make` on its own lists them.
# =============================================================================
SHELL := /bin/bash
PY    := backend/.venv/bin/python
PIP   := backend/.venv/bin/pip
DOCKER ?= docker

.DEFAULT_GOAL := help
.PHONY: help install dev backend frontend test check-types e2e stub lint fmt tunnel docker-build docker-up clean

help:  ## List every target
	@grep -hE '^[a-z0-9-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Create backend/.venv, install python + node dependencies
	@# Python 3.12+ is required (the code uses StrEnum and PEP 604 unions at
	@# runtime). Prefer an explicit 3.12/3.13, else check whatever python3 is.
	@PY=""; for c in python3.13 python3.12 python3; do 	  command -v $$c >/dev/null 2>&1 || continue; 	  $$c -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null 	    && { PY=$$c; break; }; 	done; 	if [ -z "$$PY" ]; then 	  echo "Python 3.12+ not found. Install it first:"; 	  echo "  macOS:  brew install python@3.12"; 	  echo "  Ubuntu: sudo apt install python3.12 python3.12-venv"; 	  exit 1; 	fi; 	echo "Using $$($$PY --version) from $$(command -v $$PY)"; 	$$PY -m venv backend/.venv
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements-dev.txt
	npm --prefix frontend ci

dev:  ## Run backend + frontend together (Ctrl-C stops both)
	./scripts/dev.sh

backend:  ## Run only the FastAPI backend on :8000 with reload
	cd backend && ./.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:  ## Run only the Next.js dev server on :3000
	npm --prefix frontend run dev

test:  ## Run the backend test suite
	cd backend && ./.venv/bin/pytest -q

check-types:  ## Verify the frontend types still match the API (backend must be running)
	python3 scripts/check-api-types.py

e2e:  ## Walk the whole product in a headless browser (both servers must be running)
	cd frontend && node e2e/walkthrough.mjs

stub:  ## Run the local Hunar stub so calls can be exercised without dialling
	cd backend && ./.venv/bin/python tools/hunar_stub.py --port 8910

lint:  ## Lint python (ruff) and typescript (eslint)
	cd backend && ./.venv/bin/ruff check . && ./.venv/bin/mypy app && cd ../frontend && npm run lint

fmt:  ## Auto-format and auto-fix python
	cd backend && ./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .

tunnel:  ## Public HTTPS URL via cloudflared, written to backend/.env
	./scripts/tunnel.sh

docker-build:  ## Build the backend Docker image
	$(DOCKER) build -f backend/Dockerfile -t hireflow-api:local backend

docker-up:  ## Start backend + frontend with docker compose
	$(DOCKER) compose up --build

clean:  ## Remove build artifacts, caches and local DB files
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.mypy_cache frontend/.next frontend/out && find backend -name __pycache__ -type d -prune -exec rm -rf {} + && rm -f backend/data/*.db backend/data/*.db-shm backend/data/*.db-wal
