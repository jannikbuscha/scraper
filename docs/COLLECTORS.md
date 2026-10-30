# Collectors, importer and manual documents

> **Status:** Phase 2 contract, 2026-10-30, revised the same day after a four-lens review (integrity, source fit, completeness, simplicity). Binding like `docs/DATA_MODEL.md`, `docs/API.md` and `docs/UI.md`: implementations follow it, and every interface change updates it in the same change.
> **Related:** data rules in `docs/DATA_MODEL.md` §14–§18 (tables, reconciliation, proposals, imports, merging); HTTP endpoints in `docs/API.md` §7; pages in `docs/UI.md` §8; source facts and evidence in `docs/SOURCES.md` (cited here by section, e.g. SOURCES S1); fixtures in `backend/tests/fixtures/` (`fixtures/<dir>/<name>` below).
> **Rules that apply everywhere:** no value from model knowledge (CLAUDE.md, "Data integrity"); collectors never overwrite a value a person set, accepted, imported, restored, seeded or verified (DATA_MODEL §15.5); every collected value names the snapshot it was parsed from (§5); robots.txt and the politeness rules of §4 are never relaxed; no circumvention of protections; tests run without network.

## 1. Scope

**Phase 2 builds:**

| Key | Collector | Source (SOURCES) | Creates directly | Proposes |
|---|---|---|---|---|
| `ministry_projects` | C1 ministry project list | S1 | documents (project pages) | projects, field updates (including official URLs linked from project pages), possibly discontinued |
| `project_sites` | C2 the projects' official URLs (generic pass) | S2 | documents | field updates |
| `diia_catalog` | C3 Diia portal service catalogue | S3 | services (under project `diia`), documents | field updates, possible duplicates, possibly discontinued |
| `ministry_news` | C4 ministry news, documents, `/ministry`, microsites, files | S4 | documents | field updates, possible duplicates |
| `kmu_news` | C4b ministry news on kmu.gov.ua | S4b | documents | field updates, possible duplicates |
| `wayback` | C5 Wayback Machine (CDX) | S5 | `first_archived` events for exact URL matches | `first_archived` events for other URLs |
| `tagger` | built-in, no network: alias tagging and event patterns over stored document texts | — | — (adds suggested document links) | events |

The tagger also runs inside every run that collects documents (C1–C4), so their runs add suggested links and `create_event` proposals too (§7.6, §7.7).

Plus: the polite HTTP client (§4), the raw snapshot store (§5), runs with fetch log and messages (§6), reconciliation and proposals (DATA_MODEL §15, §16), the review inbox, runs and sources pages (UI §8), merging duplicate projects and services (DATA_MODEL §18), the tabular importer (§9) and manual documents, including archived copies from the Wayback Machine (§10).

**Deferred** (§14): the cross-check collectors C2a (Digital State UA) and C3b (Diia service guide) while decision D-12 is open; C6 legal acts and C7 Telegram and data.gov.ua; Wayback reconstruction of the catalogues and an automatic Wayback fallback inside collectors; schedules (Phase 4).

## 2. Architecture

```
sources.yaml ─▶ collector module ─▶ PoliteHttpClient ─▶ raw snapshot store (data/raw, raw_snapshot)
                    │  (discovery,          │                └─ fetch_log (every attempt)
                    │   pagination)         ▼
                    └── parse(snapshot) ─▶ candidates ─▶ reconciler ─┬─▶ apply_change (channel collector, revision.run_id)
                         (pure functions)                            ├─▶ proposals (review inbox)
                                                                     └─▶ source_observation (first/last seen, binding)
```

- **Package layout** (`backend/src/mdt/`): `collectors/` with `base.py` (the interfaces of §2.1), `client.py` (PoliteHttpClient), `robots.py`, `store.py` (snapshot store), `runs.py` (run lifecycle and threads), `replay.py` (fixture replay transport), `parsing/` (shared helpers of §7: `turbostream.py`, `tiptap.py`, `html_text.py`, `sitemaps.py`, `dates.py`, `language.py`, `texts.py`), `tagger.py`, `duplicates.py`, and one module per collector (`ministry_projects.py`, `project_sites.py`, `diia_catalog.py`, `ministry_news.py`, `kmu_news.py`, `wayback.py`); `domain/reconcile.py`, `domain/proposals.py`, `domain/observations.py`, `domain/merge.py`; `importers/tabular.py`; `documents/manual.py` and `documents/extract.py` (text extraction from PDF, DOCX, HTML, TXT).
- **One process (D-15):** a run started from the UI executes in a thread of the server process, a run started with `mdt collect` in the CLI process. There are no subprocesses, no queue, no scheduler and no message broker; at most one run runs at a time in the whole database (DATA_MODEL §14.2).

### 2.1 Interfaces

The framework and the collector modules meet only here (`collectors/base.py`; types abbreviated):

```python
@dataclass(frozen=True)
class Evidence:                      # where a candidate was read
    raw_snapshot_id: str
    source_url: str
    quote: str | None = None         # verbatim, at most 1 000 characters
    locator: str | None = None

@dataclass(frozen=True)
class LinkHint:                      # a link the source itself states (documents)
    snippet: str
    subject_id: str | None = None    # a known record, or
    subject_key: str | None = None   # an observation key of this collector, resolved through its binding

@dataclass
class Candidate:                     # DATA_MODEL §15.1
    entity_type: str                 # project | service | document
    key: str                         # observation key, stable per collector (at most 500 characters)
    evidence: Evidence               # the main snapshot
    label: str | None = None
    url: str | None = None
    external_id: str | None = None
    fields: dict[str, Any] = {}      # observed values of declared `writes` only; absent = not observed
    proposed: dict[str, Any] = {}    # observed values of declared `propose_only` fields
    field_snapshots: dict[str, list[str]] = {}  # field -> snapshots it was parsed from; default [evidence.raw_snapshot_id]
    text: str | None = None          # documents: extracted text
    text_snapshot_id: str | None = None
    extraction_method: str | None = None
    links: list[LinkHint] = []       # documents
    details: dict[str, Any] = {}     # observation details

@dataclass(frozen=True)
class TypeDeclaration:               # DATA_MODEL §15.1
    creates: bool                    # unmatched: direct create (True) or create_entity proposal (False)
    writes: frozenset[str]
    propose_only: frozenset[str] = frozenset()
    match_rules: tuple[str, ...] = ()     # "external_id", "document", "url_fields" (DATA_MODEL §15.3)
    discontinued: bool = False

class Collector(Protocol):
    NAME: str
    VERSION: int                     # bumped when parsing or mapping changes; stats.extra.collector_version
    DECLARATION: Mapping[str, TypeDeclaration]
    def run(self, ctx: RunContext) -> None: ...

class RunContext(Protocol):
    run_id: str; mode: str; params: Mapping[str, Any]; options: Mapping[str, Any]
    client: PoliteHttpClient
    def reconcile(self, candidate: Candidate) -> Outcome: ...          # one write unit, DATA_MODEL §15.11
    def observe(self, entity_type: str, key: str, *, url: str | None = None,
                label: str | None = None, details: Mapping | None = None) -> None: ...  # sighting, DATA_MODEL §15.7
    def first_archived(self, subject_id: str, capture: Capture, *, exact: bool) -> Outcome: ...  # C5, DATA_MODEL §15.12
    def message(self, level: str, code: str, text: str, *, url: str | None = None,
                snapshot_id: str | None = None, subject_id: str | None = None,
                details: Mapping | None = None) -> None: ...           # §6.6
    def listing_complete(self) -> None: ...                            # complete_listing = 1 (§8 per collector)
    def cancelled(self) -> bool: ...
    def count(self, key: str, n: int = 1) -> None: ...                 # stats.extra[key] += n
    # read helpers, each in its own short read transaction
    def live_records(self, entity_type: str, fields: Sequence[str]) -> list[dict]: ...
    def observation(self, key: str) -> Observation | None: ...
    def latest_snapshot(self, url: str) -> Snapshot | None: ...        # newest stored response for the URL (any run)
```

- `Outcome` = `{action: "created" | "updated" | "unchanged" | "proposed" | "blocked" | "observed", record_id, proposal_ids}`; `Capture` = `{timestamp, original, archive_url, cdx_row, request_url, raw_snapshot_id, fetched_at}`.
- **The framework, not the collector,** runs the tagger and the event patterns for document candidates whose text is new or changed (§7.6, §7.7), the duplicate detection after the run's last candidate (§7.8), the disappearance step (DATA_MODEL §15.7), the stats, the heartbeat and the end status (§6).

## 3. `sources.yaml` and settings

One file in the repository root (setting `SOURCES_FILE`). It holds **operational settings only**; what a collector parses and may write is code, documented in §8. It is validated when the app starts (an invalid file stops startup like an unusable `codebook/parameters.yaml`, API §6) and by every CLI command that uses it.

```yaml
# Collector settings (docs/COLLECTORS.md §3). No secrets; CONTACT_EMAIL comes from .env.
version: 1
defaults:
  min_interval_s: 1.0          # per host, between the end of one request and the start of the next
  timeout_connect_s: 10
  timeout_read_s: 30
  max_bytes: 26214400          # 25 MiB per response
  max_redirects: 5
  retries: 2                   # extra attempts after 429/502/503/504 and network errors
  backoff_base_s: 5
  max_wait_s: 600              # longest Retry-After or Crawl-delay waited for (§4.6)
  discontinued_after_runs: 2   # DATA_MODEL §15.7
  exclude_hosts: [codeua.com]  # out of scope (data lead, 2026-10-30, SOURCES S2); never requested, C5 included
collectors:
  ministry_projects:
    label: "Ministry project list (thedigital.gov.ua/projects)"
    source: S1                 # ID in docs/SOURCES.md
    enabled: true
    licence: {code: cc_by_4_0, statement: "Весь контент доступний за ліцензією Creative Commons Attribution 4.0 International license, якщо не зазначено інше"}
    options: {}
  project_sites:
    label: "Official URLs of the projects (generic pass)"
    source: S2
    enabled: true
    licence: {code: unknown}   # decided per page (§8.2)
    options:
      soft_404_patterns: {usf.com.ua: ["Post not found"]}
  wayback:
    label: "Wayback Machine (CDX API)"
    source: S5
    enabled: true
    needs_server_check: true   # shown in the UI until the server checks are done (SOURCES §5)
    hosts:
      web.archive.org: {min_interval_s: 5.0}
    licence: {code: unknown, statement: "Archived third-party content; cite as archive copy"}
    options:
      prefixes: ["thedigital.gov.ua/projects/", "diia.gov.ua/services/", "diia.gov.ua./services/"]
      page_limit: 5000
    fixtures:                  # §11; the full list is in §8.5
      - {name: robots_web_archive, url: "https://web.archive.org/robots.txt", purpose: "robots.txt of the CDX host"}
  tagger:
    label: "Alias tagging and event patterns (no network)"
    builtin: true
    enabled: true
```

| Key | Meaning |
|---|---|
| `version` | file format version (1) |
| `defaults` | client and reconciliation settings; a collector may override any of them at its top level |
| `label`, `source` | display name and SOURCES ID |
| `enabled` | a disabled collector cannot be started (API `409 collector_unavailable`) |
| `needs_server_check` | true until the source checks from the target server are done (SOURCES §5); the UI shows a notice, runs are still allowed |
| `hosts` | optional per-host settings (`min_interval_s`). Collectors request only URLs they build from their source data, and redirects are followed to any host (robots.txt is checked for every hop, §4.5) |
| `exclude_hosts` | hosts never requested (`defaults` and per collector, merged) |
| `licence` | default licence of the source's documents: `code` from the `license` vocabulary, `statement` as captured (SOURCES) |
| `options` | collector-specific options (§8); run parameters (§6.4) may override some per run |
| `fixtures` | the URL list of `mdt fixtures capture` (§11); in Phase 2 only `wayback` has one |
| `builtin` | a collector without network (only `tagger`) |

The complete file is part of the Phase 2 implementation, with one entry per collector of §1 and the options of §8.

**Settings** (`.env`, documented in `.env.example` except the test-only one):

