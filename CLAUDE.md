# CLAUDE.md

Working notes for Claude Code and every other contributor. Keep this file current: update it in the same change as the commands, layout, rules or phase status it describes.

## Purpose

**MDT Portfolio** is the data platform for the paper **"Digital Innovation for Governments under Crisis"** (ICIS 2026 Paper Development Workshop). Research question: how do governments develop digital products and services in war? The case is the Ministry of Digital Transformation of Ukraine (Мінцифри). The platform

1. collects, reproducibly, the ministry's portfolio of projects and digital services and a document corpus for the planned qualitative document analysis, and
2. offers a web app in which its user views, filters, sorts, comments on and corrects the data, with a complete revision history.

Guiding principle: **traceability before completeness.** In a scientific paper every value is only as good as its evidence.

The app has **one user**: the data lead provides the server, and one other person uses the app. The server is secured by its environment. So there is **no login and no author name**, nothing has to work for several people at once, and the app has no security layer of its own (decision D-15, `PLAN.md` §12). Every write through the app is recorded with the fixed actor `user`.

`paper.docx` in the repository root is the paper draft. Never modify it and never add copies of it to the repository.

"The assignment" below means the data lead's project brief (in German). It is not part of the repository: its rules are reproduced in this file, and its content is summarised in `PLAN.md` (marked [user]).

## Status

| Phase | Content | State |
|---|---|---|
| 0 | Exploration and plan: `PLAN.md`, drafts of `docs/SOURCES.md` and `docs/CODEBOOK.md` | done |
| 0b | Hands-on source checks and fixture capture | open: the development environment cannot reach the source hosts (`PLAN.md` §2.2) |
| 1 | Skeleton: repository structure, data model and migrations, seed (19 + 1 projects, vocabulary drafts), revisions with diff and restore, comments, API, tables with filters and sorting, detail pages with editing, start via Docker | done (2026-10-29): DoD items 1, 2, 4 and 6 hold on seed data; adversarial review findings fixed; simplified the same day for one user without concurrent editing or a security layer (D-15); all local gates, the E2E suite and a Docker start are green on the simplified state (CI ran green before the simplification) |
| **2** | **Data acquisition:** collectors C1–C5, raw snapshots, reconciliation and review inbox, importer, manual documents | **next**, after the data lead's go; needs network access to the source hosts (Phase 0b) |
| 3 | Analysis: document view with evidence, organisations, participations, components and relations (D2–D4), indicators, timeline, dashboard, exports | planned |
| 4 | Operations: releases with git tags, backups, schedules, documentation | planned |

Content and "done when" per phase: `PLAN.md` §10. Phase 1 is done when items 1, 2, 4 and 6 below hold on seed data and the tests are green.

Definition of Done for v1 (assignment §11):
1. On a fresh server, `docker compose up -d` starts the app at http://127.0.0.1:8080 (configurable).
2. The 19 projects and "Євроінтеграція" (European Integration, out of scope) are visible and can be filtered and sorted by all vocabulary fields.
3. A complete collector run is idempotent: a second run creates neither duplicates nor empty revisions; runs and errors are visible in the UI.
4. A manual change creates a revision with a note; diff and restore work. *(Changed by the data lead on 2026-10-29, D-15: the app has one user, so author names and concurrent editing with the conflict dialog are no longer required.)*
5. Collectors do not overwrite manual values; deviations appear as proposals.
6. Comments (threads, open/resolved) work on all entities and can be filtered.
7. Timeline and dashboard distinguish the periods; all exports and a release with a git tag work.
8. Tests and CI are green; README and `docs/` are complete.

## Data integrity (non-negotiable)

From the assignment, §2:

1. Do not enter facts from your training knowledge into the data. Every value comes from a captured source (URL or document with retrieval time), from the seed data in assignment §3 (provenance `seed`), from an import, or from a person on the team.
2. Derived values are marked as derived and are traceable.
3. Automatically collected values **never** overwrite manual corrections (assignment §6).
4. Nothing is hard-deleted; everything can be restored through the history.

In practice:
- This applies to seeds, fixtures, examples and test data as well. `seed/` holds only values from the assignment (see `seed/README.md`); `codebook/` holds only the codebook draft (see `codebook/README.md`).
- Every write records its channel (`ui`, `restore`, `seed`, `import`, `collector`, …) in the revision and a provenance per field (`field_meta`). Names exist only for the automatic channels (`seed`, `import:<file>`, `collector:<name>`); writes through the app are recorded as `user`, with `src = manual`. Collectors write only unlocked fields and turn other differences into proposals (Phase 2).
- Delete is soft (trash). A hard purge is planned only as a CLI command with explicit confirmation (`mdt purge`, `PLAN.md` §6.4).

## Collection rules (assignment §5; collectors arrive in Phase 2)

