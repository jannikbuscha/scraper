# MDT Portfolio: developer and operations commands (GNU make).
# Run `make` or `make help` to list the targets.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-builtin-rules

# The mdt CLI runs from the repository root, as in the container (/app), so
# relative paths (data/, codebook/, seed/, frontend/dist, .env) resolve the
# same way everywhere. Quality gates run inside backend/ and frontend/.
MDT := uv run --project backend mdt
BACKEND := cd backend &&
FRONTEND := cd frontend &&

# Backend address for `make dev`; the Vite dev server proxies /api to it.
DEV_HOST := 127.0.0.1
DEV_PORT := 8000

# Commit recorded in the image label org.opencontainers.image.revision.
# "-dirty" marks uncommitted changes to tracked files.
GIT_COMMIT ?= $(shell git rev-parse HEAD 2>/dev/null || echo unknown)$(shell git diff --quiet HEAD -- 2>/dev/null || [ $$? -ne 1 ] || echo -dirty)

# Use preinstalled Playwright browsers when present (e.g. /opt/pw-browsers in
# the cloud development environment). CI installs Chromium itself.
ifeq ($(origin PLAYWRIGHT_BROWSERS_PATH),undefined)
  ifneq ($(wildcard /opt/pw-browsers),)
    export PLAYWRIGHT_BROWSERS_PATH := /opt/pw-browsers
  endif
endif

.PHONY: help install dev backend-dev frontend-dev build \
	test e2e lint format typecheck check \
	migrate seed recompute db-check \
	collect fixtures sources-check \
	up down logs docker-build

##@ General

help: ## Show this help (default target)
	@awk 'BEGIN { FS = ":.*## "; print "Usage: make <target>" } \
		/^##@/ { printf "\n%s\n", substr($$0, 5); next } \
		/^[a-zA-Z0-9_-]+:.*## / { printf "  %-14s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

##@ Development

install: ## Install backend (uv, from uv.lock) and frontend (npm ci) dependencies
	$(BACKEND) uv sync --locked
	$(FRONTEND) npm ci

dev: ## Run the backend (127.0.0.1:8000, auto-reload) and the Vite dev server together
	@$(MAKE) --no-print-directory -j2 backend-dev frontend-dev

backend-dev: ## Run the API on 127.0.0.1:8000 with auto-reload (migrates and seeds first)
	$(MDT) db upgrade
	$(MDT) seed
	$(MDT) serve --host $(DEV_HOST) --port $(DEV_PORT) --reload

frontend-dev: ## Run the Vite dev server (proxies /api to 127.0.0.1:8000)
	$(FRONTEND) npm run dev

build: ## Build the frontend into frontend/dist
	$(FRONTEND) npm run build

##@ Quality

lint: ## Lint the backend (ruff check, ruff format --check) and the frontend (ESLint)
	$(BACKEND) uv run ruff check .
	$(BACKEND) uv run ruff format --check .
	$(FRONTEND) npm run lint

format: ## Format the backend (ruff format, ruff check --fix); fix frontend lint issues
	$(BACKEND) uv run ruff format .
	$(BACKEND) uv run ruff check --fix .
	$(FRONTEND) npm run lint -- --fix

typecheck: ## Type-check the backend (mypy) and the frontend (tsc)
	$(BACKEND) uv run mypy src
	$(FRONTEND) npm run typecheck

test: ## Run the backend (pytest) and frontend (Vitest) unit tests
	$(BACKEND) uv run pytest -q
	$(FRONTEND) npm test

e2e: build ## Build the frontend, then run the Playwright E2E smoke tests
	$(FRONTEND) npm run e2e

check: ## Run all quality gates: lint, typecheck, unit tests, frontend build, E2E
	@$(MAKE) --no-print-directory lint
	@$(MAKE) --no-print-directory typecheck
	@$(MAKE) --no-print-directory test
	@$(MAKE) --no-print-directory e2e

##@ Local database (DATA_DIR, default data/app.db)

migrate: ## Apply the database migrations (mdt db upgrade)
	$(MDT) db upgrade

seed: ## Load vocabularies and seed data; idempotent (mdt seed)
	$(MDT) seed

recompute: ## Recompute all derived fields (mdt recompute)
	$(MDT) recompute

db-check: ## Run the database integrity report (mdt check)
	$(MDT) check

##@ Data acquisition (docs/COLLECTORS.md §11; CONTACT_EMAIL in .env)

# Collector for `make collect` and `make fixtures`; MODE is incremental (default) or full.
SOURCE ?=
MODE ?= incremental

collect: ## Run a collector in the foreground: make collect SOURCE=<name> [MODE=full]
	@test -n "$(SOURCE)" || { echo "usage: make collect SOURCE=<name> [MODE=full]" >&2; exit 2; }
	$(MDT) collect $(SOURCE) --mode $(MODE)

fixtures: ## Capture a collector's fixture list: make fixtures SOURCE=wayback
	@test -n "$(SOURCE)" || { echo "usage: make fixtures SOURCE=<name>" >&2; exit 2; }
	$(MDT) fixtures capture $(SOURCE)

sources-check: ## Check robots.txt and reachability of every source host from this machine
	$(MDT) sources check

##@ Docker (published on HOST:PORT from .env, default 127.0.0.1:8080)

up: ## Build the image and start the app; waits until it is healthy
	@mkdir -p data releases
	GIT_COMMIT=$(GIT_COMMIT) docker compose up -d --build --wait --wait-timeout 180

down: ## Stop and remove the container (the data in ./data is kept)
	docker compose down

logs: ## Follow the app logs
	docker compose logs -f --tail=200 app

docker-build: ## Build the image mdt-portfolio:local
	GIT_COMMIT=$(GIT_COMMIT) docker compose build