| Setting | Type and default | Used for | Docker (compose) |
|---|---|---|---|
| `CONTACT_EMAIL` | e-mail address, none | User-Agent; required for collector runs with network and manual fetches (§4.4) | from `.env` |
| `PROJECT_URL` | URL, empty | optional part of the User-Agent (§4.4) | from `.env` |
| `SOURCES_FILE` | path, `sources.yaml` | this section | pinned to `/app/sources.yaml` (the image copies the file: `.dockerignore` allowlist and `COPY`) |
| `RUN_STALE_AFTER_S` | integer, 300 | stale runs (§6.3) | from `.env` |
| `COLLECTOR_REPLAY_DIR` | path, empty | replay mode for development and E2E (§4.10) | pinned empty, so the server's database never runs in replay mode |
| `COLLECTOR_RUN_INLINE` | bool, false | API tests: `POST /api/runs` answers after the run has finished (§6.2) | not set |

`backend/tests/test_docker_layout.py` checks the two pins.

## 4. PoliteHttpClient

`collectors/client.py`, built on httpx2 (§13). One client per run (and one per manual fetch); the per-host throttle state is shared by all clients of the process. Every rule below has a test (§12.3).

### 4.1 URLs and hosts

- Only `http` and `https` URLs without userinfo; the host is lower-cased, IDNA-encoded, stripped of a trailing dot (`diia.gov.ua.` → `diia.gov.ua`) and of a default port; an empty path becomes `/`; path and query keep their case (`/services/RD4U` exists only in upper case); the fragment is removed.
- Refused without a request (`fetch_log.outcome = refused`, with the reason in `error`): excluded hosts (§3), paths starting with `/cdn-cgi/` (Cloudflare trap and e-mail-protection links, SOURCES §2), hosts blocked or throttled earlier in the run (§4.6, §4.7), hosts whose robots.txt is unavailable in this run (§4.2).
- Collectors never follow links marked `rel=nofollow` together with `aria-hidden` (hidden trap links, SOURCES §2); link extraction helpers drop them.

### 4.2 robots.txt

- Fetched once per origin (scheme, host, port) and run, before the first request to it, with `Accept: */*` (osvita.diia.gov.ua answered `Accept: text/plain` with HTTP 406, SOURCES §2), following up to 5 redirects; logged with `purpose = robots`; a body is stored as a snapshot like any response.
- **Interpretation** (RFC 9309, longest match, `*` and `$`, Allow wins ties; parser: protego, §13):
  - a 2xx body is parsed after preprocessing: a UTF-8 BOM is removed; a body that starts with `<` (after whitespace), or an HTML body without any robots field (`user-agent`, `allow`, `disallow`, `crawl-delay`, `sitemap`), counts as **no robots.txt** (allow all; plan2.diia.gov.ua); Allow/Disallow lines without any `User-agent` line get `User-agent: *` prepended, so they are honoured (playcity.gov.ua); lines that are not `field: value` (e.g. HTML after the rules, usf.com.ua) are ignored;
  - **404 and 410** → allow all (RFC 9309 "unavailable");
  - **401, 403, 429 or a challenge page** (§4.7) → the host is **blocked** for the run;
  - **other 4xx (e.g. 400, 406), 5xx after the retries of §4.6, network errors** → robots.txt is **unavailable**: nothing is requested from the host in this run (every URL of it is `refused`, error "robots.txt unavailable"), and the run gets the error-level message `robots_unavailable`. Unlike a URL that a robots rule disallows, such a refusal makes the run `partial` (§6.5), and on the host of a collector's listing it fails the run (§4.7).
- **Group:** our product token `MDT-Portfolio-Research`, else `*`.
- **Every URL is checked before it is requested, including every redirect hop** (SOURCES §2: `https://www.kmu.gov.ua/news` redirects to the disallowed `/timeline`). A disallowed URL is not requested: `fetch_log.outcome = robots_disallowed`, `stats.robots_disallowed + 1`; a disallowed hop ends the fetch with that outcome.
- `Crawl-delay` and `Request-rate` of the selected group raise the host's interval when they are stricter (data.gov.ua: 10 s); a value above `max_wait_s` makes the host throttled for the run (§4.6).

### 4.3 Throttling

