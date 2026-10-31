# MDT Portfolio

Research data platform for the paper **"Digital Innovation for Governments under Crisis"** (ICIS 2026 Paper Development Workshop). It maps the portfolio of projects and digital services of the Ministry of Digital Transformation of Ukraine (Мінцифри) and builds a document corpus for the qualitative document analysis. In the web app its user views, filters, sorts, comments on and corrects the data, with a complete revision history. The app has one user and no login; the server it runs on is secured by its environment (decision D-15 in [`PLAN.md`](PLAN.md) §12).

Guiding principle: **traceability before completeness.** Every value records where it came from (seed, collector run, import or a change made in the app), automatic updates never overwrite manual corrections, and nothing is hard-deleted.

> **Status: Phase 1 (skeleton) is done; Phase 2 (data acquisition) is implemented.** The Wayback Machine collector (C5) still needs its checks and fixtures from the target server ([`docs/SOURCES.md`](docs/SOURCES.md) §5). This README covers the Docker start, local development, configuration, access, data acquisition and data. The full README (deployment, schedules, backup and restore, releases, adding a source) follows in Phase 4. The plan and all phases are in [`PLAN.md`](PLAN.md).

Phase 1 covers: the data model with migrations; the seed with the 19 projects of the paper plus European Integration (seeded as outside the paper's scope until the team decides) and the draft vocabularies; revisions with diff and restore; comments; the HTTP API; tables with server-side filters, sorting and export; detail pages with editing; and the start via Docker.

Phase 2 adds data acquisition: collectors for the ministry's project list (C1), the projects' official websites (C2), the Diia service catalogue (C3), the ministry's news on thedigital.gov.ua (C4) and on kmu.gov.ua (C4b) and the Wayback Machine (C5), plus a tagger that suggests links from documents to projects and services and proposes events from phrases in their texts; raw snapshots of every response and runs with their fetch log and messages; reconciliation with a review inbox, where collected values that differ from manual ones wait as proposals; source observations, merging of duplicates, a CSV/XLSX importer and manual documents (an upload, a URL or an archived copy).

## Quick start with Docker (server)

Requirements: Docker Engine with Docker Compose v2.24 or newer.

```bash
git clone <repository URL> mdt-portfolio && cd mdt-portfolio
cp .env.example .env      # set CONTACT_EMAIL (needed by the collectors); optional: HOST and PORT
docker compose up -d      # or: make up
```

Then open **http://127.0.0.1:8080** on the server (from another machine see [Access](#access)).

- The first start builds the image, creates `data/app.db`, applies the database migrations and loads the seed. Every later start runs the migrations and the seed again; both are idempotent, so existing data and manual changes are kept.
- `docker compose ps` shows the health status; `docker compose logs -f app` (or `make logs`) follows the logs.
- `make up` does the same as `docker compose up -d --build`, but first creates `./data` (so it belongs to your user, not to root), waits until the health check passes and records the git commit in the image label `org.opencontainers.image.revision`.
- After `git pull`, rebuild with `make up` (or `docker compose up -d --build`). A plain `docker compose up -d` only builds the image if it does not exist yet.
- `docker compose down` (or `make down`) stops and removes the container. The data in `./data` stays.

**Ports:** inside the container the app always listens on 0.0.0.0:8080. `HOST` and `PORT` in `.env` only choose the interface and port on the host where Docker publishes it. The default `127.0.0.1:8080` makes the app reachable from the server itself only.

## Quick start for local development

Requirements: Python 3.13 and [uv](https://docs.astral.sh/uv/) (Docker and CI use uv 0.11.32), Node.js 22 with npm, GNU make. The E2E tests also need Chromium for Playwright: where `/opt/pw-browsers` exists the Makefile uses it, elsewhere run `cd frontend && npx playwright install chromium` once.

```bash
make install    # backend: uv sync --locked; frontend: npm ci
make dev        # backend on http://127.0.0.1:8000 (auto-reload) + Vite dev server
```

Open the URL that Vite prints (by default http://localhost:5173). The Vite dev server proxies `/api` to the backend. `make dev` applies the migrations and loads the seed into `data/app.db` first; `make backend-dev` and `make frontend-dev` start only one of the two.

The server never creates, migrates or seeds the database itself: `mdt serve` refuses to start (with an `error:` line) while the database file is missing or not at the current schema, so run `mdt db upgrade` and `mdt seed` first (`make dev`, `make migrate`/`make seed` and the container entrypoint do this). The other commands that read or write data (`seed`, `recompute`, `check`, `reindex`, `collect`, `runs`, `import`) refuse in the same way; only `mdt db upgrade` creates the database. Without a frontend build (`make build`) the API works, and the pages answer with a hint to build the frontend.

Other common commands (`make help` lists all):

| Command | What it does |
|---|---|
| `make check` | All quality gates: lint, type checks, unit tests, frontend build, E2E smoke tests |
| `make test` | Backend (pytest) and frontend (Vitest) unit tests |
| `make e2e` | Build the frontend and run the Playwright smoke tests (two servers with temporary databases: one for the Phase 1 scenarios, one whose collectors answer from the stored fixtures) |
| `make lint` · `make format` · `make typecheck` | Linters · auto-formatting · mypy and tsc |
| `make migrate` · `make seed` · `make recompute` · `make db-check` | Database migrations · seed (idempotent) · recompute derived fields · integrity report |
| `make collect SOURCE=<name> [MODE=full]` · `make fixtures SOURCE=wayback` · `make sources-check` | Run a collector in the foreground · record a collector's fixture list · re-check every source host from this machine ([Data acquisition](#data-acquisition)) |
| `make up` · `make down` · `make logs` · `make docker-build` | Docker Compose |

The command-line tool `mdt` runs from the repository root as `uv run --project backend mdt <command>` (this is what the Makefile does): `db upgrade`, `seed [--dry-run]`, `recompute`, `check [--deep]` (integrity report; `--deep` also re-hashes every raw snapshot file), `reindex` (rebuild the full-text search tables, in batches, so the app stays usable meanwhile) and `serve [--host] [--port] [--reload]`; for data acquisition `collect <name> [--mode incremental|full] [--limit N] …`, `runs [--collector NAME] [--status STATUS]` and `runs show <run_id>`, `import <file> --type <type> [--dry-run] …`, `fixtures capture <name>` and `sources check [<name> …]` (all options: [`docs/COLLECTORS.md`](docs/COLLECTORS.md) §11). `uv run --project backend mdt --help` lists them.

## Configuration

Settings come from environment variables, usually from a `.env` file in the repository root (gitignored). [`.env.example`](.env.example) lists every variable with an explanation; copy it to `.env` and adjust. The repository contains no secrets.

| Variable | Default | Purpose |
|---|---|---|
| `HOST`, `PORT` | `127.0.0.1`, `8080` | Docker: host interface and port where the app is published. Without Docker: default listen address of `mdt serve` (`make dev` always uses 127.0.0.1:8000) |
| `CONTACT_EMAIL` | unset (`.env.example` has a placeholder) | Contact address in the User-Agent of the collectors and of manual URL fetches. Required for collector runs with network access, "From URL" fetches, `mdt fixtures capture` and `mdt sources check`: they are refused while it is missing, not an e-mail address, or in a reserved example domain such as the placeholder (replay mode needs none). Use a project or functional address; it never appears in the repository, exports or releases |
| `PROJECT_URL` | empty | Optional public project page in the User-Agent (`+<PROJECT_URL>`); checked at startup |
| `MAX_COMMENT_CHARS`, `FOCAL_ORG_SEED_KEY`, `LOG_LEVEL` | `10000`, `ministry-of-digital-transformation`, `INFO` | Comment length limit, seed key of the ministry, log level |
| `SOURCES_FILE` | `sources.yaml` | Collector settings: per-host intervals, excluded hosts, licences, options ([`docs/COLLECTORS.md`](docs/COLLECTORS.md) §3). Fixed inside the container |
| `RUN_STALE_AFTER_S` | `300` | A running collector run without a heartbeat for this many seconds counts as interrupted (failed), so a new run can start |
| `COLLECTOR_REPLAY_DIR` | empty (off) | Replay mode for development and E2E tests: collector runs and URL fetches answer from the fixtures in this directory instead of the network. Always off inside the container |
| `DATA_DIR`, `DATABASE_URL`, `CODEBOOK_DIR`, `SEED_DIR`, `FRONTEND_DIST` | `data`, `sqlite:///<DATA_DIR>/app.db`, `codebook`, `seed`, `frontend/dist` | Paths for local development; relative directory paths resolve against the repository root. Inside the container they are fixed |
| `APP_UID`, `APP_GID` | `1000` | Docker build: user and group that run the app and own `./data` |

docker compose reads `.env` both for `${...}` substitution in `docker-compose.yml` (`HOST`, `PORT`, `APP_UID`, `APP_GID`) and as environment of the container. Inside the container compose pins `HOST`, `PORT` and all paths, so a `.env` with local development values cannot redirect them.

## Access

By default the app is reachable on **127.0.0.1** only, that is from the server itself (Docker publishes the port on 127.0.0.1; `mdt serve` listens there). The app has one user and no login of its own; who can reach the server is decided by the server's environment (D-15). To use the app from another machine:

1. **SSH tunnel** (no change on the server): `ssh -N -L 8080:127.0.0.1:8080 <user>@<server>`, then open http://127.0.0.1:8080 on your own machine.
2. **Another network interface** (e.g. a VPN address): set `HOST` in `.env` to that address and restart with `make up`. The interface must be up before Docker starts the container, otherwise publishing the port fails.

## Data acquisition

The collectors fetch the sources politely (robots.txt, about one request per second per host, a User-Agent with the contact address, no circumvention of protections) and keep what they fetch as raw snapshots. Sources, collectors and their options: [`docs/COLLECTORS.md`](docs/COLLECTORS.md) and [`docs/SOURCES.md`](docs/SOURCES.md).

- **Before the first run** set `CONTACT_EMAIL` in `.env` to a real project or functional address ([Configuration](#configuration)).
- **Run a collector** under **Runs** ("Start run") or on the command line: `make collect SOURCE=ministry_projects` (add `MODE=full` for a full run); in the container `docker compose exec -u app app mdt collect ministry_projects`. The collectors are `ministry_projects`, `project_sites`, `diia_catalog`, `ministry_news`, `kmu_news` and `wayback`, plus the `tagger`, which reads only stored texts. One run at a time; a second run of the same collector creates no duplicates and no empty revisions. **Runs** lists every run with its statistics, fetch log and messages; **Sources** shows per collector what its source listed (observations, first and last seen).
- **Review:** collected values never overwrite a value that a person set, imported or accepted. Differences, new records, events found in texts and possible duplicates become proposals in the **Review** inbox: accept, edit and accept, or reject.
- **Import** a CSV or XLSX file under **Import** (mapping, dry run, run) or with `mdt import <file> --type <type> --dry-run`, then without `--dry-run`.
- **Add a document** in the Documents table ("+ Add document"): upload a file, or fetch a URL or a Wayback Machine capture URL (an archived copy).
- **On the target server**, still to do: `docker compose run --rm app mdt sources check` re-checks every source host from there (geo-blocking; in a checkout with uv, `make sources-check` does the same), and `docker compose run --rm app mdt fixtures capture wayback` records the real Wayback fixtures ([`docs/COLLECTORS.md`](docs/COLLECTORS.md) §11; [`docs/SOURCES.md`](docs/SOURCES.md) §5 lists every check still open there).
- **Replay mode** for development: with `COLLECTOR_REPLAY_DIR` set (e.g. to `backend/tests/fixtures/ministry_projects`), runs and URL fetches answer from the stored fixtures instead of the network and need no contact address. It is for development only: the container pins it empty, so the server's database never runs in replay mode.

## Data

- All runtime data lives in `./data` on the host (bind mount to `/app/data`): the SQLite database `data/app.db` and the raw snapshots in `data/raw/` (the responses fetched by the collectors and by URL fetches, and every uploaded file, import files included; stored once per content and never changed); `mdt fixtures capture` run in the container writes to `data/fixtures/`; backups follow in Phase 4. The directory is gitignored and survives rebuilds and `docker compose down`. `./releases` is mounted at `/app/releases` for the dataset releases of Phase 4. It is part of the repository (until Phase 4 it holds only a README), so it exists in every clone and belongs to your user; Docker would create a missing directory as root.
- On every start the container hands `./data` to the user that runs the app (UID/GID 1000). If your host user has other IDs (`id -u`, `id -g`), set `APP_UID` and `APP_GID` in `.env` before building, so the files stay yours on the host.
- Automatic daily backups arrive in Phase 4. Until then: `docker compose stop`, copy the whole `data/` directory (the database and the raw snapshots it refers to), `docker compose start`. Do not copy `app.db` alone while the app is running.
- CLI commands inside the running container: `docker compose exec -u app app mdt check` (keep `-u app`, otherwise files created in `./data` may belong to root). One-off commands: `docker compose run --rm app mdt check`.

## Data integrity

These rules come from the project brief and are enforced by the app where it can:

- **No invented facts.** Every value comes from a captured source (URL or document with retrieval time), the seed data of the brief (provenance `seed`), an import, or a person on the team. This applies to seeds, fixtures and test data as well. There is no machine translation: a missing English name stays empty.
- **Provenance per field.** Every write records its channel (a change made in the app, the seed, an import or a collector run) and, per field, where the value came from. Derived values (period, war trajectory, launch) are marked as derived and link the deciding event.
- **Manual corrections win.** Automatically collected values never overwrite a value that a person set; differences become proposals in the review inbox. The seed, too, never overwrites a value that a person has set, cleared, restored or verified.
- **Nothing is hard-deleted.** Every change creates a revision with a full snapshot; deleted records go to the trash and can be undeleted, and any earlier version can be restored.

## Exports

Every table can be exported as CSV ("for analysis tools") or XLSX ("for Excel, exact values"), with the current filters, sort order and columns.

**File formats:** CSV files are UTF-8 with a byte order mark and hold the values verbatim. XLSX stores every text value as a text cell, never as a formula, so values stay exact. Details: [`docs/API.md`](docs/API.md) §5.

## Troubleshooting

- **Container stays "unhealthy":** check `make logs`. The health check requests `http://127.0.0.1:8080/api/health` inside the container.
- **"/app/data is not writable":** the container was started as a non-root user. Make `./data` writable for that user, e.g. `sudo chown -R 1000:1000 data`.
- **`error: database … does not exist`** from `mdt serve`: run `make migrate` and `make seed` (or `mdt db upgrade` and `mdt seed`) first.
- **Port already in use:** set another `PORT` in `.env` and run `make up`.
- **A collector run or a "From URL" fetch is refused because of `CONTACT_EMAIL`** (`collector_unavailable`, reason `contact_email_missing`; the start dialog under Runs shows the reason): set `CONTACT_EMAIL` in `.env` to a real address, not the placeholder, and restart the app (Docker: `docker compose up -d --force-recreate`).
- **`git pull` fails with "unable to create file releases/…: Permission denied":** Docker created `./releases` as root, in a checkout from before the directory was part of the repository. Run `sudo chown -R "$(id -u):$(id -g)" releases` once, then `git pull` again.

## Documentation

- [`PLAN.md`](PLAN.md): architecture, data model rationale, data acquisition, versioning, UI sketch, phases, risks, decisions for the team, notes for the paper.
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md), [`docs/API.md`](docs/API.md), [`docs/UI.md`](docs/UI.md): the binding contracts for the data model, the HTTP API and the pages (Phase 1, extended for Phase 2); [`docs/COLLECTORS.md`](docs/COLLECTORS.md): the binding Phase 2 contract for the collectors, the importer and manual documents.
- [`docs/CODEBOOK.md`](docs/CODEBOOK.md): vocabularies and coding rules; [`docs/SOURCES.md`](docs/SOURCES.md): source register.
- [`CLAUDE.md`](CLAUDE.md): working rules for contributors (data integrity, collection rules, conventions, commands).
