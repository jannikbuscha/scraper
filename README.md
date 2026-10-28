# MDT Portfolio

Research data platform for the paper **"Digital Innovation for Governments under Crisis"** (ICIS 2026 Paper Development Workshop). It maps the portfolio of projects and digital services of the Ministry of Digital Transformation of Ukraine (Мінцифри) and builds a document corpus for the qualitative document analysis. In the web app the research team views, filters, sorts, comments on and corrects the data, with a complete revision history.

Guiding principle: **traceability before completeness.** Every value records where it came from (seed, collector run, import or a named person), automatic updates never overwrite manual corrections, and nothing is hard-deleted.

> **Status: Phase 1 (skeleton) is in progress.** This README covers local development, the Docker start and team access. The full README (deployment, collectors and schedules, backup and restore, releases, adding a source) follows in Phase 4. The plan and all phases are in [`PLAN.md`](PLAN.md).

Phase 1 covers: the data model with migrations; the seed with the 19 projects of the paper plus European Integration (seeded as outside the paper's scope until the team decides) and the draft vocabularies; revisions with diff and restore; comments; the HTTP API; tables with server-side filters, sorting and export; detail pages with editing; and the start via Docker. Collectors follow in Phase 2.

## Quick start with Docker (server)

Requirements: Docker Engine with Docker Compose v2.24 or newer.

```bash
git clone <repository URL> mdt-portfolio && cd mdt-portfolio
cp .env.example .env      # optional: review ALLOWED_HOSTS and TEAM_MEMBERS
docker compose up -d      # or: make up
```

Then open **http://127.0.0.1:8080** on the server (from other machines see [Team access](#team-access)).

- The first start builds the image, creates `data/app.db`, applies the database migrations and loads the seed. Later starts do the same idempotently: existing data and manual changes are kept.
- `docker compose ps` shows the health status; `docker compose logs -f app` (or `make logs`) follows the logs.
- `make up` does the same as `docker compose up -d --build`, waits until the health check passes and records the git commit in the image label `org.opencontainers.image.revision`.
- After `git pull`, rebuild with `make up` (or `docker compose up -d --build`). A plain `docker compose up -d` only builds the image if it does not exist yet.
- `docker compose down` (or `make down`) stops and removes the container. The data in `./data` stays.

**Ports:** inside the container the app always listens on 0.0.0.0:8080. `HOST` and `PORT` in `.env` only choose the interface and port on the host where Docker publishes it. The default `127.0.0.1:8080` makes the app reachable from the server itself only.

## Quick start for local development

Requirements: Python 3.13 and [uv](https://docs.astral.sh/uv/) (Docker and CI use uv 0.11.32), Node.js 22 with npm, GNU make. The E2E tests also need Chromium for Playwright (`cd frontend && npx playwright install chromium`).

```bash
make install    # backend: uv sync --locked; frontend: npm ci
make dev        # backend on http://127.0.0.1:8000 (auto-reload) + Vite dev server
```

Open the URL that Vite prints (by default http://localhost:5173). The Vite dev server proxies `/api` to the backend. `make dev` applies the migrations and loads the seed into `data/app.db` first.

Other common commands (`make help` lists all):

| Command | What it does |
|---|---|
| `make check` | All quality gates: lint, type checks, unit tests, frontend build, E2E smoke tests |
| `make test` | Backend (pytest) and frontend (Vitest) unit tests |
| `make e2e` | Build the frontend and run the Playwright smoke tests |
| `make lint` · `make format` · `make typecheck` | Linters · auto-formatting · mypy and tsc |
| `make migrate` · `make seed` · `make recompute` · `make db-check` | Database migrations · seed (idempotent) · recompute derived fields · integrity report |
| `make up` · `make down` · `make logs` · `make docker-build` | Docker Compose |

## Configuration

Settings come from environment variables, usually from a `.env` file in the repository root (gitignored). [`.env.example`](.env.example) lists every variable with an explanation; copy it to `.env` and adjust. The repository contains no secrets.

| Variable | Default | Purpose |
|---|---|---|
| `HOST`, `PORT` | `127.0.0.1`, `8080` | Docker: host interface and port where the app is published. Without Docker: default listen address of `mdt serve` |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost` | Host-header allowlist against DNS rebinding. Add the name the team uses (VPN address, proxy host name). Keep `127.0.0.1`: the container health check uses it |
| `TEAM_MEMBERS` | empty | Names offered by the "Who are you?" author picker, comma-separated |
| `CONTACT_EMAIL` | placeholder | Contact address in the collectors' User-Agent (Phase 2). Replace the placeholder before running collectors |
| `MAX_COMMENT_CHARS`, `FOCAL_ORG_SEED_KEY`, `LOG_LEVEL` | `10000`, `ministry-of-digital-transformation`, `INFO` | Comment length limit, seed key of the ministry, log level |
| `DATA_DIR`, `DATABASE_URL`, `CODEBOOK_DIR`, `SEED_DIR`, `FRONTEND_DIST` | `data/`, `data/app.db`, `codebook/`, `seed/`, `frontend/dist` | Paths for local development. Inside the container they are fixed |
| `APP_UID`, `APP_GID` | `1000` | Docker build: user and group that run the app and own `./data` |

docker compose reads `.env` both for `${...}` substitution in `docker-compose.yml` (`HOST`, `PORT`, `ALLOWED_HOSTS`, `APP_UID`, `APP_GID`) and as environment of the container.

## Team access

By default the app is reachable on **127.0.0.1** only, that is from the server itself (Docker publishes the port on 127.0.0.1; `mdt serve` listens there). **The app has no login.** Anyone who can reach it can read and change all data, and author names are self-declared. Never expose it unprotected, for example by setting `HOST=0.0.0.0` on a machine that is reachable from the internet. Note that ports published by Docker bypass host firewalls such as ufw.

Ways for the team to reach it, from the simplest to the most comfortable:

1. **SSH tunnel** (no change on the server): `ssh -N -L 8080:127.0.0.1:8080 <user>@<server>`, then open http://127.0.0.1:8080 on your own machine. Every team member needs SSH access to the server.
2. **VPN** (e.g. WireGuard or Tailscale): set `HOST` to the server's VPN address, so the app is published on the VPN interface only, and add that address (or the VPN host name) to `ALLOWED_HOSTS`. Then restart with `make up`. The VPN interface must be up before Docker starts the container, otherwise publishing the port fails.
3. **Reverse proxy with TLS and authentication** (e.g. Caddy or nginx) on the server, forwarding to `127.0.0.1:8080`. Use basic auth, single sign-on or at least an IP allowlist, and add the proxy's host name to `ALLOWED_HOSTS`. The proxy must pass the original `Host` header on (Caddy does this by default; nginx needs `proxy_set_header Host $host;`), otherwise writes fail the same-origin check. A minimal Caddy sketch:

   ```
   mdt.example.org {
       basic_auth {
           # user name and bcrypt hash from: caddy hash-password
           team <hash>
       }
       reverse_proxy 127.0.0.1:8080
   }
   ```

## Data

- All runtime data lives in `./data` on the host (bind mount to `/app/data`): currently the SQLite database `data/app.db`; later raw snapshots, backups and import files. The directory is gitignored and survives rebuilds and `docker compose down`.
- On every start the container hands `./data` to the user that runs the app (UID/GID 1000). If your host user has other IDs (`id -u`, `id -g`), set `APP_UID` and `APP_GID` in `.env` before building, so the files stay yours on the host.
- Automatic daily backups arrive in Phase 4. Until then: `docker compose stop`, copy the whole `data/` directory, `docker compose start`. Do not copy `app.db` alone while the app is running.
- CLI commands inside the running container: `docker compose exec -u app app mdt check` (keep `-u app`, otherwise files created in `./data` may belong to root). One-off commands: `docker compose run --rm app mdt check`.

## Troubleshooting

- **Container stays "unhealthy":** check `make logs`. The health check requests `http://127.0.0.1:8080/api/health` inside the container, so `ALLOWED_HOSTS` must contain `127.0.0.1`.
- **"/app/data is not writable":** the container was started as a non-root user. Make `./data` writable for that user, e.g. `sudo chown -R 1000:1000 data`.
- **Port already in use:** set another `PORT` in `.env` and run `make up`.

## Documentation

- [`PLAN.md`](PLAN.md): architecture, data model rationale, data acquisition, versioning, UI sketch, phases, risks, decisions for the team, notes for the paper.
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md), [`docs/API.md`](docs/API.md), [`docs/UI.md`](docs/UI.md): the binding Phase 1 contracts.
- [`docs/CODEBOOK.md`](docs/CODEBOOK.md): vocabularies and coding rules; [`docs/SOURCES.md`](docs/SOURCES.md): source register.
- [`CLAUDE.md`](CLAUDE.md): working rules for contributors (data integrity, collection rules, conventions, commands).