- Per host, the next request starts no earlier than `interval` after the previous request to that host **ended**, where `interval` = max(the host's `min_interval_s` (default 1.0 s; 5.0 s for `web.archive.org`), robots `Crawl-delay`, `60 / requests per minute` of `Request-rate`).
- Every attempt counts: robots.txt, each redirect hop, each retry. The state is process-wide (a lock-protected registry keyed by host), so a manual fetch in the server and a running collector share it. A collector run in the CLI process and a manual fetch in the server do not share it; at worst one extra request reaches a host, which stays within "about 1 request per second".
- Waiting is interruptible by a cancel request (§6.3).

### 4.4 Requests

- **User-Agent:** `MDT-Portfolio-Research/<app version> (+<PROJECT_URL>; mailto:<CONTACT_EMAIL>)`; without `PROJECT_URL` the part `+<PROJECT_URL>; ` is left out. Both come from `.env`, never from the repository.
- **`CONTACT_EMAIL` is required** for every run of a collector with network and for every manual fetch: they refuse to start when it is missing, empty, not an e-mail address, or in a reserved example domain (`example.org`, `example.com`, `example.net`, `*.example`, `*.invalid`, `*.test`, `localhost`); the `.env.example` placeholder is therefore refused. API: `409 collector_unavailable {reason: "contact_email_missing"}` (also reported as `available: false` in `GET /api/collectors`); CLI: `error: CONTACT_EMAIL is not set …`, exit 1. The rule does not apply to the built-in `tagger` or in replay mode (§4.10), where no request leaves the machine.
- **Other headers:** `Accept` per request (default `text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8`; JSON endpoints `application/json`), `Accept-Encoding: gzip, deflate`; no `Referer`, no browser imitation. Cookies set by a site are kept in memory for the run only and never stored.
- **Timeouts:** connect 10 s, read 30 s per chunk, 300 s per request.
- **Size limit:** `max_bytes` (default 25 MiB). A larger `Content-Length`, or a body that grows beyond it while streaming, aborts the request: `outcome = too_large`, nothing stored.
- **Methods:** GET; HEAD only where a collector needs headers alone.

### 4.5 Redirects

Followed by the client itself (never by httpx), at most `max_redirects` (5): each hop is checked against the robots.txt of its host (§4.2) and the excluded hosts (§4.1), waits for its host's interval (§4.3) and gets its own `fetch_log` row (`outcome = redirect`). Relative `Location` values are resolved. The final response records `final_url` and the hop list (`"<status> <url>"`).

### 4.6 Retries, backoff and throttling

- Retried, up to `retries` (2) extra attempts: **429, 502, 503, 504** and network errors (connect or read timeout, connection reset). Not retried: other 4xx, 500, `too_large`, refused or disallowed URLs.
- Wait before a retry: `Retry-After` when given (seconds or HTTP date), else `backoff_base_s × 2^(attempt−1)` with ±20 % jitter.
- A wait longer than `max_wait_s` (600 s), from a `Retry-After` or a robots `Crawl-delay`, is not started: the attempt ends as `http_error` (with `retry_after_s`), the host counts as **throttled** for the run (warning `throttled`), and later requests to it are refused.
- **Manual fetches** (§10.3) have a total budget of 60 s: a wait or retry that does not fit the remaining budget is not started (`502 fetch_failed {reason: "throttled"}`).

### 4.7 Block detection (no circumvention)

- A host is **blocked for the run** when: its robots.txt answers 401, 403 or 429 or a challenge page (§4.2); any response is a **challenge page** (Cloudflare: title "Just a moment..." or `cType: 'managed'` as in `fixtures/polite_client/robots_codeua_cloudflare_challenge.html`, or the response header `cf-mitigated: challenge`; Akamai: HTTP 403 with an "Access Denied" page, as www.undp.org answered in Phase 0b, SOURCES S8; the signature list lives in `client.py` and is tested on that fixture and on synthetic pages); or three consecutive responses from it are 403 or 429 after retries.
- Then: `outcome = blocked` for that response, run message `blocked` (host, URL, status, matched signature), no further request to the host in this run (`refused`), and the run ends `partial` at best.
- **Listing host:** a collector whose listing host (§8: the host of its listing pages or sitemaps; for C5 `web.archive.org`) is blocked, throttled or has an unavailable robots.txt before the listing is complete **fails** (`error = "<host>: blocked"`, `"… throttled"` or `"… robots.txt unavailable"`). The run page shows it, which is how a blocked gov.ua site is reported (CLAUDE.md collection rules); archived copies of single pages can then be added by hand (§10.3).
- Never: CAPTCHA solving, proxy rotation, other User-Agents, browser imitation, retries with changed headers.

### 4.8 Conditional requests

When the latest live snapshot of the same URL with HTTP status 200 carries an `etag` or `last-modified`, the client sends `If-None-Match` / `If-Modified-Since`. A 304 gives `outcome = not_modified`, `fetch_log.raw_snapshot_id` = that earlier snapshot, and the collector parses the earlier body again (so observations are refreshed). Hosts without validators (most HTML pages, SOURCES §2) are fetched in full.

### 4.9 Recording

Every attempt and every refused or disallowed URL writes a `fetch_log` row (DATA_MODEL §14.3); every final response with a body is stored as a raw snapshot (§5) before the collector sees it. `mdt fixtures capture` and `mdt sources check` record nothing in the database (§11).

### 4.10 Replay transport (tests and E2E)

`collectors/replay.py` implements an httpx2 transport that answers from fixtures instead of the network:
- **Index:** the fixtures of the given directories (not recursive), keyed by the normalised `meta.url` (§4.1; the query string exact). A fixture whose `meta.redirects` is not empty answers its hop URLs with bodiless redirect responses (`Location` header) and also registers its `final_url`, unless another fixture has that URL. Fixtures named `*_refetch` or `variant_*` are not indexed (the volatility and client tests load them directly); two indexed fixtures with the same key fail when the index is built.
- A URL without a fixture raises a replay error that the client records as `refused` (`error = "no fixture"`); a missing robots.txt fixture counts as 404 (allow all).
- Replayed responses are stored as snapshots with `via = replay` and `fetched_at` = the fixture's `retrieved_at`, so fixture content never claims a live retrieval; the run records `params.replay = true`; throttling waits are 0; the `CONTACT_EMAIL` rule does not apply (§4.4).
- Users: the parser and acceptance tests (which build the transport for the collector's fixture directory) and the E2E server through `COLLECTOR_REPLAY_DIR` (one directory; the E2E server uses `backend/tests/fixtures/ministry_projects`, UI §8.9). There is no CLI option for replay, and compose pins the setting empty (§3). Example: in `fixtures/project_sites/`, the seed URL `https://winwin.gov.ua` (normalised `https://winwin.gov.ua/`) is answered by `winwin_home_csr_shell`, whose `final_url` it is.

## 5. Raw snapshot store

`collectors/store.py`; format and table in DATA_MODEL §14.1.
- `put(body, meta) -> raw_snapshot row`: streams the body to a temporary file in `<DATA_DIR>/raw/<ab>/` while computing SHA-256 and size, gzips it (level 6, mtime 0, no file name) into `<sha256>.gz` unless that file exists, renames atomically, then inserts the row (its own small write unit). `open(raw_id) -> bytes` returns the decompressed body.
- **Every collected value names its snapshot.** Collectors parse only bodies that went through the store. Candidates carry the snapshots per field (`field_snapshots`, §2.1), which the reconciler writes into `field_meta[field].raw_snapshot_ids` (DATA_MODEL §5) and into proposals; a document's `raw_snapshot_id` names the snapshot of its text version, an evidence row's that of its quote. The snapshot row gives URL, final URL and retrieval time.
- **Content type of uploads:** from the file name extension and the first bytes (`%PDF-` → `application/pdf`; a ZIP whose entries contain `word/document.xml` → DOCX, `xl/workbook.xml` → XLSX; `<` after optional BOM and whitespace → `text/html`; valid UTF-8 or UTF-16 with BOM → `text/plain` or `text/csv` by extension); otherwise `application/octet-stream`.
- `DATA_DIR/raw` lives in the `./data` bind mount (CLAUDE.md, Docker), so snapshots survive container restarts; backups follow in Phase 4 (`PLAN.md` §6.8).

## 6. Runs

### 6.1 Lifecycle

```
running ──▶ succeeded | partial | failed | cancelled
```

1. **Start:** `POST /api/runs` (UI) or `mdt collect` (CLI) checks the configuration (collector known and enabled; `CONTACT_EMAIL` valid where §4.4 requires it), recovers stale runs (§6.3) and inserts the run as `running` in one write unit. The partial unique index of DATA_MODEL §14.2 refuses a second running run: API `409 run_in_progress {run_id}`, CLI exit 1 with `error: run <id> (<collector>) is running; try again when it has finished`. `code_version`, `config_hash` and `params` are recorded.
2. **Run:** the collector discovers, fetches, parses and reconciles, in a **deterministic order** (the source's listing order; C3 by slug), so that repeated runs decide alike (DATA_MODEL §15.6). Stats are written every 20 requests and at the end; the cancel flag is checked before every request and between items.
3. **Finish:** if the run set `complete_listing` and was not cancelled, the disappearance step (DATA_MODEL §15.7); then the duplicate detection (§7.8) over the documents and services the run created or whose text changed; finally the end status (§6.5), `finished_at` and the final `stats`.

An interrupted run is simply started again; collectors skip work already done (C4 known articles and files, C4b entries with an observation), so a restart costs little more than the listing pages.

### 6.2 Execution

- **CLI:** `mdt collect <name> [options]` (§11) runs in the foreground, prints one progress line per page or 20 requests and a summary, and exits 0 (`succeeded`), 2 (`partial`) or 1 (`failed`, `cancelled`, refused). Ctrl-C requests cancellation (§6.3).
- **UI:** the server starts the run in a daemon thread of its process and answers `202` at once; with `COLLECTOR_RUN_INLINE=true` (API tests only) it executes the run in the request and answers when it has finished. On shutdown the server requests cancellation of its running run and waits up to 10 s; a run cut off later is recovered as stale.
- Collector writes go through the normal write units (DATA_MODEL §6.1, §15.11), so the web app stays usable during a run (WAL, `busy_timeout`, small transactions).

### 6.3 Heartbeat, stale runs and cancellation

- A running run updates `heartbeat_at` every 30 s from a small heartbeat thread, also while it waits for a host's interval or a `Retry-After`.
- A run in status `running` whose `heartbeat_at` is older than `RUN_STALE_AFTER_S` (default 300 s) is **stale**: it is set to `failed` with `error = "interrupted: no heartbeat since <time> (the process ended or restarted)"`. The server checks at startup, and every start (API or CLI) checks before inserting its run, so a container restart never blocks new runs for more than five minutes.
- **Cancel** (`POST /api/runs/{id}/cancel`, Ctrl-C): the running run gets `cancel_requested_at`, stops before its next request or item (an interval wait is interrupted), skips the disappearance step and ends `cancelled`. Finished runs cannot be cancelled (`409 invalid_state`).

### 6.4 Modes and parameters

| Parameter | Values | Meaning |
|---|---|---|
| `mode` | `incremental` (default) · `full` | per collector (§8); collectors without the distinction treat both alike |
| `limit` | int ≥ 1 | stop after this many items (to try a collector); such a run never sets `complete_listing` |
| `refetch` | bool | `ministry_news`, `kmu_news`: fetch known articles again |
| `recall_sample`, `recall_seed` | int ≥ 0, int | `kmu_news` (§8.4) |
| `document_ids` | list of document IDs | `tagger`: only these documents |

Unknown parameters, or parameters a collector does not support, → `400 validation_error` (API) or a CLI usage error. There are no collector dry runs: `limit` and the replay tests serve to try a collector, and every write is a restorable revision.

### 6.5 End status

- `failed`: a fatal error (an unexpected exception, an invalid codebook mapping, the listing host blocked, throttled or without robots.txt before the listing was complete, §4.7), or a stale run (§6.3).
- `cancelled`: a cancel was requested.
- `partial`: the run finished, but at least one content request ended as `http_error`, `network_error`, `blocked`, `too_large` or `refused` (also when refused because the host was blocked or throttled, its robots.txt was unavailable, or a replay fixture was missing), or an `error`-level message was written. URLs that a robots.txt rule disallows do not make a run partial (they are expected and counted).
- `succeeded`: otherwise.

### 6.6 Run messages

| Level | Codes |
|---|---|
| `error` | `fatal` (the run's fatal error), `parse_error` (expected structure missing, decoder failure), `http_error` (a content request ended as `http_error`, `network_error`, `too_large` or `refused` after the retries; the outcome is in `details`), `blocked` (§4.7), `robots_unavailable` (§4.2), `write_error` (a candidate failed validation at write time) |
| `warning` | `throttled`, `invalid_value`, `unknown_code`, `unmapped_label`, `incomplete_candidate`, `conflicting_candidates`, `soft_404`, `no_server_rendered_content`, `unsupported_content`, `checksum_mismatch`, `ambiguous_time`, `listing_changed` (pagination totals changed during the run) |
| `info` | `subject_deleted`, `discarded` (C4b: not relevant), `listing_complete` (with counts) |

A message names the URL, snapshot and record where they exist; the text is plain, without HTML. Limits: DATA_MODEL §14.4.

## 7. Parsers and shared helpers

### 7.1 Parser contract

- A parser is a **pure function** `parse_<page kind>(snapshot) -> ParseResult`. The input is the body bytes plus `url`, `final_url`, `http_status`, `headers`, `fetched_at` and `raw_snapshot_id`; `ParseResult` holds the candidates (§2.1), the URLs to fetch next (pagination, detail pages, files), a `not_found` flag (404, 410 or a soft 404), the listing facts (`total`, `last_page`) and warnings `(code, message)`. No network, no database, no clock (times come from the snapshot), no randomness.
- A parser raises `ParseError` when the structure it expects is missing (no loader data, no `h1`, an unknown turbo-stream construct), so a site change fails loudly instead of yielding empty data (risk R3). The collector records `parse_error` and continues with the other pages.
- Machine-readable data first (`PLAN.md` §5.5): embedded loader data, JSON, JSON-LD, `<time datetime>`, meta tags, then selectors and visible text. Sitemap `lastmod` is never a publication date.
- Decoding: the charset of `Content-Type`, else `<meta charset>`, else UTF-8 (undecodable bytes → warning `invalid_value`). HTML is parsed with BeautifulSoup and Python's built-in `html.parser` (the fixture excerpts were serialised with it).
- Parsers never emit volatile values (DATA_MODEL §15.6).

### 7.2 Turbo-stream decoder (`parsing/turbostream.py`; C1, C4)

- **Input:** an HTML page, whose `window.__reactRouterContext.streamController.enqueue("…")` calls carry the data as JSON string literals (decoded and concatenated in order), or a `.data` response body (`fixtures/ministry_projects/projects_data_turbostream.txt`).
- **Format** (React Router v7 / Remix v2 single fetch): the first line is a JSON array in which values are referenced by index; an object is `{"_<index of key>": <index of value>}`, an array lists indices; negative numbers are constants. The fixtures use only −5, which decodes to null (e.g. `actionData` and `errors` of the root object) [local probe of all turbo-stream fixtures, 2026-10-30]; the decoder also maps −7 to undefined (the key is omitted), as in turbo-stream v2, and raises `ParseError` on any other constant until a fixture shows it. Typed values (arrays starting with a one-letter type tag) and later promise lines do not occur in the 2026-10-29 captures either; the decoder raises `ParseError` on them.
- **Output:** a mapping of route ID to data. An HTML page holds it under `loaderData`; a `.data` body decodes to `{"<route ID>": {"data": …}}` without `loaderData` (in the fixture: `root` and `projects.list`) [local, 2026-10-30], which the decoder unwraps to the same mapping. Parsers pick the entry by its keys, not by the route ID, so a renamed route does not break them: the first non-`root` entry with the expected keys (listing: `pagination` and `projects` | `articles` | `documents`; detail: `project` | `article` | `document` | `page`). Route IDs seen on 2026-10-29 [local]: `projects.list`, `projects.list.page`, `projects.view`, `news.list`, `news.list.page`, `news.view`, `documents.list`, `documents.list.page`, `documents.view`, `pages.view`.
- The `root` entry (menus, contacts) is never read.

### 7.3 TipTap JSON to text (`parsing/tiptap.py`)

Depth-first over `content` [node types and attributes checked on the C1 and C4 fixtures, local, 2026-10-30]:
- `text` nodes are concatenated; `paragraph`, `heading`, `listItem`, `blockquote`, `codeBlock`, `tableRow` end with a line break; `hardBreak` is a line break.
- **Text held in attributes:** `section` → `attrs.label.text` as a heading line; `tabsItem` → `attrs.label` as a heading line; `linkListItem` and `buttonsItem` → `attrs.text` as a line; `valueCardListItem` → its `value`, `unit` and `text` (those present, space-separated) as a line.
- **Outbound links** `{href, text}` (http and https only; `mailto:` and other schemes are dropped): `link` marks (the marked text) and `linkListItem` / `buttonsItem` (`attrs.href`, `attrs.text`).
- No text from `image`, `gallery`, `video`, `embed`, `teamMembers`, `relatedDocuments` (C4 reads its items as documents, §8.4) or any other attribute.
- The result is normalised as in DATA_MODEL §15.6.
- Parser assertions: `project_brave1_technologies.html` has the line "Платформа Brave1" and the outbound link https://brave1.gov.ua/ (its only one); `project_diiatsyfrova_hromada_additional_rubric.html` has https://hromada.gov.ua/ and the line "1353 лідерів та лідерок територіальних громад …"; `project_virtual_assets_business.html` has the Rada bill link (w1.c1.rada.gov.ua) and four cms.thedigital.gov.ua links, and no mailto link; `ministry_page.html` has the five strategic-goal labels of its tabs.

### 7.4 HTML to text (`parsing/html_text.py`)

- Removed: `script`, `style`, `noscript`, `template`, `svg`, `iframe`, `form` controls, and elements with `hidden` or `aria-hidden="true"`.
- Generic text: the whole `body` (footer statements on operator, owner and licence stay in the text, SOURCES S2), with line breaks after block elements (`p`, `div`, `section`, `article`, `header`, `footer`, `li`, `h1`–`h6`, `tr`, `br`, `table`), whitespace collapsed within lines, then the normalisation of DATA_MODEL §15.6. Collectors with selectors (C3, C4b) extract their own parts.
- Title: the first `h1`, else `<title>`, whitespace collapsed.
- Licence phrases (per page): the CC BY 4.0 sentences quoted in SOURCES S1 and S4b → `cc_by_4_0`; "Всі права захищені", "Усі права захищено", "Усі права захищені", "All rights reserved" → `all_rights_reserved`; otherwise the collector's default from `sources.yaml`.

### 7.5 Dates, numbers and language

- **Month names:** Ukrainian genitive (`жовтня`), nominative (`жовтень`) and abbreviated (`жов.`) forms and English month names; ambiguous or unknown input gives no date (never a guess).
- **Time zones:** ISO 8601 with offset → `published_at_utc` and the Europe/Kyiv calendar date. Kyiv local time without zone (kmu.gov.ua) → UTC via `zoneinfo("Europe/Kyiv")`; a non-existent or ambiguous local time (DST change) gives no UTC value (warning `ambiguous_time`) but keeps the calendar date.
- **No dates from titles:** a "від <date>" in a document title usually dates the act it amends or cites, and no captured title states its own date that way (SOURCES S4), so titles never give `published`.
- **Language** (no LLM): over the first 5 000 letters of title and text, a Cyrillic share ≥ 0.6 gives `uk`, unless the letters ы, э, ъ, ё outnumber і, ї, є, ґ (then `ru`); a Latin share ≥ 0.6 gives `en`; otherwise no value. Used for C2 pages, C4 texts (`translations` says `uk` even for English articles) and as the suggestion for manual documents. www.kmu.gov.ua uses its URL instead: a path starting with `/en/` → `en`, otherwise `uk`.

### 7.6 Tagger: aliases (`tagger.py`)

- **Aliases:** the `aliases` items of live projects and services (all kinds), plus each record's `name_en` and `name_uk` as case-sensitive aliases of kind `name` (so services created by C3, which have names but no aliases, are tagged too).
- **Matching** on the text normalised with `normalize_for_search` (DATA_MODEL §10): an alias with `case_sensitive: true` matches exactly, otherwise case-folded; a match must not be preceded or followed by a letter or digit; overlapping matches are resolved **longest first** (`Дія.Бізнес` wins over `Дія` at the same place); a match covered by an occurrence of one of the alias's `exclude_patterns` (literal phrases, case-folded) is dropped.
- **Output** per subject with at least one match: `matched_aliases` (distinct alias texts, sorted), `match_count`, `snippet` (up to 120 characters before and after the first match, whitespace collapsed). The reconciler adds them as suggested links (DATA_MODEL §15.8).
- Inflected forms are aliases with `kind: inflection` that a person adds; there is no automatic stemming (pymorphy3 suggestions are Phase 3).
- The reconciler runs the tagger for every document candidate whose text is new or changed; the built-in collector `tagger` (§8.6) runs it over stored texts, e.g. after aliases were edited.

### 7.7 Event patterns (`codebook/event_patterns.yaml`)

- A codebook file that is not a vocabulary (no `vocabulary` key, like `parameters.yaml`), versioned in git; its SHA-256 is part of the run's `config_hash`. Initial content: the draft phrase list of CODEBOOK §4, one entry per table cell, nothing added.

```yaml
# Phrase patterns for create_event proposals (docs/CODEBOOK.md §4, docs/COLLECTORS.md §7.7). Not a vocabulary.
version: 1
patterns:
  - {id: launch_uk_zapust, event_type: launch, lang: uk, stems: ["запуст"]}
  - {id: launch_uk_zapratsiu, event_type: launch, lang: uk, stems: ["запрацю"]}
  - {id: beta_uk_test_mode, event_type: beta_launch, lang: uk, all_of: ["тестов", "режим"]}
  - {id: launch_en_launched, event_type: launch, lang: en, phrases: ["launched", "now available", "went live"]}
```

- **Sentences** are split on the stored text (`document_text.text`) at line breaks and after `.`, `!`, `?` or `…` followed by whitespace (dots inside names such as `Дія.City` do not split). Each sentence is normalised with `normalize_for_search` and case-folded for matching, so offsets always refer to the stored text.
- **Semantics:** a stem matches a word that starts with it; a phrase matches the sequence of words; `all_of` requires every part in the same sentence. Patterns apply to documents of their `lang` (documents without a language: all patterns).
- A sentence with at least one alias match (§7.6) and one pattern match yields one `create_event` proposal per (subject, event type), recorded with `collector = tagger` and the run that raised it (also inside C1–C4 runs): event `date` = the document's `published` (canonical string) with `date_basis = inferred` and `date_text` = the document's `published_text`; evidence = the document's current text version (`document_id`, `text_hash`, its `raw_snapshot_id` and `retrieved_at`) with `char_start`/`char_end` of the sentence in the stored text and `quote` = the stored sentence (≤ 1 000 characters); `pattern_id`, `matched_alias` (DATA_MODEL §16.1). Documents without `published` give proposals without a date.
- The share of accepted proposals per `pattern_id` is reported (API `GET /api/proposals/summary`), so the list can be improved on evidence (CODEBOOK §4).

### 7.8 Duplicate detection (`duplicates.py`)

- **Documents:** for each document created or with a changed text in the run, against live documents of **another** `source_id` with the same `language` and a `published` date within ±1 day: a pair is a possible duplicate if the titles are equal after `fold()`, whitespace collapsing and removal of punctuation (`basis = title_date`), or if the containment of their word 3-shingle sets, |A ∩ B| / min(|A|, |B|), over the first 5 000 words of the normalised texts is ≥ 0.8 (`basis = text`, `similarity` recorded). Calibration [local]: the fixture pair `fixtures/kmu_news/news_uk_2019_komanda_duplicate_pair.html` and `fixtures/ministry_news/news_article_2019.html` (the same 2019 item at 17:48 and 13:21 with different slugs, both `uk`) has equal titles and a containment of 0.977, and a test asserts that it yields a `possible_duplicate`.
- **Services** (C3): a new service whose `name_uk` equals, after `fold()`, that of another live service of the same project (`basis = name`), e.g. after the portal renamed a slug.
- Each pair yields one `possible_duplicate` proposal (dedup by pair, DATA_MODEL §16.3; `collector` = the run's collector). Both records stay; the person decides (DATA_MODEL §16.1).

### 7.9 Mapping files (`codebook/collector_mappings.yaml`)

A codebook file that is not a vocabulary, versioned in git and part of `config_hash`. Every target code must be an active term of its vocabulary; otherwise runs of the collectors that use it fail (`fatal`). A source label without a mapping gives the warning `unmapped_label` and the fallback named below. Initial content (draft coding rules, open to the team like the codebook):

- `ministry_document_kinds` (C4; the `kind.slug` of thedigital.gov.ua documents, 36 values on 2026-10-29 [local, documents listing filters]) → `doc_type`; fallback `other`:
  - `legal_act`: `decision`, `order`, `nakaz`, `legislative-act`, `zakon`, `decree`, `proekt-ukazu`, `resolution`, `directive`, `draft-regulatory-act`, `license-conditions`, `convention`, `agreement`;
  - `report`: `report`, `audit-report`, `vnutrishniy-audyt`, `richna-finansova-zvitnist`, `richna-konsolidovana-finansova-zvitnist`;
  - `strategy_policy`: `plan`;
  - `statistics`: `dashbord`;
  - `other`: `regulation` (the site applies it to the ministry's annual work plans, SOURCES S4), `protocol`, `proposal`, `recommendation`, `appeal-statement`, `contract`, `declaration`, `methodological-document`, `instruction`, `budget-request`, `project`, `application-form`, `other`, `pasport-biudzetnykh-prohram`, `upravlinnia-aktyvamy`, `koshtorys`.
- `diia_portal_channels` (C3; the leads under "Як отримати послугу", SOURCES S3) → `channel`: `Онлайн` → `portal`, `Офлайн` → `physical`; `ignore: ["Результат"]` (the result lead on every captured service page, no warning); other labels are skipped with `unmapped_label`.
- **C1 rubric codes** are a fixed rule in code, not a table: a rubric slug maps to the `ministry_category` code obtained by replacing `-` with `_` (codes allow only `[a-z0-9_]`, DATA_MODEL §3.5), e.g. `how-tos` → `how_tos`. Terms are added by a person (DATA_MODEL §15.10).

## 8. Collectors

Each collector below follows DATA_MODEL §15 and lists: access, requests, modes, candidates and keys, matching, the fields it writes or proposes, what it creates, the complete listing, dates, change detection, the fixtures its parser tests use (all under `backend/tests/fixtures/`), and what needs the target server. Fields not listed are never written. "Document fields" means: `title`, `url`, `publisher`, `publisher_org_id`, `doc_type`, `language`, `published`, `published_basis`, `published_text`, `published_at_utc`, `source_record_at`, `license`, the text version (`text_hash`, `raw_snapshot_id`, `retrieved_at`, `extraction_method`, DATA_MODEL §15.6), `source_id` (= the collector key) and `external_id` (both on create only), and suggested `links` (add-only, DATA_MODEL §15.8). `publisher_org_id` is set only to the focal organisation (DATA_MODEL §3.5), only where stated. Unless stated otherwise, the listing host of a collector is the host of its first request.

### 8.1 C1 `ministry_projects` (SOURCES S1)

- **Access:** thedigital.gov.ua, embedded turbo-stream (§7.2); robots.txt allows all (SOURCES S1). Licence default `cc_by_4_0`, confirmed per page by the footer sentence (§7.4).
- **Requests per run** (about 16): `/projects`, then `/projects/page/<n>` up to `pagination.lastPage` (loader entry with `projects` and `pagination`); then one detail page `/projects/<rubric>/<slug>` per entry with `type = content` (14 on 2026-10-29). Entries with `type = link` get no request (their ministry URL redirects to `externalUrl`, which the listing already carries). The 12 rubric listings are not fetched: the primary rubric comes from the listing, the additional rubrics from the detail page (`additionalRubrics`). Modes: no distinction.
- **Candidates and keys:**
  - project per entry: key `entry:<slug>` (the entry's `slug` without the rubric segment, e.g. `entry:brave1`), `external_id` = `project.id` (detail page; none for link entries), `label` = `title`, `url` = `https://thedigital.gov.ua/projects/<rubric>/<slug>` (content) or `externalUrl` (link);
  - document per detail page: key `page:<project.id>`.
- **Matching:** projects by `external_id` (DATA_MODEL §15.3 rule `external_id`), then by URL (rule `url_fields`: the entry URL in `ministry_urls` for content entries, `externalUrl` in `official_urls` for link entries; all 20 seed projects carry such a URL); no name matching. Documents by rule `document`.
- **Writes:**

  | Type | Field | Value |
  |---|---|---|
  | project | `description_uk` | the listing's `caption` (always available with the listing, so a failed detail page cannot change it) |
  | project | `ministry_categories` | codes of the primary rubric, then the additional rubrics sorted by code (§7.9); unknown codes dropped with the warning `unknown_code`, which names the rubric slug, its site label and the code a person would add (DATA_MODEL §15.10). For content entries only when the detail page was read in this run (otherwise the field is left out of the candidate); link entries: the primary rubric |
  | project | `ministry_urls` | content entries: the entry URL (add-only) |
  | project | `official_urls` | link entries: `externalUrl` (add-only) |
  | document | document fields | `doc_type = project_page`, `title` = project title, `url` = entry URL, `publisher = thedigital.gov.ua`, `publisher_org_id` = focal organisation, `language = uk`, text = caption and `blocks` (§7.3), `external_id` = `project.id`, `extraction_method = turbo-stream`; no `published` |

  Names (`name_en`, `name_uk`) of existing projects are never written: the site title is kept in the observation's `label` and in the project-page document. Snapshots per field: the listing page for `description_uk`, `ministry_urls` and `official_urls`, the detail page for `ministry_categories` of content entries.
- **Propose-only:** `official_urls` from the project page: every outbound `linkListItem` link (§7.3) whose host is neither thedigital.gov.ua nor one of its subdomains, nor `*.rada.gov.ua` or `www.kmu.gov.ua` (legal acts stay references, SOURCES S6), and whose path does not end in a file extension (`.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.zip`), becomes an add-only `update_field` proposal even when the field is unlocked, so the domain-verification judgement (`PLAN.md` §5.2 C2) stays with the person: evidence = the page snapshot, `quote` = the link text, `locator` = the URL. On the fixtures: https://brave1.gov.ua/ (Brave1) and https://hromada.gov.ua/ (Дія.Цифрова громада); none for Віртуальні активи (Rada bill and cms.thedigital.gov.ua files) or Євроінтеграція (storage files). An accepted URL is fetched by C2 from its next run.
- **Creates:** documents (project pages), each with a suggested link to its project (`LinkHint` with the entry's key, `snippet` = "Project page on thedigital.gov.ua").
- **Proposes:** `create_entity` for an unmatched entry (observed `fields`: `name_uk` = title, `description_uk`, `ministry_categories`, `ministry_urls` or `official_urls`; `payload.site_slug` for the slug generated at accept time; scope comes from the person, DATA_MODEL §16.4); `update_field` for locked fields and the propose-only official URLs; `possibly_discontinued` for projects (`discontinued: true`; documents: false).
- **Complete listing:** every listing page 1 … `lastPage` parsed (detail-page failures do not affect it).
- **Dates:** projects carry none (SOURCES S1); launch dates come from documents (C4, C4b) and archive bounds from C5.
- **Change detection:** decoded data only; nonces and image `?v=` parameters never reach candidates. The entry URL is built from the data's slug, never from the request URL or `<link rel=canonical>` (which echoes any accepted path).
- **Fixtures and parser tests** (`fixtures/ministry_projects/`): `projects_page1.html` and `projects_page2.html` (20 entries, 6 link entries, pagination); `project_brave1_technologies.html` (detail: `project.id`, blocks, the official-URL proposal); `project_diiatsyfrova_hromada_additional_rubric.html` (`additionalRubrics` → `how_tos`, an unknown code until a person adds the term; value cards; the official-URL proposal); `project_virtual_assets_business.html` (no proposal; the Rada bill and cms links stay in the text and in the outbound links); `project_yevrointegraciya_progress.html` with `variant_yevrointegraciya_302.html` (**volatility pair**: they differ only in nonces and give identical candidates); `variant_regions_city_same_record.html` (requested as `/projects/regions/city`, the candidate URL is `/projects/business/city`); `legacy_e_residency_404.html` (`not_found`, no candidate); `projects_data_turbostream.txt` (decoder on a `.data` body); `category_*.html` (decoder route selection by keys; C1 fetches no rubric listing); `link_entry_winwin_redirect.html` (C1 requests no link-entry page).
- **Target server:** nothing beyond the general host re-check (SOURCES §5 item 1).

### 8.2 C2 `project_sites` (SOURCES S2)

- **Input:** the `official_urls` of all live projects at run start, minus the excluded hosts (`codeua.com`, out of scope since 2026-10-30, SOURCES S2). One GET per URL (home pages; no link following, no sitemap inventory in Phase 2); redirects to other hosts are followed (§4.5). The listing host is none: every URL is its own unit.
- **Candidates:** one document per URL, key `url:<canonical url>`; text by §7.4; licence per page (§7.4; default `unknown`).
- **Observe only** (no document, a warning): a **client-rendered shell**, i.e. a page with a client-side application root (an `<app-root>` element or an `ng-version` attribute) whose visible body text without `<title>` is shorter than 200 characters (`no_server_rendered_content`; winwin.gov.ua: 18 characters in `winwin_home_csr_shell.html`, while the server-rendered Angular excerpts of u24.gov.ua have 216–294) [local, 2026-10-30]; a title or `h1` that matches a `soft_404_patterns` entry for the host (`soft_404`); a non-HTML response (`unsupported_content`).
- **Writes (documents):** document fields with `doc_type = project_page`, `publisher` = the host of the final URL, `language` by §7.5, `extraction_method = html`; no `published` (pages carry no reliable date; JSON-LD such as UNITED24 Media's `foundingDate` stays in the snapshot, where evidence can cite it).
- **Creates:** documents, each with a suggested link to the project whose `official_urls` contain the URL (`snippet` = "Official URL of the project"). Proposes `update_field` for locked document fields only.
- **Complete listing:** every input URL got a final response (any status). Documents get no `possibly_discontinued`.
- **Fixtures** (`fixtures/project_sites/`): `usf_home.html`, `u24_home.html`, `united24media_home.html`, `playcity_home.html`, `center_home.html`, `osvita_home.html`, `e_pidpryemets_home.html`, `se_portal_page.html` (generic text, footer statements kept, licence phrases; the short excerpts `playcity_home.html` with 82 characters and `united24media_about.html` with 46 have no application root and are not shells); `winwin_home_csr_shell.html` (`no_server_rendered_content`); `usf_sitemap_soft404.html` (`soft_404`); `usf_about.html`, `u24_about.html`, `united24media_about.html` (extractor tests). The sitemaps (`center_sitemap.xml`, `osvita_sitemap.xml`, `playcity_sitemap.xml`) are unused until the Phase 3 inventory.
- **Target server:** the domains that C1 proposes and a person accepts (brave1.gov.ua, hromada.gov.ua, …; "not contacted" in SOURCES §4) are first contacted by C2; the host re-check covers them.

### 8.3 C3 `diia_catalog` (SOURCES S3)

- **Access:** diia.gov.ua, server-rendered HTML (no embedded data, no API); robots.txt disallows `/backend/` only. Licence `all_rights_reserved` ("Всі права захищені"). Cloudflare in front: any challenge page blocks the host (§4.7).
- **Requests per run** (about 205, 3.5 minutes at 1 request/s): first `/services` (alphabetical list `div.services-byletter_item a`), `/sitemap.xml` and the services sitemap `sitemap-kitsoftservicesmodelsservice-1.xml` (slugs and `lastmod`), the audience pages `/services/categories/gromadyanam` and `/services/categories/biznesu` (subcategory tiles) and the subcategory pages `/services/categories/<audience>/<subcategory>` (service links `a.service-acc_item-service`, deduplicated by `href`); then one page per service `/services/<slug>`, sorted by slug. Discovery = the catalogue list ∪ the sitemap (`/services/RD4U` appears only in the list). Slugs keep their case; the trailing-dot host variant is never requested (§4.1). Modes: no distinction.
- **Candidates:** a service per slug (key `service:<slug>`, `external_id` = slug, `label` = `h1`, `details.lastmod` from the sitemap); a document per service page (key `page:<slug>`).
- **Matching:** services by `external_id`, then by URL (`urls`); documents by rule `document`.
- **Writes:**

  | Type | Field | Value |
  |---|---|---|
  | service | `project_id` | on create only: the project with `seed_key` = option `project_seed_key` (`diia`); missing or deleted → the run fails (`fatal`) |
  | service | `name_uk` | `h1.service-type_title` (the meta title can differ, SOURCES S3) |
  | service | `description_uk` | the value of the label/value pair "Опис послуги", if present |
  | service | `urls` | `https://diia.gov.ua/services/<slug>` (add-only) |
  | service | `channels` | channel leads under "Як отримати послугу" mapped by `diia_portal_channels` (§7.9), in vocabulary order |
  | service | `source_categories` | `{source: "diia_catalog", label: "<audience label> / <subcategory label>", url: <subcategory page URL>}` for every subcategory page listing the service, sorted by `url` (system field) |
  | service | `source_audiences` | the distinct audience labels of those pages, sorted |
  | document | document fields | `doc_type = project_page`, `title` = `h1`, `publisher = diia.gov.ua`, `language = uk`, text = the service page's main content (`h1`, label/value pairs, the `section.service-acc_section` blocks; headings matched after `fold()` so "та"/"й" and apostrophe variants agree), `extraction_method = selector`; suggested link to the service; legal-act links (zakon.rada.gov.ua) stay references in the text |

  `source_categories` and `source_audiences` are aggregated over pages, so they are part of the candidates **only when both audience pages and every subcategory page linked from them were parsed in this run**; otherwise both fields are left out of every service candidate and the warning `incomplete_candidate` names the missing pages. Their `field_snapshots` list the subcategory pages. `kind`, `status` and the classification fields are never written.
- **Creates:** services (`verification_status = unverified`, D-8) and documents. **Proposes:** `update_field` for locked fields; `possible_duplicate` for a new service whose name equals another service's (§7.8); `possibly_discontinued` for services missing from two complete runs (`discontinued: true`).
- **Complete listing:** the catalogue list and the services sitemap both parsed. The 43 Register-of-Damage claim categories in the list are created like any service (proposed default while decision D-6 is open; they can be regrouped with `parent_service_id`, merged or deleted, and a deletion is respected, DATA_MODEL §15.3).
- **Dates:** service pages carry none; the sitemap `lastmod` stays in the observation's `details`, never a launch date (SOURCES §5 item 4).
- **Fixtures** (`fixtures/diia_catalog/`): `catalog_root.html` (list and footer grid), `category_gromadyanam.html` (audience page, tiles only), `subcategory_biznesu_pidpriyemnictvo.html` (memberships, duplicated accordion), `service_reyestraciya_fop.html`, `service_vityag_pro_nesudimist.html`, `service_poshkodzhene_majno.html` (fields, channel leads incl. the ignored "Результат", legal-act links, h1 vs meta title), `sitemap_index.xml`, `sitemap_services.xml`, `sitemap_categories.xml`. The fixture set lacks the `biznesu` audience page and most subcategory pages, so the acceptance run leaves the category fields out with `incomplete_candidate`; the parser test reads the memberships from the subcategory fixture directly. Volatility: no real pair exists; the test derives one by changing the csrf token and inline scripts.
- **Target server:** the trailing-dot host check (SOURCES §5 item 1) only.

### 8.4 C4 `ministry_news` and C4b `kmu_news` (SOURCES S4, S4b)

**C4 `ministry_news`** (thedigital.gov.ua, storage.thedigital.gov.ua, the microsites `2years.`, `5years.`, `2025.thedigital.gov.ua`):
- **Parts** (option `parts`, default all): `news`, `documents`, `ministry`, `microsites`. Each listing page is processed completely (its new or changed items fetched and reconciled) before the next page.
- **News:**
  - `incremental`: `/news`, `/news/page/<n>` … until a page whose items are all known (an observation `news:<slug>` exists), at least 2 pages; `full`: every page up to `pagination.lastPage` (366 on 2026-10-29), fetching articles that are new or whose listing title or `publishedAt.iso8601` differs from the observation's details; `refetch` fetches all articles. Every listed article that is not fetched is **sighted** (`ctx.observe`, DATA_MODEL §15.7). A full backfill is about 4 750 requests (3–5 hours).
  - Article page `/news/<rubric>/<slug>` (loader entry with `article`); old `/news/<slug>` URLs redirect there (SOURCES S4) and the candidate URL comes from the data.
  - Candidate: document, key `news:<slug>` (the slug without the rubric segment), `external_id` = `article.id`; `doc_type = news`, `title`, `url = https://thedigital.gov.ua/news/<rubric>/<slug>`, `publisher = thedigital.gov.ua`, `publisher_org_id` = focal organisation, `language` by §7.5, `published` = the Kyiv date of `publishedAt.iso8601` (precision `day`, basis `stated_in_source`), `published_text` = `publishedAt.iso8601` as given, `published_at_utc` from it, text = `lead` and `blocks` (§7.3), `extraction_method = turbo-stream`, licence by footer. `publishedAt.text` (year-less for the current year) and `publishedAt.related` are never used.
- **Documents:** **every run** traverses all `/documents` listing pages (106 pages, 1 267 items on 2026-10-29; about 2 minutes), in both modes: the listing is sorted by the site's `publishedAt`, which for `link` items is the act's own date, so a new item can appear on any page (SOURCES S4). Only new or changed items cause further requests; the others are sighted. Per item type:
  - `file`: a document with key `file:<md5>` (the 32-hex storage file name, so the same file listed again, e.g. as an attachment or on `/ministry`, is the same key), `url` = `externalUrl`, `title` from the listing, `doc_type` by `ministry_document_kinds` (§7.9), `source_record_at` = `publishedAt.iso8601` in UTC (never `published`: bulk timestamps and upload times, SOURCES S4 and §5 item 4), no `published`, `license = unknown` (SOURCES §5 item 6 default), text from the file (§10.2: PDF, DOCX; other formats `extraction_method = none`). A known file key is never fetched again; the MD5 of a new body must equal the file name (else warning `checksum_mismatch`, the body is kept);
  - `content`: key `doc:<group/slug>`; the detail page `/documents/<slug>` (loader entry with `document`) gives a document (text from `blocks`, licence by footer); each attachment (an outbound link to a storage file) becomes a `file:<md5>` document (`title` = link text, `doc_type` of the parent) unless that key was already reconciled in the run (DATA_MODEL §15.6: the first candidate wins);
  - `link`: key `doc:<group/slug>`; no request (legal acts on zakon*.rada.gov.ua or kmu.gov.ua `/npas/` are references, SOURCES S6); a document with `url` = `externalUrl`, `title`, `doc_type` by kind, `source_record_at`, no `published`, no text (`extraction_method = listing_only`; text version = the listing page's `raw_snapshot_id` and `retrieved_at`).
- **`/ministry`** every run: a document (`doc_type = other`, title and text of the page by §7.3, team members excluded), and its embedded document items (`relatedDocuments`, the same shape as listing items) handled like listing items (same keys, so no duplicates).
- **Microsites** every run, conditional GET (they send ETag and Last-Modified, a file time, not a date): one document each, key `microsite:<host>`, `doc_type = report`, text by §7.4, licence by footer (only `2years.` carries the CC BY sentence, SOURCES C-4), no `published`.
- **Proposes:** `update_field` for locked fields; `possible_duplicate` against C4b documents (§7.8); the tagger adds `create_event` proposals. Documents get no `possibly_discontinued`.
- **Complete listing:** `full` mode with every news and every documents listing page parsed; `incremental` never sets it.
- **Fixtures** (`fixtures/ministry_news/`): `news_list_page1.html`, `news_list_page366.html` (first and last page, `publishedAt` with and without `related`), `news_article_2019.html`, `news_article_2022.html`, `news_article_2026.html` (articles; dates; `lead` and `blocks`), `news_article_en_2024.html` (language `en` despite `translations: uk`), `news_article_redirect_2021.html` (redirect recorded, URL from the data), `documents_list_page1.html` (`file` items, kinds), `documents_list_page106.html` (`link` items with act dates 1996–2001 → `source_record_at`, never `published`), `document_page_content.html` (`content` item, attachments), `ministry_page.html` (embedded document items; the work plans with kind `regulation`; tabs and section labels, §7.3), `storage_pdf_draft_resolution.pdf` (PDF text; MD5 = file name), `microsite_2years_report.html` (CC BY sentence), `microsite_2025_report.html` (no licence → `unknown`), `not_found_en.html` (404 → `not_found`). `sitemap_latest100.xml` is unused (SOURCES S1). Volatility: the C1 pair (same site and decoder) plus derived variants of the news fixtures with changed nonces, `related` texts and image `?v=` values.
- **Target server:** nothing beyond the host re-check.

**C4b `kmu_news`** (www.kmu.gov.ua):
- **Access:** sitemaps plus article pages; robots.txt disallows `/npas/`, `/storage/`, `/timeline`, `/api/` (never requested, also not as redirect targets); `Crawl-delay` applies to another group (SOURCES S4b), so the 1 s default holds. Licence `cc_by_4_0` by footer. A bot manager is present: any challenge page blocks the host (§4.7).
- **Discovery per run:** `https://www.kmu.gov.ua/sitemap.xml` (a `urlset` listing the child sitemaps), the Ukrainian post sitemaps `sitemap-rainlab-blog-models-post-<n>.xml` (all `n` listed) and the English one under `/en/`; one GET each (no validators, so no conditional GET). **Candidates:** entries whose `lastmod` falls into the window (`window_from`, default `2019-08-29`; `window_to`, default none), whose slug matches one of the keyword patterns (option `keywords`, regular expressions over the slug; initial list from SOURCES S4b in both transliteration styles: `mincifr`, `cifrovoyi-transformaciyi`, `ministerstv[a-z]*-cifrov`, `mintsyfr`, `tsyfrovoi-transformatsii`, `ministerstv[a-z]*-tsyfrov`, `fedorov`, `\bdiia\b`, `\bdiya\b`) and that have no observation yet (unless `refetch`). Entries that have an observation are sighted (`ctx.observe`), so a document that leaves the sitemaps becomes missing after complete runs. `lastmod` only selects the window; it is never a date of the document.
- **Recall sample** (SOURCES §5 item 3; parameters `recall_sample`, default 0, and `recall_seed`, default 1; options `recall_from` `2019-09-01` and `recall_to` `2022-02-23`): the Ukrainian sitemap entries with `lastmod` in the recall window that match no keyword are sorted by URL and shuffled with a pseudo-random generator seeded with `recall_seed`; the first `recall_sample` of them are the sample, and those without an observation are fetched and judged like candidates. Their observations get `details.recall_sample = <seed>`, so a repeated run with the same seed draws the same sample and fetches nothing again. `stats.extra` records `recall_seed`, the window, `window_entries` (Ukrainian entries in the window), `keyword_entries`, `nonkeyword_entries`, `keyword_relevant` and `keyword_discarded` (from the observations of the window's keyword entries), `sample_size` and `sample_relevant`, which the methods section needs for the recall estimate.
- **English versions:** for a relevant Ukrainian article whose slug is in the English sitemap, the page `/en/news/<slug>` is fetched as a separate document.
- **Parsing** (`news_page`): `h1` → title; `div.page_title-desc` → publishing body (Ukrainian pages: the link and its host; English: plain text) and the date, matched after collapsing whitespace: `опубліковано DD <month genitive> YYYY року о HH:MM` / `posted D Month YYYY HH:MM` (Kyiv local time, §7.5); `ul.wcag-tags` → topics (observation `details`); `div.editor-content` → text; footer → licence.
- **Relevance:** a page is kept if its publishing body is the ministry (Ukrainian: the link points to thedigital.gov.ua; English: "Ministry of Digital Transformation") or the tagger finds an alias match in its title or text; otherwise no document is created (`discarded`), and its observation (subject null, `details.discarded = "not_relevant"`) prevents fetching it again (unless `refetch`).
- **Writes (documents):** key `uk:<slug>` or `en:<slug>`, `external_id` the same; `doc_type = news`, `publisher = www.kmu.gov.ua`, `publisher_org_id` = focal organisation when the body is the ministry, `language` from the URL (§7.5), `published` (precision `day`, basis `stated_in_source`), `published_text` = the date words as on the page, `published_at_utc` (§7.5), `extraction_method = selector`.
- **Proposes:** `update_field`, `possible_duplicate` against C4 (§7.8); the tagger adds `create_event` proposals.
- **Complete listing:** every post sitemap parsed.
- **Snapshots:** the raw pages contain the bot-manager token with the client's IP address (SOURCES §2); raw snapshots never leave the server (DATA_MODEL §14.1), and no kmu.gov.ua page is on a fixture capture list.
- **Fixtures** (`fixtures/kmu_news/`): `sitemap_index.xml`, `sitemap_posts_uk_2021_2026_excerpt.xml`, `sitemap_posts_uk_2016_2021_excerpt.xml`, `sitemap_posts_en_excerpt.xml` (discovery, window, keywords in both styles); `news_uk_2019_regulation.html` and `news_en_2019_regulation.html` (UA/EN pair by slug, dates); `news_en_2019_regulation.html` with `news_en_2019_regulation_refetch.html` (**volatility pair**: they differ in the CSP nonce and the csrf token; the bot-manager script was removed from both excerpts, so the test adds a synthetic one with different tokens to one of them in memory); `news_uk_2019_komanda_duplicate_pair.html` (duplicate of `ministry_news/news_article_2019.html`, §7.8); `news_uk_2020_other_body.html` (another body, kept by alias match); `news_uk_2025_playcity.html`, `news_uk_2025_year_review.html`, `news_en_2025_plans.html` (recent pages). `npa_sitemap_excerpt.xml` serves a test that no `/npas/` URL is ever requested.
- **Target server:** nothing beyond the host re-check.

### 8.5 C5 `wayback` (SOURCES S5)

The Wayback Machine works from the data lead's machine but not from the development environment [user, 2026-10-30]. C5 is therefore specified against the official CDX documentation (SOURCES S5, README re-read on 2026-10-30) and tested with **synthetic fixtures**; real fixtures come from `mdt fixtures capture wayback` on the target server, before C5 runs there (`needs_server_check: true`).

- **Purpose in Phase 2:** archive upper bounds for projects and services (`first_archived` events, DATA_MODEL §15.12). The reconstruction of the catalogues at the cut-off dates (31 December 2019–2025 and 2022-02-23) with era-specific parsers is Phase 3 (§14); archived copies of single pages can be added by hand (§10.3).
- **Host:** `web.archive.org`, 5 s interval, long backoff (§4.6); it is C5's listing host (§4.7). If its robots.txt is unavailable or blocked, or the first CDX request fails after the retries (429, 503, network failure), the run fails with `error = "Wayback Machine unavailable"`; a later failure ends it `partial`. Unavailable is never read as "no captures" (risk R5).
- **URL set:** (a) the `prefixes` of `sources.yaml` (default `thedigital.gov.ua/projects/`, `diia.gov.ua/services/` and the trailing-dot form `diia.gov.ua./services/`, SOURCES S5); (b) every URL in the `ministry_urls` and `official_urls` of live projects and the `urls` of live services that no prefix covers, minus the excluded hosts (`codeua.com`). Paths that the live site's robots.txt disallows are never queried (SOURCES §5 item 2): C5 requests no live host itself and checks against the newest stored robots.txt snapshot of the host (other runs store it, §4.2); without one the URL is queried, since the URL set holds only the listing prefixes and the subjects' own URLs.
- **Queries** (`output=json`, documented parameters only, in this parameter order, so a capture fixture's URL equals the request):
  - prefix: `url=<prefix>&matchType=prefix&collapse=urlkey&output=json&fl=urlkey,timestamp,original,statuscode,mimetype&filter=statuscode:200&limit=<page_limit>&showResumeKey=true`, repeated with `&resumeKey=<key>` appended while the response ends with a resume key;
  - single URL: `url=<url>&output=json&fl=urlkey,timestamp,original,statuscode,mimetype&filter=statuscode:200&limit=1`.
  Only the earliest capture is needed in Phase 2; the experimental skip counters (`showSkipCount`, `lastSkipTimestamp`) and latest-capture queries are not used.
- **Parser** (`cdx_json`): the body may be gzip-compressed without a `Content-Encoding` header (README: gzip by default), so a body starting with the gzip magic bytes is decompressed first; the first row is the header and columns are located **by name**, further named columns are ignored; an empty array `[]` or a header-only array means no captures (the documented format does not say which occurs); a final `[]` followed by a one-element row is the resume key; a row whose length differs from the header, or a timestamp that is not 14 digits, raises `ParseError`. Per `urlkey` the smallest timestamp over all rows and pages counts (the README's "usually sorted by url and date" is not relied on).
- **Mapping to subjects:** URLs are compared by an archive key (lower-cased host without `www.` and trailing dot, default port, query and fragment removed, trailing slash removed, path lower-cased: the CDX `urlkey` is lower-case). A row maps
  - **exactly** to every subject that has a URL with the row's archive key;
  - **by slug** to the project whose ministry URL ends in `/<slug>`, when the row lies under `thedigital.gov.ua/projects/` and its path is the pre-relaunch form `/projects/<slug>` (where `<slug>` is not one of the 12 rubric slugs or `page`) or `/projects/<rubric>/<slug>` with another rubric (the site ignores the rubric segment and redirects legacy slugs that still exist, SOURCES S1).
  Per subject and URL the earliest capture counts.
- **Writes** (DATA_MODEL §15.12): for an exact match of a subject's own ministry or service URL, a `first_archived` event with its evidence row, created directly; for every other mapping (official URLs such as domain roots, slug matches), a `create_event` proposal with the same values, so a person checks in the archive that the capture shows the project (a domain can predate its project or have served something else). Event: `date` = the Europe/Kyiv calendar date of the 14-digit UTC timestamp, precision `day`, `date_basis = archive_upper_bound`, `date_text` = `<timestamp> <original URL>`, `description_en` = "Earliest capture in the Wayback Machine (CDX, status 200) of <original URL>"; evidence: `url` = the CDX request URL (what C5 retrieved), `archive_url` = `https://web.archive.org/web/<timestamp>/<original URL>`, `raw_snapshot_id` = the CDX response, `retrieved_at` = its `fetched_at`, `quote` = the CDX row as JSON. Observations: one unbound sighting per queried URL and CDX `urlkey`, key `url:<archive key>`, with `details.earliest` and `details.subject_ids` (a URL can belong to several subjects). No `possibly_discontinued`.
- **Complete listing:** every CDX page of every prefix and every single-URL query answered (not refused, not failed).
- **Synthetic fixtures** (Phase 2, `fixtures/wayback/`): `synthetic_cdx_prefix_collapse.json` (header plus rows for several URLs under `example.org/projects/`, among them a pre-relaunch `/projects/<slug>` row and two rows of one URL in reverse order), `synthetic_cdx_exact_limit1.json`, `synthetic_cdx_resume_key.json` (rows, `[]`, `["<key>"]`, exactly the README's JSON example shape), `synthetic_cdx_empty.json` (`[]`), `synthetic_cdx_header_only.json`, `synthetic_cdx_extra_columns.json` (a header with further named columns), `synthetic_cdx_gzipped.json.gz` (a gzip body without `Content-Encoding`), `synthetic_capture_redirected.html` (an `id_` capture whose meta records a redirect to another timestamp, for §10.3). Rules: file names start with `synthetic_`; the meta file has all keys of `fixtures/README.md` plus `"synthetic": true`, `capture` starts with "synthetic:" and cites the README (SOURCES S5), `licence` says "synthetic test data written for this repository", `retrieved_at` is the time of writing, `trimmed: false`; every URL inside the body uses a reserved example host (`example.org`, `www.example.org`, `example.com`) and every digest and length is obviously made up, so no synthetic row can be mistaken for an archive fact about a real site; each meta `url` is exactly the query C5 builds for the test sources file of §12.1. `backend/tests/test_fixtures.py` enforces these rules. The real 429 body `availability_429.html` serves the client test for "Wayback unavailable".
- **Capture list** for `mdt fixtures capture wayback` (§11; run on the target server, then commit): `robots_web_archive` (`https://web.archive.org/robots.txt`), `cdx_prefix_projects_collapse` (the prefix query above for `thedigital.gov.ua/projects/` with `limit=50`, which also shows a resume key), `cdx_exact_diia_services_earliest` (the single-URL query for `diia.gov.ua/services`), `cdx_resume_key_news` (`url=thedigital.gov.ua/news/&matchType=prefix&collapse=urlkey&output=json&fl=urlkey,timestamp,original,statuscode,mimetype&filter=statuscode:200&limit=5&showResumeKey=true`), `cdx_no_captures` (a single-URL query for a path that does not exist, to record the answer without captures). All are technical responses without creative content and are kept whole, like the robots.txt fixtures. After the capture, the parser tests also run against the real fixtures, and every difference from the documented format is recorded in SOURCES S5 (and the synthetic fixtures corrected).

### 8.6 `tagger` (built-in)

No network and no hosts. Runs the tagger (§7.6) and the event patterns (§7.7) over the current text of every live document (or the documents in `document_ids`), adding suggested links (DATA_MODEL §15.8) and `create_event` proposals (collector `tagger`). Use it after aliases or `event_patterns.yaml` changed, and after adding a manual document ("Tag now", UI §8.6). It creates no records and no observations; `complete_listing` stays 0. Each run writes revisions only for documents that gain links, so a second run writes none.

## 9. Importer (CSV and XLSX)

The data rules (channel `import`, provenance `import:<file_label>`, which fields may be written, conflicts instead of overwrites) are DATA_MODEL §17.1; this section is the workflow. Typical use: the dataset mentioned in the paper, if it exists (`PLAN.md` §14 question 3). Mapping and plan are not stored; only an import that was run is (`import_run`).

### 9.1 Workflow

1. **Upload** the file: `POST /api/uploads?filename=<name>` with the raw bytes (API §7.7) → an upload snapshot (`via = upload`, `source_id = manual`).
2. **Preview:** `POST /api/imports/preview {upload_id, entity_type, sheet}` → the sheet names (XLSX), the column headers, the first 20 rows, a suggested mapping, the importable fields and the key fields of the type. Writes nothing.
3. **Dry run:** `POST /api/imports/dry-run {upload_id, entity_type, sheet, mapping, key_field}` → the plan (§9.4). Writes nothing; repeat it after changing the mapping.
4. **Run:** `POST /api/imports {upload_id, entity_type, sheet, mapping, key_field, note}` re-plans and writes row by row (each row one write unit, all revisions with `batch_id` = the import's ID), stores the `import_run` (`done`, or `failed` on a fatal error such as an unreadable file) and returns the result in the plan's format with the written IDs. The UI links the result to Recent changes filtered by that `batch_id`. Running again means a new import.

The CLI does the same in one command: `mdt import <file> --type <type> [--sheet NAME] [--map COLUMN=FIELD …] [--key id|slug|url] [--note TEXT] [--dry-run]` (§11); it first stores the file as an upload snapshot.

### 9.2 Files

- **CSV:** UTF-8 with or without BOM (anything else → `400 validation_error` "save the file as UTF-8"); the delimiter is the one of `,`, `;` and tab that occurs most often in the header line; quoting per RFC 4180.
- **XLSX:** read with openpyxl in read-only mode with cached formula values; the chosen sheet (default the first). Numbers become their decimal text (integral values without `.0`), date cells `YYYY-MM-DD`.
- **Header:** the first row; an empty header cell is named `column_<n>`; duplicate headers → `400`. Empty rows are skipped. Rows are numbered as in the sheet (header = row 1).

### 9.3 Mapping and values

- `mapping` = `{column: field}` over the importable fields of the type (DATA_MODEL §17.1) plus `id` (key only); unmapped columns are ignored; a field mapped twice → `400`.
- **Suggested mapping:** a header that equals a field's name or label (case-insensitive, trimmed) maps to that field.
- **`key_field`:** `id` (the record's prefixed ID), `slug` (project, organization), `url` (document: matched by canonical URL), or null (every row creates a record).
- **Cell values** (an empty cell means "not provided" and never clears a field):

  | Field type | Accepted cell text |
  |---|---|
  | `string`, `text`, `slug`, `url` | as given (normalised, DATA_MODEL §1.2) |
  | `vocab` | the code, or a term's `label_en` (case-insensitive) |
  | `vocab_list`, `string_list`, `url_list` | items separated by `;` (the export joins with `"; "`), each as above |
  | `alias_list` | alias texts separated by `;` (defaults of DATA_MODEL §1.2) |
  | `bool` | `true`/`false`, `yes`/`no`, `1`/`0` (case-insensitive) |
  | `int`, `number` | decimal number with `.` |
  | `partial_date`, `date` | canonical strings (DATA_MODEL §1.1) or XLSX date cells |
  | `datetime` | ISO 8601 with offset |
  | `ref` | an ID of an allowed type; for project and organization references also a slug |

### 9.4 Plan and result

`{stats: {rows, create, update, unchanged, conflicts, errors}, rows: [...]}` with at most 500 row items, errors first, then conflicts, then the rest: `{row, action: "create"|"update"|"unchanged"|"error", id, changes: {field: [current, new]}, conflicts: [{field, current, new, reason: "manual"|"seed"|"verified"|"restored"}], errors: {field: [messages]}}`. A row with conflicts still applies its other changes. The run's result is the same plan with the written IDs; `import_run.stats` uses the same keys, and `import_run.errors` stores the row errors and conflicts.

## 10. Manual documents (S8)

A manual document is always created from a stored snapshot: an upload (§10.1) or a fetch (§10.3). Both steps return **suggested values** derived from the file; the form shows them as editable defaults, and only what the person submits is written (channel `ui`, `src = manual`, DATA_MODEL §17.2).

### 10.1 From a file

`POST /api/uploads?filename=<name>` (raw bytes) → the snapshot and `suggested` = `{title, language, publisher, extraction_method, char_count, warnings}`: `title` from the HTML title (§7.4), the PDF or DOCX metadata title, else the file name without extension; `language` by §7.5; `warnings` e.g. `no_text_layer`. Then `POST /api/documents/manual {snapshot_id, title, url, retrieved_at, doc_type, language, publisher, published, published_basis, published_text, license, note}` (API §7.8):
- text extracted by type (§10.2); other types (images, XLSX, ZIP) are stored without text (`extraction_method = none`);
- `url` is the document's source address if there is one (e.g. the paper's reference URL of the KIIS/UNDP report when the PDF is uploaded, SOURCES S8); with a `url`, `retrieved_at` is required (DATA_MODEL §3.4), and the form proposes the current time.
The original file stays downloadable through its snapshot (API §7.3).

### 10.2 Text extraction (`documents/extract.py`, shared with C4 files)

| Type | Method (`extraction_method`) |
|---|---|
| PDF | pypdf text layer, pages joined with a blank line (`pdf`); no OCR: a PDF without a text layer gets no text and the response warns `no_text_layer` |
| DOCX | `word/document.xml` read with `zipfile` and ElementTree: paragraphs (`w:p`) as lines, runs (`w:t`), `w:tab` as a tab, `w:br` as a line break (`docx`) |
| HTML | §7.4 (`html`) |
| TXT | UTF-8 with or without BOM, or UTF-16 with BOM (`txt`); other encodings → `400 validation_error` "the text file is not UTF-8" |

The text is normalised and hashed as in DATA_MODEL §15.6.

### 10.3 From a URL, including archived copies

- `POST /api/documents/fetch {url}`: the server checks that no live document has the same canonical URL (else `409 unique_violation` with a link to it), then fetches the URL synchronously with the polite client (`source_id = manual`, `run_id` null): robots.txt, throttling, redirects, size limit, block detection and the `CONTACT_EMAIL` rule apply (§4), within a total budget of 60 s (§4.6). The response is stored as a snapshot and returned with `suggested` (as in §10.1; `publisher` = the host). `POST /api/documents/manual {snapshot_id, …}` then creates the document with `url` = the fetched URL and `retrieved_at` = the snapshot's `fetched_at` (neither is given in this step).
- **Archived copies** (the fallback for blocked or vanished pages, CLAUDE.md collection rules): a Wayback capture URL `https://web.archive.org/web/<14 digits>[id_]/<original URL>` is fetched in its `id_` form (the original bytes, SOURCES S5). The snapshot gets `via = wayback:<timestamp>` (the timestamp of the final URL, since the archive may redirect to the nearest capture); the document gets `url` = the original URL, `archive_urls` = [the capture URL] and `retrieved_at` = the fetch time. The original URL's path must not be disallowed by the newest stored robots.txt of its host, or, without a stored one, by the live robots.txt; if neither can be read, the copy is refused (`robots_unavailable`; SOURCES §5 item 2: never read archived copies of robots-disallowed paths).
- Failures → `502 fetch_failed {reason: "robots_disallowed"|"robots_unavailable"|"blocked"|"throttled"|"http_error"|"network_error"|"too_large", status}`; a missing or placeholder `CONTACT_EMAIL` → `409 collector_unavailable {reason: "contact_email_missing"}`. A blocked page can also be added from a saved copy (§10.1).

### 10.4 After adding

The new document is `unverified` and `unscreened` like any new document. The UI offers "Tag now", which starts a `tagger` run for this document (§8.6), so its suggested links and event proposals appear in the review inbox; while another run is running the start is refused (`409 run_in_progress`) and the person tags later.

## 11. CLI and Makefile

| Command | What it does |
|---|---|
| `mdt collect <name> [--mode incremental\|full] [--limit N] [--refetch] [--recall-sample N] [--recall-seed N] [--document ID …]` | run a collector (or `tagger`) in the foreground (§6.2); exit 0 succeeded, 2 partial, 1 failed, cancelled or refused |
| `mdt runs [--collector NAME] [--status STATUS] [--limit N]` · `mdt runs show <run_id>` | list runs · show one run with stats and messages |
| `mdt fixtures capture <name> [--only NAME …] [--force] [--out DIR]` | record the collector's `fixtures` list (below; Phase 2: `wayback`) |
| `mdt sources check [<name> …]` | reachability check from the current machine (below) |
| `mdt import <file> --type <type> [--sheet NAME] [--map COLUMN=FIELD …] [--key id\|slug\|url] [--note TEXT] [--dry-run]` | tabular import (§9) |
| `mdt check [--deep]` | integrity report including the Phase 2 checks (DATA_MODEL §13); `--deep` re-hashes every raw snapshot file |

Makefile targets: `make collect SOURCE=<name> [MODE=full]`, `make fixtures SOURCE=wayback`, `make sources-check`. In the container: `docker compose exec -u app app mdt collect ministry_projects`.

**`mdt fixtures capture <name>`** records the entries `{name, url, purpose}` of the collector's `fixtures` list through the polite client (robots.txt, throttling, User-Agent with `CONTACT_EMAIL`) and writes `<out>/<name>.<ext>` plus `<name>.meta.json` with every key of `backend/tests/fixtures/README.md` (`capture` = "mdt fixtures capture <collector> (app <version>), <UTC time>"; `licence` and `attribution` from `sources.yaml`; never the User-Agent or the contact address). `--out` defaults to `backend/tests/fixtures/<collector>/` in a source checkout, else `DATA_DIR/fixtures/<collector>/`. Bodies are written whole, so a list may name only openly licensed pages or technical responses without creative content (robots.txt, CDX JSON, sitemaps). Refused: bodies above 1 MiB, and bodies that contain the contact address, the User-Agent product token, any e-mail address or `__uzdbm` ("capture an excerpt by hand"). Existing files are kept unless `--force`. It writes no database rows. **On the target server:** `docker compose run --rm app mdt fixtures capture wayback` writes to `./data/fixtures/wayback/` on the host; copy that folder to `backend/tests/fixtures/wayback/` in a checkout, run `uv run pytest -q tests/test_fixtures.py` and the C5 parser tests, update the fixture list in `backend/tests/fixtures/README.md`, and commit (a push needs the data lead's approval).

**`mdt sources check [<name> …]`** fetches, per host of the selected collectors (default all; C2's hosts from the live projects' `official_urls`), robots.txt and the collector's check URL (option `check_url`, default the first start URL or the host root), and prints a table: host, robots decision, HTTP status, final URL, block signature, duration. It writes no database rows and exits 1 if a host is blocked or unreachable. It is the re-check from the target server (geo-blocking, risk R2; SOURCES §5 item 1).

## 12. Tests

All tests run offline (CLAUDE.md): collectors use the replay transport (§4.10) or `httpx2.MockTransport`; a real network transport in tests raises. Fixture paths below are relative to `backend/tests/fixtures/`.

### 12.1 Acceptance tests (Definition of Done 3 and 5)

- **DoD 3, idempotency** (`tests/collectors/test_idempotency.py`), for every collector of §1 against its fixture directory (C5: the synthetic fixtures with the setup below; `tagger`: documents created by a C4 run): on a fresh database (`alembic upgrade head` + `mdt seed`), run 1, then run 2 with the same transport. After run 2: **no new record of any type, no new revision, no new proposal row, no proposal that changed its state, no new `document_text` row**, identical document links; the observations of the keys seen show `last_seen_run` = run 2. Both runs are listed by `GET /api/runs` with their stats; URLs without a fixture make the runs `partial`, and their `refused` entries appear in `GET /api/runs/{id}/fetches` and the error messages in `GET /api/runs/{id}/messages` ("runs and errors are visible").
- **C5 setup and cases:** a test sources file (`SOURCES_FILE`) whose `wayback.options.prefixes` is `["example.org/projects/"]`; synthetic projects and services with `example.org` URLs created through `apply_change` in the test setup. Run 1 creates `first_archived` events with evidence for the exact matches and `create_event` proposals for the slug and domain-root matches; run 2 writes nothing; a run against a variant directory that adds an earlier capture creates a second event and leaves the first; a C5 event a person deleted is not recreated.
- **One record, several candidates:** two C3 services merged into one (DATA_MODEL §18); the next run reconciles the survivor from the first candidate, the second key only updates its observation (with `conflicting_candidates` where values differ), and a further run writes nothing.
- **DoD 5, manual values win** (`tests/collectors/test_manual_values_win.py`): run C1 → the seed project `brave1` gets `description_uk` from the collector (`src = collector:ministry_projects@<run>`, `locked = false`, `raw_snapshot_ids` = the listing page's snapshot); edit it through `apply_change` on channel `ui` (locked); run C1 again → the field keeps the manual value and `src = manual`, and one `update_field` proposal holds the collector's value. Accept → the value is the collector's, `src = collector:ministry_projects@<last run>`, `raw_snapshot_ids` from the proposal, `by = user`, `locked = true`, `revision.proposal_id` set. The other branches on their own projects (an accepted value is never proposed again): `diia-city` edit & accept → `src = manual`, state `accepted_modified`; `virtual-assets` reject → nothing changes and a further run does not reopen it. The same for a seed-locked URL list (`ministry_urls`: a different URL becomes a proposal holding only the URLs to add), an imported value (locked by the import), a field-verified value, and a record whose `verification_status` is `verified` (every differing field, system fields included, becomes a proposal). The importer side: an import never overwrites a manual value; the dry run lists the conflict.
- **Through the API** (`tests/api/test_runs.py`, with `COLLECTOR_RUN_INLINE=true` and the replay transport): `POST /api/runs` runs a collector; cancel; `409 run_in_progress` while a run is running; `409 collector_unavailable` (disabled, missing or placeholder `CONTACT_EMAIL`); a stale run is recovered as `failed`.

### 12.2 Parser tests

- One test module per collector (`tests/collectors/test_<name>_parse.py`) with the fixtures listed in §8, asserting candidates field by field against values read from the fixture (never from model knowledge).
- **Volatility tests** (DATA_MODEL §15.6): the real pairs `ministry_projects/project_yevrointegraciya_progress.html` + `ministry_projects/variant_yevrointegraciya_302.html` and `kmu_news/news_en_2019_regulation.html` + `kmu_news/news_en_2019_regulation_refetch.html` (plus an in-memory bot-manager variant, §8.4); derived variants (nonces, csrf tokens, inline scripts, `publishedAt.related`, image `?v=` changed in memory) for C2, C3 and C4.
- Shared helpers: the turbo-stream decoder on all turbo-stream fixtures (route selection, the `.data` unwrap, `ParseError` on an unknown constant or typed value); TipTap text and links with the assertions of §7.3; HTML text (hidden and trap elements dropped, footers kept) and the client-shell rule of §8.2; month names and Kyiv time (a non-existent time on 2021-03-28 and an ambiguous one on 2021-10-31); language detection (`ministry_news/news_article_en_2024.html` → `en`) and the kmu.gov.ua URL rule; the tagger (longest match `Дія.Бізнес` over `Дія`, case sensitivity, word boundaries, exclude phrases, no match of `Дії` without an inflection alias); event patterns (stems, phrases, `all_of`, sentence splitting around `Дія.City`, offsets into the stored text); duplicate detection (the 2019 pair yields a `possible_duplicate`, an unrelated pair does not); validation of `collector_mappings.yaml` (incl. `regulation` → `other`, "Результат" ignored) and `event_patterns.yaml`; the CDX parser on every synthetic fixture.

### 12.3 Client tests (local fake server)

`httpx2.MockTransport` handlers, and a threaded `http.server` on 127.0.0.1 where real sockets matter (timeouts, streaming, size limit). Cases: robots.txt longest match (`polite_client/robots_osvita_allow_first.txt`: `/programmes` refused), `Accept: */*` on robots requests and 406 handling (`polite_client/robots_osvita_406.txt` → robots.txt unavailable: URLs `refused`, run `partial`, and a failed run when it is the listing host), group-less rules (`polite_client/robots_playcity_no_user_agent.txt` honoured), HTML as robots.txt (`polite_client/robots_plan2_html_200.html` → allow all), rules followed by HTML (`polite_client/robots_usf_content_signal_with_html.txt`), a challenge on robots.txt (`polite_client/robots_codeua_cloudflare_challenge.html` → host blocked, no retry), kmu rules (`polite_client/robots_kmu.txt`: `/npas/` refused, a redirect hop to `/timeline` refused), `Crawl-delay: 10` (`polite_client/robots_data_gov_ua.txt`) and a `Crawl-delay` above `max_wait_s` (throttled); redirects (every hop checked, relative `Location`, at most 5, cross-host hops followed, excluded hosts refused); throttling with a fake clock (end-to-start interval per host, hops, retries and robots.txt counted, hosts independent); `Retry-After` in seconds and as HTTP date, more than 600 s not waited (throttled); the 60 s budget of manual fetches; retries on 429, 502, 503, 504 and network errors, none on 500 and 404; size limit by `Content-Length` and while streaming; conditional GET (304 → the earlier snapshot, re-parse); block detection (signatures, three 403 in a row; `wayback/availability_429.html` → Wayback unavailable); `CONTACT_EMAIL` rules and the User-Agent format; cookies not persisted after the run; `/cdn-cgi/` refused; trailing-dot host and empty path normalised; a `fetch_log` row per attempt; snapshots stored with the right SHA-256, gzip format and immutability (triggers); the replay transport (index keys, redirects and `final_url` registration, excluded names, duplicate keys refused, `via = replay` with the fixture's time).

### 12.4 Other tests

Reconciler (every row of the decision table, record-level verification, the text version unit, add-only URL lists, link suggestions on a locked `links` field, propose-only fields, collectors never clear, unknown codes, deleted matches block (live and deleted records searched), merged subjects followed, the first candidate per record and run, sightings, `possibly_discontinued` only after two runs with a complete listing whatever their end status and never after cancelled runs or runs without a complete listing); proposals (dedup states: refresh, rejection memory, an accepted key reopened only after a newer proposal, a new row after `superseded`; every supersede rule; accept, edit & accept, link to existing and reject per kind with the provenance of DATA_MODEL §16.4; evidence of accepted `create_event` proposals; bulk with `stale` and `needs_values`); merge and unmerge (repointing of every editable reference and of document links, conflicts, `merge_log`, one revision per changed row, unmerge restores, a plain undelete of a merged record is refused); importer (suggestions, value parsing, conflicts, a re-run writes 0 revisions, the dry run writes nothing); manual documents (each file type; suggested values; URL fetch through `MockTransport`; archived copies with `via = wayback:<ts>` from the final URL and the robots rule; canonical URL uniqueness); runs (one running run, stale recovery, cancel, end statuses); migration `0002` (upgrade of a database with Phase 1 data, downgrade, triggers on `raw_snapshot`); the Phase 2 checks of `mdt check`; the synthetic-fixture rules in `tests/test_fixtures.py`. E2E scenarios: UI §8.9.

## 13. Dependencies

| Package | Why | Notes |
|---|---|---|
| `httpx2` | the HTTP client under `PoliteHttpClient`: streaming with a size limit, manual redirects, timeouts, pluggable transports (`MockTransport`, the replay transport) | already in `uv.lock` as a dev dependency (Starlette's `TestClient` imports it first); it moves to the runtime dependencies. httpx itself is not added, so there is one HTTP stack with the same API |
| `protego` | robots.txt with RFC 9309 semantics (longest match, `*` and `$`), `Crawl-delay`, `Request-rate` | `urllib.robotparser` applies the first match (SOURCES §2). Checked [local, 2026-10-30] against the fixtures: osvita `/programmes` refused despite a leading `Allow: /`; kmu `/npas/`, `/timeline`, `/storage/` refused; data.gov.ua `Crawl-delay` 10; a group-less file (playcity) needs the preprocessing of §4.2 |
| `beautifulsoup4` | HTML parsing with Python's built-in `html.parser` | brings `soupsieve` (CSS selectors); no lxml |
| `pypdf` | text of PDFs (C4 files, uploads) | pure Python, BSD; extracted the Cyrillic text of `ministry_news/storage_pdf_draft_resolution.pdf` correctly [local, 2026-10-30]; preferred to pdfminer.six (more dependencies) and PyMuPDF (AGPL) |

Not added: trafilatura and lxml (heavy, version-dependent output; §7.4 is enough and reproducible), python-docx (DOCX via `zipfile` and ElementTree), python-multipart (uploads are raw request bodies, API §7.7), APScheduler (schedules are Phase 4), pymorphy3 (Phase 3), defusedxml (XML-bomb protection was dropped with D-15; sitemaps and Atom are parsed with ElementTree). openpyxl, already a dependency, reads XLSX imports.

## 14. Deferred

- **Phase 3:** C2a `digitalstate_catalog` and C3b `diia_guide` (cross-check sources while D-12 is open; their fixtures stay in `fixtures/digitalstate_catalog/` and `fixtures/diia_guide/`, and the D-12 default "cross-check sources, observations only" applies when they are built); C6 legal acts (after the server check of zakon.rada.gov.ua; until then the S6 alternative applies, SOURCES S6); C7 Telegram and data.gov.ua; Wayback reconstruction of the catalogues at the cut-off dates, documents recovered from the archive in bulk and an automatic Wayback fallback inside collectors (era-specific parsers need real captures); the UNITED24 report harvester, Diia.Education courses and sitemap inventories of project sites; ai.thedigital.gov.ua (scope decision, SOURCES §5 item 5); pymorphy3 inflection suggestions for aliases; merging organisations and components, and proposals for organisations, participations and relations from page statements (D3); evidence capture in the document view; collector dry runs and resumable runs, if long backfills turn out to need them.
- **Phase 4:** schedules, backups of `data/raw`, pruning of old `fetch_log` rows (collected values stay traceable through their field-level snapshot references), releases with the included runs in the manifest.