- **Be polite:** obey robots.txt; at most about **1 request per second per host**; back off on errors (honour `Retry-After`); send a unique User-Agent that contains the contact e-mail from `.env` (`CONTACT_EMAIL`).
- **No circumvention of protections:** no CAPTCHA solving, no proxy rotation.
- **If gov.ua sites block or throttle:** log it, fall back to the Wayback Machine, and report it to the data lead.
- Look for structured access first (JSON endpoints, sitemaps, RSS, embedded JSON); HTML parsing is the fallback, a headless browser only if unavoidable.
- Wayback captures are upper bounds (`date_basis = archive_upper_bound`), never start dates. Never guess a date.
- Phrases such as "запустили" or "запрацювала" create event **proposals**, never facts; automatic project tags are suggestions.
- Every collector is its own module with tests against stored fixtures; the tests run without network.

## Process rules

- After each phase: all tests green, clean commits (Conventional Commits), and a short status report to the data lead **in German** with three parts: *fertig* (done), *offen* (open), *Entscheidungen* (decisions the data lead has to make).
- **No `git push` without the data lead's approval.**
- If a source behaves differently than described, document it (`docs/SOURCES.md`) and propose an alternative instead of improvising silently.
- Team decisions are D-1 to D-15 in `PLAN.md` §12; for the open ones the proposed defaults apply until the team decides.

## Stack

- **Backend** (`backend/`): Python 3.13 (3.12+), uv with `uv.lock`, FastAPI served by uvicorn, Pydantic v2 (pydantic-settings), SQLAlchemy 2 with Alembic (batch mode), SQLite (WAL, FTS5), Typer CLI `mdt`, markdown-it-py for comments, openpyxl for XLSX exports. Lint and types: ruff, mypy. Tests: pytest; the HTTP tests use Starlette's `TestClient` (dev dependency `httpx2`).
- **Frontend** (`frontend/`): React 19, TypeScript (strict, ~6.0), Vite, Mantine, TanStack Router, Query and Table, jsdiff, dayjs. Lint and types: ESLint 9 (eslint-plugin-react does not support ESLint 10), tsc. Tests: Vitest; Playwright (`@playwright/test` 1.63.0, Chromium) for E2E smoke tests in `frontend/e2e/`.
- **Operations:** one container and one process (FastAPI serves `/api` and the built frontend); multi-stage Dockerfile (node:22-alpine builds the frontend, python:3.13-slim runs the app); docker compose; Makefile; GitHub Actions CI.
- Later phases add a polite HTTP client built on httpx, plus BeautifulSoup/lxml, trafilatura and APScheduler (`PLAN.md` §3.2).

## Repository layout

```
/
├── paper.docx             paper draft (unchanged; never edit or copy)
├── PLAN.md                architecture, rationale, phases, risks, decisions (§12), notes for the paper (§13)
├── CLAUDE.md  README.md
├── Makefile  Dockerfile  docker-compose.yml  .dockerignore  .env.example
├── docker/entrypoint.sh   container start: mdt db upgrade → mdt seed → mdt serve
├── docs/
│   ├── DATA_MODEL.md      contract: entities, fields, revisions, provenance, derived fields
│   ├── API.md             contract: HTTP API, query grammar, exports, runtime
│   ├── UI.md              contract: routes, pages, components, frontend tests
│   ├── CODEBOOK.md        vocabularies and coding rules
│   └── SOURCES.md         source register
├── codebook/              one YAML file per vocabulary + parameters.yaml (cut-off dates)
├── seed/                  projects.yaml: 19 + 1 projects and the focal organisation
├── backend/               uv project: package mdt (src/mdt), alembic.ini, migrations/, tests/
├── frontend/              Vite app (src/, e2e/); build output frontend/dist (gitignored)
├── .github/workflows/ci.yml
├── data/                  runtime data, gitignored: app.db; later raw/, backups/, import/, logs/
└── releases/              frozen dataset releases (Phase 4; committed and tagged); until then only README.md, which keeps the bind-mount directory in every clone
```

## Commands

`make` (or `make help`) lists all targets.

| Command | What it does |
|---|---|
| `make install` | Install backend (`uv sync --locked`) and frontend (`npm ci`) dependencies |
| `make dev` | Backend on http://127.0.0.1:8000 with auto-reload (runs migrations and the seed first) plus the Vite dev server, which proxies `/api` to the backend. `make backend-dev` / `make frontend-dev` run one of them |
| `make build` | Build the frontend into `frontend/dist` |
| `make lint` · `make format` · `make typecheck` | ruff check + ruff format --check + ESLint · ruff format + ruff check --fix + ESLint --fix · mypy + tsc |
| `make test` | Backend (pytest) and frontend (Vitest) unit tests |
| `make e2e` | Build the frontend, then run the Playwright smoke tests |
| `make check` | All quality gates: lint, typecheck, unit tests, frontend build, E2E |
| `make migrate` · `make seed` · `make recompute` · `make db-check` | `mdt db upgrade` · `mdt seed` · `mdt recompute` · `mdt check` on the local database |
| `uv run --project backend mdt reindex` | Rebuild both full-text search tables in batches; the app stays usable (no make target) |
| `make up` · `make down` · `make logs` · `make docker-build` | Docker Compose: build and start (waits until healthy) · stop · follow logs · build the image |

