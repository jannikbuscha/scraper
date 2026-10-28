# syntax=docker/dockerfile:1
#
# MDT Portfolio: one image, one process. uvicorn/FastAPI serves the API under
# /api and the built React app under /.
#
#   make docker-build   build the image mdt-portfolio:local (records the git commit)
#   make up             build and start it with docker compose
#
# Inside the container the app always listens on 0.0.0.0:8080. HOST and PORT
# in .env only choose where docker compose publishes that port on the host
# (default 127.0.0.1:8080), see docker-compose.yml and README.md.

# ---------------------------------------------------------------------------
# Stage 1: build the frontend (output: /build/frontend/dist)
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /build/frontend

# Building the app needs no browsers; Playwright runs only in CI and local E2E.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Dependencies first: this layer is reused until package*.json change.
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: runtime (Python 3.13, dependencies from backend/uv.lock)
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# uv, pinned. Keep the version in sync with .github/workflows/ci.yml.
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

# Unprivileged user that runs the app. The IDs are build arguments so that the
# files in the bind-mounted ./data can belong to the host user (see README.md).
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --no-log-init --create-home \
        --home-dir /home/app --shell /usr/sbin/nologin app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

# Backend dependencies only, exactly as locked. Cached until pyproject.toml or
# uv.lock change.
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# The backend itself (package "mdt" with its console script, alembic.ini,
# migrations/). Installed in editable mode, so the code stays in /app/backend.
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Runtime inputs: vocabularies, seed data, the built frontend, the entrypoint.
WORKDIR /app
COPY codebook/ ./codebook/
COPY seed/ ./seed/
COPY --from=frontend /build/frontend/dist/ ./frontend/dist/
COPY --chmod=0755 docker/entrypoint.sh ./docker/entrypoint.sh

# Runtime data lives in /app/data (bind mount ./data in docker-compose.yml).
RUN mkdir -p /app/data /app/releases \
    && chown app:app /app/data /app/releases

# Paths inside the image. docker-compose.yml pins the same values, so that a
# .env written for local development cannot redirect them.
ENV HOST=0.0.0.0 \
    PORT=8080 \
    DATA_DIR=/app/data \
    CODEBOOK_DIR=/app/codebook \
    SEED_DIR=/app/seed \
    FRONTEND_DIST=/app/frontend/dist

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"]

# Starts as root only to fix the owner of /app/data, then drops to "app" before
# running anything else (see docker/entrypoint.sh). No CMD: without arguments
# the entrypoint runs migrations, the seed and the server.
ENTRYPOINT ["/app/docker/entrypoint.sh"]

# Build metadata last, so that a new commit does not invalidate cached layers.
# GIT_COMMIT is passed by `make up` / `make docker-build` (docker compose build
# argument, default "unknown"); "-dirty" marks uncommitted changes.
ARG GIT_COMMIT=unknown
LABEL org.opencontainers.image.title="MDT Portfolio" \
      org.opencontainers.image.description="Research data platform on the project and service portfolio of the Ministry of Digital Transformation of Ukraine (ICIS 2026 PDW paper)" \
      org.opencontainers.image.revision="${GIT_COMMIT}"
ENV GIT_COMMIT="${GIT_COMMIT}"