Direct commands:
- Backend quality gates: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q`
- Frontend: `cd frontend && npm run lint && npm run typecheck && npm test && npm run build && npm run e2e`
- CLI: `uv run --project backend mdt <command>` from the repository root (this is what the Makefile does). Commands: `db upgrade`, `seed [--dry-run]`, `recompute`, `check`, `reindex`, `serve [--host] [--port] [--reload]`. `mdt serve` never creates, migrates or seeds the database: it refuses to start (`error: …`, exit 1) while the database file is missing or not at the current schema, so run `mdt db upgrade` and `mdt seed` first. Every command creates a missing `DATA_DIR`.
- E2E needs Chromium: where `/opt/pw-browsers` exists, the Makefile sets `PLAYWRIGHT_BROWSERS_PATH` to it; elsewhere run `cd frontend && npx playwright install chromium` once.

## Docker and configuration

- `docker compose up -d` (or `make up`) starts the single service `app` at http://127.0.0.1:8080. Data lives in `./data` on the host (bind mount to `/app/data`); `./releases` is mounted at `/app/releases`. The Docker daemon creates a missing bind-mount directory as root, so every bind-mount source is either part of the repository (`./releases` through `releases/README.md`; keep that file) or handed to the user `app` by the entrypoint (`./data`, gitignored; `make up` also creates it first, as your user). `backend/tests/test_docker_layout.py` and the CI Docker job check this.
- **Inside the container the app always listens on 0.0.0.0:8080.** `HOST` and `PORT` in `.env` only choose the host interface and port that docker compose publishes (default 127.0.0.1:8080). Compose pins `HOST`, `PORT` and all paths inside the container, so a `.env` with local development values cannot redirect them.
- The entrypoint starts as root only to hand `./data` to the unprivileged user `app` (UID/GID 1000, build arguments `APP_UID`/`APP_GID`), then re-executes itself as `app` and runs `mdt db upgrade`, `mdt seed` and `mdt serve`.
- Run CLI commands in the running container as that user: `docker compose exec -u app app mdt check`. Without `-u app`, `exec` runs as root and can leave root-owned files in `./data`. One-off commands: `docker compose run --rm app mdt check` (the entrypoint drops privileges itself).
- Configuration: `.env` (template `.env.example`, every variable commented).
- `make up` and `make docker-build` record the git commit in the image label `org.opencontainers.image.revision` (and the environment variable `GIT_COMMIT`), with `-dirty` if tracked files have uncommitted changes.
- uv is pinned to 0.11.32 in the Dockerfile and in `.github/workflows/ci.yml`; change both together.

## Conventions

- **Language:** code, comments, UI text, documentation and the codebook in English (the language of the paper). The data lead is addressed in German.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `build:`, `ci:`, `chore:`; dataset releases later `data: release <name>`). Small, focused commits.
- **Contracts:** `docs/DATA_MODEL.md`, `docs/API.md` and `docs/UI.md` are binding. Every interface change (fields, endpoints, parameters, behaviour) updates the affected contract document in the same change.
- **Tests run offline** against fixtures (collector fixtures in `backend/tests/fixtures/<collector>/`). No test may depend on network access.
- **One write path:** every change of curated data goes through `apply_change` or the other write actions of `docs/DATA_MODEL.md` §6.4, which share its machinery (write transaction, revision, field provenance, field locks); see `docs/DATA_MODEL.md` §6.
- **No LLM calls in the app** (no automatic classification or translation) and no machine translation in the data: a missing English name stays empty.
- **No additional security layer** (decision D-15): the server is secured by its environment, so the app has no login, no request guard, no security headers and no HTML sanitising; do not reintroduce them without a new decision. Keep the ordinary input validation the UI relies on, show document texts as plain text (never render stored HTML), keep secrets out of the repository (`.env` is gitignored) and delete only softly.
- **Time:** timestamps in UTC; publication dates as calendar dates in Europe/Kyiv.
- **Dependencies** only through the lockfiles `backend/uv.lock` and `frontend/package-lock.json`.

## Where to read more

- `PLAN.md`: architecture (§3), data model rationale (§4), data acquisition (§5), versioning and reconciliation (§6), web app (§7), operations (§8), phases (§10), risks (§11), decisions (§12), notes for the paper (§13), open questions (§14).
- `docs/DATA_MODEL.md`, `docs/API.md`, `docs/UI.md`: the Phase 1 contracts.
- `docs/CODEBOOK.md`, `codebook/README.md`, `seed/README.md`, `docs/SOURCES.md`.
