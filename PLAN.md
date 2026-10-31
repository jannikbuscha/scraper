# PLAN: data platform for "Digital Innovation for Governments under Crisis"

> **Status:** Phase 0 plan, 2026-10-28; approved, Phase 1 done (2026-10-29); Phase 0b source checks done from the development environment on 2026-10-29, except the hosts it cannot reach (§2.2, §10). Decision D-15 of 2026-10-29 (§12: one user, no concurrent editing, no additional security layer) supersedes the plan passages marked with it. For Phase 1 onwards, the contract documents [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md), [`docs/API.md`](docs/API.md) and [`docs/UI.md`](docs/UI.md) are binding, and from Phase 2 on also [`docs/COLLECTORS.md`](docs/COLLECTORS.md) (Phase 2 contract of 2026-10-30, which also records the data lead's local source checks of that day); where they differ from this plan in detail (e.g. provenance rules, derived-field algorithm, seed matching, the collector process model of §3.4, the stack choices of §3.2), they take precedence.
> **Companion drafts:** [`docs/SOURCES.md`](docs/SOURCES.md) (source register), [`docs/CODEBOOK.md`](docs/CODEBOOK.md) (vocabularies).
> **Language:** code, UI, docs and codebook in English (language of the paper).

## TL;DR

- **One container, one process.** FastAPI serves the API and the built React app. The working store is SQLite (WAL, FTS5). Collectors run as subprocesses of the same image, started by a scheduler, a UI button or the CLI.
- **Traceability built into the model.** Every curated field records where its value came from (`seed`, `collector:<name>@<run>`, `manual`, `import:<file>`), who set it, whether a human has locked it, and optional evidence. Revisions are append-only, enforced by database triggers. Collectors never overwrite human values: they open **proposals** instead.
- **Collectors** are separate modules with offline tests against saved fixtures. They use a polite HTTP client (robots.txt, about 1 request per second per host, conditional requests, backoff, no circumvention). Every response is kept unchanged as a content-addressed raw snapshot. The Wayback Machine serves as a fallback and supplies *upper bounds* for start dates, never start dates.
- **Main additions to the proposed model:** dates stored as intervals with precision and the verbatim source text; per-source observations (for `first_seen`/`last_seen` and "possibly discontinued"); an explicit `development_mode` field (adaptation vs. new development, Yoo et al. 2012); `unit_type` (product vs. platform, programme, strategy, organisation); the derived `portfolio_entry` (launch ≠ entry into the ministry's portfolio); institutional context events; derived values in their own table; content-addressed document texts; screening reason codes (for a PRISMA-style flow in the paper).
- **Phase 0 findings relevant for the paper (§13; leads, partly checked in Phase 0b):** responsibility for PlayCity moved away from the ministry in 2026; the ministry's leadership and mandate changed in 2025–2026; for several projects the ministry is not the initiator; European Integration and WINWIN look more like policy areas or strategies than products.
- **Releases** are frozen, hashed exports committed and tagged in git (`make release NAME=…`), created from the CLI only (reasons in §6.7).
- **Phase 0b (2026-10-29):** with network access enabled, the hands-on source checks ran from the development environment: structured access exists for most sources (embedded page data, sitemaps, a JSON register, an Atom feed), 103 fixtures are committed, and the Wayback Machine and zakon.rada.gov.ua, which this environment cannot reach, remain to be checked from the target server (§2.2, §10). Everything this plan says about a source is labelled by how well it is supported (see below).

### Evidence labels used in this plan and in `docs/SOURCES.md`

| Label | Meaning |
|---|---|
| **[user]** | Stated in the assignment (checked by the data lead on 2026-10-28). |
| **[paper]** | Stated in `paper.docx` (read in full on 2026-10-28; file unchanged). |
| **[local]** | Verified by running code in the development environment. |
| **[doc]** | Read in official documentation retrieved on 2026-10-28 (e.g. the Wayback CDX server README on GitHub). |
| **[search]** | A URL or title seen in web-search results on 2026-10-28. The URL exists in a search index; the page content was not retrieved. |
| **[search-summary]** | The claim appears only in the model-written summary that the search tool adds to its results. Weaker than [search]; to be verified. |
| **[hypothesis]** | An expectation still to be verified. Never used as a fact and never written into the data. |
| **[0b]** | Retrieved directly on 2026-10-29 (Phase 0b); capture sha256 in the fixture metadata or the Phase 0b log. Evidence of what a source showed that day, not data. |
| **[live]** | Retrieved directly by a limited live run of the Phase 2 collectors from the development environment on the date given (2026-10-30); URL, fetch time and snapshot sha256 cited in `docs/SOURCES.md`, the run database and raw snapshots kept outside the repository. Evidence of what a source showed that day, not data. |

---

## 1. Goals and guiding principles

The platform has two jobs: (1) reproducibly collect the portfolio of projects and digital services of the Ministry of Digital Transformation of Ukraine (Мінцифри) and a corpus of documents for the planned document analysis, and (2) let the team view, filter, comment on and correct those data with a complete history.

**Guiding principle: traceability before completeness.** Each principle maps to a concrete design decision:

| Principle | Design consequence |
|---|---|
| No facts from model knowledge | Values enter only through collectors (each backed by a raw snapshot), the seed, an import or the app's user. Every write records its channel and, per field, its provenance (the app's user is recorded as `user`, D-15). The app makes no LLM calls (non-goal). |
| Derived values are marked | Derived fields live in a separate table. They are read-only, carry their basis and reason, and are exported with a `derived_` prefix. |
| Automation never overwrites humans | A per-field `locked` flag. Collectors write only unlocked fields; for locked fields they create proposals. |
| Nothing is hard-deleted | Soft delete with a trash view. The revision table is append-only (UPDATE and DELETE are blocked by triggers). Hard purge is CLI-only. |
| Numbers in the paper are reproducible | Git-tagged dataset releases with a manifest (counts, SHA-256 hashes, code commit, schema revision). |

---

## 2. Phase 0 findings

### 2.1 What the paper needs from the data [paper]

- **RQ:** How do governments develop digital products and services in war? Single case: the Ministry of Digital Transformation of Ukraine (founded 29 Aug 2019). The study compares the time before and after the full-scale invasion of 24 Feb 2022.
- **Method:** (1) portfolio mapping of projects and digital services, including sub-services and available launch dates, classified by *primary objectives, policy domains, intended beneficiaries, relevance to wartime needs* and information on *introduction or modification*; (2) qualitative document analysis with thematic coding along Table 1 (D1 needs and priorities, D2 platforms, D3 distributed innovation, D4 combinatorial innovation); (3) semi-structured interviews later.
- **Theory:** the three characteristics of digital innovation (platforms, distributed innovation, combination of existing components) and the distinction between **continuously adapting existing services** and **developing new services** (Yoo et al. 2012).
- **Current results:** 19 projects in seven clusters. The methodology states that "structured datasets of the Ministry's projects and digital services, including associated sub-services and available launch dates" **have already been collected**. Whether that table exists and can be imported is an open question (§14).
- **Claims in the paper that need evidence in the data:** the description of PlayCity (digitised licensing for online gambling, online monitoring, taxes for the Armed Forces) and of Brave1 (both uncited in the current draft); the KIIS/UNDP usage figures (candidates for `Indicator` rows that cite the report).

**Consequences for the data model:** a two-level portfolio (Project → Service, with sub-service hierarchy); events with explicit date uncertainty, so the pre-/post-invasion comparison holds up even with imprecise dates; evidence records that tie every classification and every D1–D4 statement to a verbatim quote; and an explicit representation of adaptation versus new development (§4.5).

### 2.2 Development environment constraints [local]

- **Phase 0 (2026-10-28):** all source hosts were blocked by the egress policy of this cloud environment (HTTP 403 from the proxy on CONNECT). Web *search* worked (URLs and titles, no page content), and GitHub was reachable, which allowed reading the official Wayback CDX documentation [doc]. Phase 0 was therefore done with three search-only explorations, recorded with evidence labels in `docs/SOURCES.md` and §13; none of it was entered as data.
- **Phase 0b (2026-10-29):** the data lead enabled network access for the source hosts ("Der Netzwerkzugriff ist aktiviert"). The source checks then ran from this environment: an orchestrating session and five explorers shared one polite fetcher (robots.txt obeyed, at least 1 s between requests per host, 5 s for archive hosts, `Retry-After` honoured, every request logged; exceptions: one redirect hop to a robots-disallowed path, and redirect hops followed at once, 6 of them to the same host less than 1 s after the redirect response, `docs/SOURCES.md` §2) and made 195 HTTP requests to 34 hosts plus 8 logged browser page loads for XHR discovery, 12:55-14:09 UTC [0b]. Eight connectivity checks shortly before (12:46-12:48 UTC) bypassed the fetcher; none got an answer from a source server (`docs/SOURCES.md` §4). Results per source: `docs/SOURCES.md` ("Phase 0b results"); fixtures: `backend/tests/fixtures/` (§5.7).
- **Still not reachable from this environment (2026-10-29) [0b]:**
  - `web.archive.org` (S5), `zakon.rada.gov.ua` and `data.rada.gov.ua` (S6) and `cms.thedigital.gov.ua` (older ministry file uploads): the TLS handshake was never answered (connection reset after 14-17 s; the agent proxy saw no byte from the server). The cause (egress path or server-side filtering) is not determinable from here.
  - `archive.org`'s availability API answered HTTP 429 on the first request, so the environment's shared egress IP was already throttled.
  - `codeua.com` (Cloudflare managed challenge on robots.txt) and `www.undp.org` (HTTP 403 from the Akamai edge on robots.txt) block automated access; no circumvention was attempted.
  - The trailing-dot host `diia.gov.ua.` got no answer through the agent proxy.
- **Not allowed by robots.txt (independent of the environment) [0b]:** www.kmu.gov.ua `/npas/`, `/storage/`, `/timeline`, `/api/`; data.gov.ua `/api/` (CKAN action API) and `/dataset/*/history`; guide.diia.gov.ua `/api/schema/swagger` and `/search/?q=*`.
- **Consequences:** S5 and S6 (and the four hosts above) must be checked **from the target server** before C5 and C6 are built; the same applies to a quick re-check of every reachable host, because the server's location may change what is reachable (risk R2). All other Phase 0b checks are done.
- **Available locally:** Python 3.13, uv, Node 22, Docker CLI, pandoc, SQLite 3.45.1 with FTS5 (including the trigram tokenizer); headless Chromium for Playwright (used only for the Phase 0b XHR checks).

### 2.3 Source assessment (summary)

<!-- SOURCE-SUMMARY:BEGIN -->
Details, evidence and the Phase 0b results per source are in [`docs/SOURCES.md`](docs/SOURCES.md). Status after Phase 0b (2026-10-29).

| # | Source | Role in the dataset | Known after Phase 0b | Main risks | Assessment |
|---|---|---|---|---|---|
| S1 | Ministry project list (`thedigital.gov.ua/projects`) | Portfolio backbone, ministry categories | Complete loader data embedded in every page (React Router turbo-stream); 20 entries on 2 pages; 12 rubrics with Ukrainian labels, 6 used as primary rubrics incl. `army` (missing from the seed paths); project UUIDs, `additionalRubrics`, outbound links; no dates on projects; 6 `link` entries point to their own domains (the one requested, WINWIN, redirects with 302); CC BY 4.0 footer [0b] | Beta relaunch [0b]; dependency on the framework's payload format; URL variants and legacy slugs (`/projects/<slug>` redirects only while the slug exists) [0b] | **Priority 1.** Verified; small, structured, high value |
| S2 | Project pages and project sites | Descriptions, operators, outbound links, structured offers | Official domains resolved through the ministry pages (Brave1, Мрія, CDTO Campus, Дія.Цифрова громада, uResidency, Дія.City); Дія.Engine and Віртуальні активи link none; none of the checked own domains is openly licensed; WINWIN is rendered in the browser without a data API; UNITED24 publishes dated weekly report PDFs; Digital State UA has a structured catalogue (17 projects, C-1) [0b] | Heterogeneous sites; codeua.com behind a Cloudflare challenge; trap links and soft 404s; some pages outdated (PlayCity) [0b] | **Priority 2.** Generic collector plus C2a (Digital State UA) and a UNITED24 report harvester |
| S3 | Diia portal catalogue (`diia.gov.ua/services`) and the service guide | Services with rubric and audience | Server-rendered HTML, no API; 172 catalogue entries (the 171 URLs of the services sitemap, plus `/services/RD4U`, which on 2026-10-30 was a redirect page, not a service page [live]), 2 audiences, 27 subcategory entries; the guide (`guide.diia.gov.ua`) publishes its full register as open JSON/XLSX under CC BY 4.0 (1921 entries; maps 46 portal services); `plan2.diia.gov.ua` is a 2021 project catalogue without status data [0b] | App-only services missing [user]; history only via Wayback (not reachable from here); Cloudflare in front | **Priority 3.** Core of the service inventory; C3 (HTML) plus C3b (guide JSON) |
| S4 | Ministry news, documents and pages; ministry news on kmu.gov.ua | Document corpus; event proposals; filling the 2019–2022 gap | thedigital.gov.ua: embedded data with machine-readable dates; news back to **2019-10-07** (4385 items, 1875 dated before 2022-02-24); 1267 documents with types and kinds; work plans 2020, 2021, 2023, 2024 and reports 2020-2023 linked from `/ministry`; files content-addressed (MD5 = name). kmu.gov.ua: complete dated news sitemaps (UA from 2016, EN from 2014), UA and EN share slugs, CC BY 4.0; no per-ministry listing; `/npas/` and `/storage/` robots-disallowed [0b] | Document `publishedAt` is not a document date (bulk timestamps); two transliteration styles; duplicates across both sites; kmu.gov.ua bot manager; recall of slug-keyword discovery unknown | **Priority 4.** Largest volume; kmu.gov.ua needed for 2019-08-29 to 2019-10-06, English versions and cross-checks |
| S5 | Wayback Machine (CDX API) | Archive upper bounds; catalogue at cut-off dates; fallback | Parameters verified in the official README [doc]; **not reachable from this environment** (no TLS answer; archive.org availability API 429) [0b] | Throttling, gaps, layout eras; possibly blocked from the server too | **Priority 5.** Essential, slow by design; to check from the target server |
| S6 | zakon.rada.gov.ua | Legal acts, legal-basis events | URL patterns and acts identified [search]; **not reachable from this environment** (no TLS answer) [0b]; kmu.gov.ua act pages are robots-disallowed [0b] | Reachability; bot protection not determinable | **Priority 6.** Linked acts only; to check from the target server |
| S7 | Telegram (`t.me/s/mintsyfra`); data.gov.ua (CKAN) | Announcements; machine-readable registers | Telegram preview paginates back to the first posts (2019-09-27) with UTC timestamps per post; data.gov.ua: 30 datasets (`cc-by`), Atom feed and DCAT per dataset, CKAN API robots-disallowed, `Crawl-delay: 10`; the Diia guide register is not among them [0b] | Volatile page bytes; low relevance of the CKAN datasets; personal data in feeds | **Priority 7.** Optional; both feasible |
| S8 | Manual (URL or upload) | Reports, interviews, press | KIIS/UNDP report page exists [search]; www.undp.org answered HTTP 403 (Akamai) from here [0b] | — | Always available; upload the report if the server is blocked too |

**Candidates assessed in Phase 0b [0b]:** the Digital State UA catalogue (structured, all rights reserved: specialised collector C2a, cross-check source, D-12); the Diia service guide (open register: collector C3b, D-12); `plan2.diia.gov.ua` (2021 catalogue of 94 projects without status fields: one-off dated snapshot, not a collector); the year-in-review microsites (static single pages: S4 documents; only `2years.` is CC BY 4.0); work plans and reports on `storage.thedigital.gov.ua` (linked from `/ministry`: plans 2020, 2021, 2023, 2024, reports 2020-2023; nothing for 2019 or 2025, no 2022 plan, no 2024 report). New: `ai.thedigital.gov.ua`, an ongoing AI policy portal with its own news and documents (API not identified; scope decision in `docs/SOURCES.md` §5).

**Cross-cutting risk:** some Ukrainian state services block foreign IP addresses (e.g. the State Tax Service, which unblocks only on request [search]). From the development environment every gov.ua host answered except zakon.rada.gov.ua, data.rada.gov.ua and cms.thedigital.gov.ua (no TLS answer); no gov.ua host showed a challenge or geo-block page [0b]. "data.gov.ua was temporarily restricted" [search-summary] is a historical claim that today's captures cannot check; the portal answered normally. Access must still be tested **from the target server** before Phase 2.
<!-- SOURCE-SUMMARY:END -->

---

## 3. Architecture

### 3.1 Overview

```
                ┌──────────────────────────── container "app" (one image) ───────────────────────────┐
 Browser ─HTTP─▶│ uvicorn + FastAPI                                                                  │
 (one user)     │   /api/*      REST + Pydantic models                                               │
                │   /*          built React app (static files)                                       │
                │   domain services: revisions · provenance · reconciliation · derived fields        │
                │   scheduler (APScheduler) ──spawns──▶ `mdt collect <source>`  (subprocess, queued) │
                │   SQLite: data/app.db (WAL, FTS5)                                                   │
                │ CLI `mdt` (Typer): collect · import · release · backup · restore · purge · check   │
                └─────────────┬──────────────────────────────────────────────────────────────────────┘
                              │ volume ./data     → db, raw/, uploads/, backups/, import/, logs/
                              │ bind   ./releases → release exports (committed + tagged on the host)
```

Collector data flow:

```
sources.yaml ─▶ Collector ─▶ PoliteHttpClient ─▶ RawSnapshot store (unchanged bytes, sha256, gzip)
                   │                                   │
                   └── parse(snapshot) ─▶ Candidates ─▶ Reconciler ─┬─▶ entity update + Revision + field provenance
                                                                    ├─▶ Proposal (review inbox)
                                                                    └─▶ SourceObservation (first/last seen)
```

### 3.2 Stack

The proposed stack is kept. Additions and choices are marked with ➕:

| Area | Choice | Reason |
|---|---|---|
| Runtime | Python 3.12+ (image `python:3.13-slim`), uv + `uv.lock` | as proposed |
| API | FastAPI, Pydantic v2 | as proposed |
| DB | SQLAlchemy 2 (typed `Mapped[]`), Alembic in batch mode (needed for SQLite `ALTER TABLE`), SQLite WAL + FTS5 | as proposed; pragmas `foreign_keys=ON`, `busy_timeout=10000`, `synchronous=NORMAL` |
| HTTP | httpx (sync) + own `PoliteHttpClient` | per-host throttling, robots.txt, conditional GET, retries in one place |
| robots.txt | ➕ `protego` | supports wildcard rules, which `urllib.robotparser` does not |
| HTML | BeautifulSoup4 + lxml | robust on messy CMS HTML; speed is irrelevant at ≤ 1 request/s |
| Main text | trafilatura | main text and metadata extraction for news and article pages |
| PDF/DOCX | ➕ pdfminer.six / pypdf, python-docx | permissive licences; PyMuPDF avoided (AGPL) |
| Browser | Playwright **only for Phase 0b exploration** (watching XHR/JSON endpoints) | collectors stay browser-free unless a source is unusable otherwise |
| Morphology | ➕ `pymorphy3` + Ukrainian dictionaries | generates inflected **alias candidates when an alias is edited**; a person confirms them, so matching stays deterministic and reproducible (§5.3) |
| Markdown | ➕ markdown-it-py | comments rendered server-side with raw HTML disabled; no further sanitising (D-15) |
| Scheduling | ➕ APScheduler 3.x in-process | jobs run as subprocesses behind a global run lock (§3.4) |
| IDs | ➕ `python-ulid` | stable, sortable, prefixed IDs (§4.1) |
| Spreadsheets | openpyxl | XLSX import and export |
| CLI | Typer | `mdt …` |
| Frontend | React + TypeScript + Vite; TanStack Router, Query, Table | TanStack Router gives typed, validated **URL search params**, so the filter state lives in the URL and links can be shared |
| Components | ➕ **Mantine** | dense tables, multi-selects, date-range pickers, modals and notifications out of the box; no Tailwind build step |
| Charts | ECharts (SVG renderer) | timeline and heatmaps; SVG/PNG export for figures in the paper |
| Diffs | ➕ jsdiff | word-level diffs of long text fields |
| Tests | pytest, Vitest, Playwright (E2E smoke) | as proposed |
| Lint/types | ruff, mypy (strict for domain code), ESLint (typescript-eslint), tsc | as proposed |

> **Phase 2 (2026-10-30):** the libraries for data acquisition are settled by `docs/COLLECTORS.md` §13, which is binding: httpx2 under the `PoliteHttpClient` (not httpx), protego, beautifulsoup4 with Python's `html.parser` (no lxml), the text extraction of COLLECTORS §7.4 instead of trafilatura, pypdf for PDFs and DOCX read with `zipfile` (no pdfminer.six, no python-docx), and tzdata. Runs execute in a thread of the server process or in the CLI, without subprocesses (COLLECTORS §6); APScheduler arrives with the schedules in Phase 4.

### 3.3 Repository layout

```
/
├── paper.docx                 # unchanged
├── PLAN.md  README.md  CLAUDE.md (Phase 1)
├── Makefile  Dockerfile  docker-compose.yml  .env.example
├── sources.yaml               # source registry: hosts, throttling, licence, schedule, enabled
├── seed/                      # projects.yaml (19 + 1 projects, provenance "seed")
├── codebook/                  # vocabularies as YAML (versioned; DB holds the working copy)
├── releases/                  # frozen dataset releases (committed + tagged)
├── docs/                      # DATA_MODEL.md, CODEBOOK.md (generated), SOURCES.md, METHODS.md
├── backend/
│   ├── pyproject.toml  uv.lock  alembic.ini  migrations/
│   ├── src/mdt/
│   │   ├── config.py  cli.py
│   │   ├── db/          # engine, models/, fts.py, triggers
│   │   ├── domain/      # revisions, provenance, reconcile, derived, merge, aliases
│   │   ├── api/         # routers per resource, filter grammar, exports
│   │   ├── collectors/  # base.py, http.py, snapshots.py, one module per source
│   │   ├── importers/   # tabular importer (CSV/XLSX) with mapping + dry run
│   │   ├── exports/     # dataset, QDA corpus, codebook
│   │   └── ops/         # release.py, backup.py, purge.py, check.py
│   └── tests/           # unit, api, collectors (offline fixtures), e2e helpers
├── frontend/            # Vite app (src/routes, src/components, src/api)
├── .github/workflows/ci.yml
└── data/                # gitignored: app.db, raw/, uploads/, backups/, import/, logs/
```

Python package and CLI name: **`mdt`** (Ministry of Digital Transformation).

### 3.4 Process model

> **Phase 2 contract:** collector runs execute in a thread of the server process or in the CLI process, one run at a time in the whole database, without subprocesses, a queue, checkpoints or a scheduler (`docs/COLLECTORS.md` §2, §6); the bullets on subprocesses and resumable runs below are the original plan.

- **One container and one uvicorn process** serve the API and the static frontend.
- **Collector runs** (from the schedule, the UI's "Run now" button or the CLI) execute as subprocesses (`mdt collect <source>`). A DB-backed queue runs them **one at a time**. That keeps per-host rate limits valid globally and gives SQLite exactly one background writer. Runs are weekly, so serial execution costs nothing.
- **Resumable runs:** each run stores a checkpoint (page, cursor, URL frontier) on its `CollectorRun` row; `mdt collect X --resume` continues from there.
- **Web requests are never blocked** by collectors: WAL mode, small per-entity transactions and `busy_timeout`.

### 3.5 Configuration (`.env`, template in `.env.example`)

`HOST` (default `127.0.0.1`), `PORT` (`8080`), `DATA_DIR`, `CONTACT_EMAIL` (**required for collectors**: they refuse to start without it), `USER_AGENT` template, `COLLECT_SCHEDULE` (cron; default weekly, Monday 03:00 Europe/Kyiv), `BACKUP_SCHEDULE` (daily), `BACKUP_RETENTION` (7 daily / 4 weekly / 6 monthly), `MAX_UPLOAD_MB` (50), `MAX_COMMENT_CHARS` (10 000), per-source overrides of throttling in `sources.yaml`.

---

## 4. Data model

### 4.1 Conventions

- **IDs:** prefixed ULIDs: `prj_`, `svc_`, `evt_`, `doc_`, `evd_`, `org_`, `par_`, `cmp_`, `rel_`, `ind_`, `cmt_`, `prp_`, `run_`, `raw_`. The prefix makes polymorphic references self-describing (`subject_id = "svc_01J…"`) and keeps exports readable. Projects also have a `slug` (unique; an old slug becomes an alias when renamed).
- **Common columns of every curated row:** `version` (numbers the row's revisions; no optimistic locking, D-15), `created_at`, `updated_at`, `deleted_at`/`deleted_by` (soft delete), `merged_into`, `verification_status`, `notes`, `field_meta` (JSON, §6.2).
- **Multi-valued vocabulary fields** (`policy_domains`, `beneficiaries`, `channels`, …) are JSON arrays of codes, validated against active vocabulary terms. Facet counts and filters use SQLite's `json_each`.
- **Dates of events and publications** are stored as an interval plus metadata: `date_start`, `date_end` (inclusive), `date_precision` (day/month/quarter/year), `date_basis` (stated_in_source/inferred/archive_upper_bound) and `date_text` (verbatim from the source, e.g. `22 жов., 14:00`). "March 2022" becomes 2022-03-01…2022-03-31 with precision `month`.
- **Time zones:** timestamps in UTC (ISO 8601); publication dates as calendar dates in Europe/Kyiv. If a source gives a UTC timestamp, the Kyiv date is computed and the timestamp kept in `published_at_utc`.
- **Integrity:** polymorphic references are validated in the domain layer and by `mdt check` (a periodic integrity report); simple foreign keys (e.g. `service.project_id`) are real FKs.

### 4.2 Curated entities

**Project**

| Field | Notes |
|---|---|
| `slug`, `name_en`, `name_uk` | `name_en` may stay empty if no official English name exists; there is no machine translation |
| `aliases[]` | `{text, lang, case_sensitive, kind: name/inflection/abbreviation/domain, exclude_patterns[]}`, used for matching (§5.3) |
| `paper_cluster` | vocabulary (7 clusters) |
| `unit_type` | ➕ vocabulary: product/service, platform, programme, strategy/policy area, organisation (decision D-11; separates e.g. a strategy listed as a "project" from a digital product) |
| `ministry_categories[]` | **list**, because one project can appear under several categories (Diia.City under `/projects/business/city` and `/projects/regions/city` [user]); each entry records category code, URL and source observation |
| `description_en`, `description_uk` | short description |
| `official_urls[]`, `ministry_urls[]` | primary URL first |
| `in_paper_scope`, `scope_note` | scope decision with reason; separate from "is listed by the ministry" |
| `status` | vocabulary (operational status) |
| `primary_objectives` | text (structured coding later if the team wants it) |
| `policy_domains[]`, `beneficiaries[]` | vocabulary |
| `wartime_relevance`, `wartime_rationale` | vocabulary + text |
| `development_mode`, `development_rationale` | ➕ new_development / adaptation_of_existing / unclear (§4.5) |
| `d1_need`, `d1_affected_groups`, `d1_priority_link` | D1 as text |
| `d2_summary`, `d3_summary`, `d4_summary` | free-text summaries, supported by structured Participations and Relations |
| common columns | see §4.1 |

**Service** (service or sub-service): `project_id`, `parent_service_id` (hierarchy), `name_en`, `name_uk`, `aliases[]`, `kind`, `channels[]`, `source_categories[]` (`{source, label, url}`: the section in the source; can be several), `source_audiences[]` (audience as labelled by the source, e.g. citizens/business), `policy_domains[]`, `beneficiaries[]`, `wartime_relevance` + rationale, `development_mode` + rationale, `status`, `urls[]` (canonical first), optional `d1…d4`, common columns. `first_seen`/`last_seen` are **derived** from SourceObservation (§4.3) and not editable.

**Event** (introduction or modification): `subject_id` (`prj_`/`svc_`/`cmp_`/`org_`), `event_type`, date interval with precision, basis and verbatim text (§4.1), `description_en`, optional `description_uk`, common columns. Its sources are Evidence rows that point at the event. Organisations as subjects allow **institutional context events** (e.g. changes in the ministry's leadership or mandate), which the timeline can show as markers.

**Focal organisation:** the ministry itself is seeded as an Organization with its name only (from the assignment). It anchors Participations and the derived `portfolio_entry` (§4.4). The cut-off dates 2019-08-29 and 2022-02-24 are **codebook parameters** set by the team, not data values.

**Document**

| Field | Notes |
|---|---|
| `title`, `title_en` | original title; English title optional and manual |
| `url`, `canonical_url` | `canonical_url` is normalised (scheme, host, trailing slash, tracking parameters) and unique among non-deleted documents |
| `publisher` (host/site), `publisher_org_id` | the organisation is optional |
| `source_id`, `external_id` | key in `sources.yaml`; ID given by the source, if any |
| `doc_type`, `language` | vocabulary; ISO 639-1 |
| `published_*` | interval, precision, basis, verbatim text, `published_at_utc` (if machine-readable) |
| `retrieved_at`, `raw_snapshot_id`, `text_hash` | latest snapshot and text version |
| `extraction_method` | api / json-ld / trafilatura / selector / pdf / docx / manual |
| `archive_urls[]`, `license` | |
| `screening_status`, `screening_reason`, `screening_note` | unscreened/included/excluded + reason code (vocabulary) + text |
| links | `DocumentLink` rows (part of the document's revision snapshot) |

- **DocumentText** (immutable, content-addressed): `text_hash` (sha256 of the normalised text), `text`, `char_count`, `created_at`. When a page changes, a new text version is created and the document points to it; the change shows up in the document's history. Keeping texts out of revision snapshots keeps the revision table small even with tens of thousands of documents.
- **DocumentLink:** `document_id`, `subject_id` (`prj_`/`svc_`), `origin` (auto/manual), `state` (suggested/confirmed/rejected), `matched_aliases[]`, `match_count`, `snippet`.
- **Evidence** (citation): `subject_id` (any curated entity, including events, participations and relations), `target` (`field:<name>`, `dimension:D1…D4` or `entity`), `document_id` **or** `url` + `archive_url` (for sources that are not documents, e.g. a CDX record), `raw_snapshot_id`, `text_hash` + `char_start`/`char_end` (exact location in one text version), `quote` (verbatim, at most 1 000 characters), `locator` (page, paragraph), `note`, author.
- **Organization:** `name_en`, `name_uk`, `aliases[]`, `org_type`, `country` (ISO 3166-1 alpha-2), `urls[]`.
- **Participation** (for D3): `organization_id`, `subject_id` (`prj_`/`svc_`/`cmp_`), `role`, period (interval + precision), `note`; evidence through Evidence rows.
- **Component** (platform or infrastructure that is not itself a portfolio project): `name_en`, `name_uk`, `aliases[]`, `component_type` (draft vocabulary in the codebook), `description`, `urls[]`. Components are created only from sources, never from the seed.
- **Relation** (for D2 and D4): `from_id`, `to_id` (`prj_`/`svc_`/`cmp_`), `relation_type`, `note`. Reading direction: *from* `relation_type` *to* (e.g. "service A **extends** service B").
- **Indicator** (optional): `subject_id`, `metric`, `value` (decimal), `unit`, `as_of` (interval + precision), `note`; the source is an Evidence row.
- **VocabularyTerm:** `vocabulary`, `code` (stable), `label_en`, `label_uk`, `definition`, `include`/`exclude` notes, `examples`, `sort_order`, `active`, `replaced_by`, `attributes` (JSON, e.g. `counts_as_modification` for event types). A code is never renamed; it is deactivated and replaced.

### 4.3 System tables

| Table | Purpose and key columns |
|---|---|
| **Revision** | `id`, `entity_id`, `entity_type`, `version`, `at`, `author`, `channel` (seed/ui/collector/import/restore/merge/system), `run_id`, `proposal_id`, `restored_from`, `batch_id` (bulk edits, merges), `note`, `snapshot` (JSON), `diff` (JSON `{field: [old, new]}`). **Append-only via triggers.** |
| **Comment** | `subject_id`, optional `field`, `parent_id` (thread), `author`, `body_md` (limited length), `status` (open/resolved, on the thread root), `resolved_by`/`at`, `version`, `deleted_at`. Edits create revisions. |
| **Proposal** | `kind` (create_entity, update_field, create_event, link_document, possibly_discontinued, possible_duplicate), `subject_id`, `field`, `current_value`, `proposed_value`, `payload`, source (`run_id`, `raw_snapshot_id`, quote, locator), `dedup_key`, `state` (open/accepted/accepted_modified/rejected/superseded), `decided_by`/`at`, `decision_note`, `first_run`/`last_run`. |
| **CollectorRun** | `collector`, `trigger` (schedule/ui/cli), `params`, `started_at`, `finished_at`, `status` (queued/running/succeeded/partial/failed/cancelled), `complete_listing` (bool), counters (requests, not_modified, snapshots_new, entities_new, entities_updated, proposals_new, errors), `checkpoint`, `log_path`, `code_version`. |
| **FetchLog** | One row per HTTP request: URL, status, bytes, duration, not-modified flag, snapshot, error. |
| **RawSnapshot** | `url`, `final_url`, `fetched_at`, `http_status`, selected headers (ETag, Last-Modified, Content-Type, …), `sha256`, `path`, `size`, `run_id`, `source_id`, `via` (live / `wayback:<timestamp>` / upload). Files under `data/raw/ab/<sha256>.gz`, deduplicated by hash, never modified. |
| **SourceObservation** | `subject_id`, `source_id`, `key` (URL or external ID), `first_seen_at`/`run`, `last_seen_at`/`run`, `present`, `consecutive_misses`, latest snapshot. |
| **SavedView** | `name`, `table`, `query` (URL search string), `description`, `created_by`; visible to everyone; revisioned. |
| **Release** | `name`, `created_at`, `path`, `git_tag`, `code_commit`, `schema_revision`, `manifest`. |
| **MergeLog** | `survivor_id`, `merged_id`, `repointed` (list of table/row/column), author, note, `undone_at`. |

### 4.4 Derived fields (rules)

Derived values are stored in a `derived` table (one row per project or service). They are recomputed in the same transaction as any change to the subject's events, and in bulk with `mdt recompute`. They are never editable, are not part of curated revisions, are exported with a `derived_` prefix, and are explained in the codebook. Cut-off dates: **MINISTRY = 2019-08-29**, **INVASION = 2022-02-24**. Events marked `disputed` are ignored. This section summarises the rules; the binding algorithm is `docs/DATA_MODEL.md` §8.3.

1. **`launch`:** the candidates are the dated `launch` events, or, if there are none, the dated `beta_launch` events. The **launch interval** [s, e] = [earliest start, earliest end] over the candidates decides period and trajectory; the displayed launch is the candidate with the earliest end, shown with precision, basis and event ID, e.g. "2020-06 (month, stated in source)".
2. **`existed_by`:** the earliest `first_archived` event (`archive_upper_bound`). It is displayed as an upper bound ("≤ 2021-05-14, archive") and **never as a start date**.
3. **`period`:**
   - From the launch interval [s, e]: e < MINISTRY → `pre_ministry`; s ≥ MINISTRY and e < INVASION → `pre_invasion`; s ≥ INVASION → `full_scale_war`; an interval that straddles a cut-off → `unknown` (reason `imprecise_date`). Example: a launch known only as "2022" cannot be assigned.
   - Without a launch, using only the archive bound u: u < MINISTRY → `pre_ministry` (certain, because the launch is ≤ u); otherwise `unknown` (reason `archive_bound_only`). The fact that the item existed before the invasion is still recorded (`existed_before_invasion = true` when u < INVASION).
   - No date at all → `unknown` (reason `no_date`).
4. **`war_trajectory`** (rules applied in this order):
   - `unknown` (reason `conflicting_dates`): launch s ≥ INVASION, but the item existed before the invasion (archive bound u < INVASION).
   - `new_in_war`: launch s ≥ INVASION.
   - `adapted_in_war`: existed before the invasion (launch e < INVASION, **or archive bound u < INVASION**) and at least one modification event with s ≥ INVASION.
   - `prewar_unchanged`: existed before the invasion and every modification event is dated with e < INVASION (or there is none).
   - `unknown`: anything else, with a reason: an undated or straddling modification event (`imprecise_modification_date`), a launch interval that straddles the invasion (`imprecise_date`), only an archive bound on or after the invasion (`archive_bound_only`), or no date (`no_date`).
   - "Modification" means event types with `counts_as_modification = true` in the codebook. Draft: expansion, major_update, rebrand, governance_change, suspension (decision D-2 in §12).
   - **Logic worth noting for the paper:** an archive capture *before* the invasion is enough to prove pre-war existence, but a capture *after* it never proves that something is new. `prewar_unchanged` means "no modification recorded in the sources up to release X"; it reflects absence of evidence.
5. **`portfolio_entry`** (➕ proposed): the earliest start of a Participation of the focal organisation (the ministry) in the roles initiator, owner or operator. It separates **the launch of an initiative** from **its entry into the ministry's portfolio**. Example from the Phase 0 leads: a government decision transfers the Innovation Development Fund "into the management of the ministry" [search]. According to the search summary, this fund is the legal entity behind the Ukrainian Startup Fund [search-summary]. If confirmed, USF's wartime event is a governance change rather than a launch. `war_trajectory` can be computed on either basis; the default (launch) and the alternative (portfolio entry) are decision D-10.

### 4.5 Adaptation vs. new development (Yoo et al. 2012)

The distinction is visible on three layers that complement each other:

1. **Coded:** `development_mode` (new_development / adaptation_of_existing / unclear) with rationale and evidence, on Project and Service.
2. **Structural:** Relations `extends`, `builds_on`, `successor_of` and `recombines` link to the existing service or component that was adapted or combined (D2/D4).
3. **Temporal, derived:** `war_trajectory` from launch and modification events.

The dashboard cross-tabulates `development_mode × war_trajectory`. Contradictions are flagged as data-quality hints (not errors), for example `adaptation_of_existing` without any extends/builds_on/successor_of relation.

### 4.6 Deviations from the proposed model

1. `ministry_category` becomes **`ministry_categories[]`**, because of observed double listings (Diia.City).
2. `first_seen`/`last_seen` are **derived from per-source observations**: an item can disappear from one source and stay in another, and the "possibly discontinued" logic needs per-source state.
3. **Date intervals** plus verbatim `date_text` replace a single date. Period assignment then stays honest under imprecision, and the original date string is preserved.
4. **DocumentText** is separate and content-addressed: small revisions and auditable text versions.
5. **`development_mode`** makes the Yoo distinction explicit instead of leaving it implicit in events.
6. Field provenance is split into **`src` (where the value comes from)** and **`by` (who set it)**, plus a `locked` flag. A collector value that a person accepted stays traceable to its snapshot and is still protected from automatic overwrites.
7. **Proposal deduplication and rejection memory:** repeated runs stay idempotent, and a rejected value is not proposed again.
8. **Derived values in their own table:** never edited, reproducible, clearly marked.
9. An event subject can also be a **Component** or an **Organization** (institutional context events such as leadership or mandate changes).
10. **Evidence** can point to a document location (character offsets in one specific text version) or to a bare URL or archive URL.
11. **Screening reason codes** (vocabulary) in addition to free text, so the paper can report a PRISMA-style screening flow (collected → screened → included, with exclusion reasons).
12. A seeded **focal organisation** (the ministry, name only) and the derived **`portfolio_entry`**: launch ≠ entry into the ministry's portfolio.
13. **`unit_type`** on Project (D-11): separates digital products from platforms, programmes, strategies or policy areas and organisations that are all listed as "projects".

### 4.7 Full-text search and Ukrainian text [local]

A probe on SQLite 3.45.1 (2026-10-28) gave the following results:

- The `unicode61` tokenizer folds Cyrillic case (`ДІЯ` = `дія`). `remove_diacritics` does **not** touch й/ї (no false merges such as й→и).
- **Apostrophe variants tokenize differently:** with `’` (U+2019) or `'`, the word `з’явилася` is split into `з` + `явилася`; with `ʼ` (U+02BC) it stays one token. All apostrophe variants (`'`, `’`, `ʼ`, `` ` ``, `´`) are therefore normalised to U+02BC before indexing and in queries. Other normalisations: NFC, non-breaking spaces, soft hyphens, dash variants.
- **No stemming:** `Дія` does not match `Дії`. Prefix queries (`Ді*`) catch inflected forms but over-match. The UI offers prefix search; auto-tagging uses curated alias forms (§5.3).
- **Homonymy:** `дія` also means "action/effect" (the test sentence "Дія закону…" matched). Brand aliases are therefore matched case-sensitively, longest match first (`Дія.Бізнес` before `Дія`), and only ever as *suggested* tags.
- **Decision:** FTS5 with `unicode61` plus prefix indexes for entities and document texts, with highlighting via `highlight()`/`snippet()`. The trigram tokenizer (substring search, but a much larger index) is not needed for now.

---

## 5. Data acquisition

> **Phase 2 contract (2026-10-30, revised the same day after a four-lens review):** [`docs/COLLECTORS.md`](docs/COLLECTORS.md) (framework, collectors, importer, manual documents) and `docs/DATA_MODEL.md` §14–§18 (tables, reconciliation, proposals, imports, merging) are binding and supersede the details below, which remain the rationale. The main changes: a collector run executes in a thread of the server process or in the CLI, one run at a time in the whole database, without subprocesses, a queue, resumable checkpoints, collector dry runs or a scheduler (schedules are Phase 4); the client is built on httpx2 with protego for robots.txt, HTML is parsed with BeautifulSoup and the built-in `html.parser`, PDFs with pypdf (trafilatura, lxml and python-docx are not used); every collected value names the raw snapshot it was parsed from (`field_meta.raw_snapshot_ids`); records a person verified are never changed by collectors, only proposed for; C1 fetches no rubric listings, never writes project names and proposes the official domains linked from project pages; C2 covers the projects' official URLs, and codeua.com is out of scope (data lead, 2026-10-30 [user]); the cross-check collectors C2a and C3b move to Phase 3 (D-12 open); C5 is specified against the CDX documentation with synthetic fixtures until `mdt fixtures capture wayback` records real ones on the server, and yields `first_archived` events (directly for a subject's own project or service page, as proposals for other URLs such as domain roots); the automatic Wayback fallback inside collectors is replaced by archived copies added by hand ("Add document → From URL"), and the catalogue reconstruction at cut-off dates moves to Phase 3; C6 is replaced until Phase 3 by the ministry's legislation documents plus act links kept as references (SOURCES S6); C7 and the pymorphy3 suggestions move to Phase 3; `link_document` proposals are replaced by suggested document links, and unknown vocabulary codes give warnings instead of term proposals (DATA_MODEL §15.8, §15.10).

### 5.1 Pipeline and shared components

- **`sources.yaml`**: one entry per source: id, name, base URLs and hosts, collector module, minimum interval per host, robots policy, licence (default plus URL of the licence statement), schedule, enabled flag.
- **`PoliteHttpClient`**:
  - throttling per host (default 1.0 s between requests; more for the Wayback Machine, §5.2 C5); robots.txt fetched once per run and obeyed;
  - User-Agent `MDT-Portfolio-Research/<version> (+<repo URL>; mailto:<CONTACT_EMAIL>)`;
  - conditional GET (`If-None-Match`, `If-Modified-Since`); timeouts; size limit;
  - retries with exponential backoff and jitter for 429/5xx, honouring `Retry-After`;
  - **block detection:** a burst of 403/429 responses or a challenge page stops the source for this run, marks the run `partial`, logs the event and reports it in the UI. It falls back to the Wayback Machine only where that fallback is configured. No CAPTCHA solving, no proxy rotation, no faked browsers.
- **RawSnapshot store**: unchanged bytes, gzip, content-addressed, deduplicated. A parse is skipped when the snapshot hash has not changed.
- **Parsers** are pure functions (snapshot → candidates), unit-tested against fixtures.
- **Reconciler**: rules in §6.5.

### 5.2 Collector catalogue

<!-- COLLECTORS:BEGIN -->
Phase 0b (2026-10-29) settled the access path of every collector except C5 and C6, whose hosts this environment cannot reach; evidence and details are in `docs/SOURCES.md`, offline fixtures in `backend/tests/fixtures/<collector>/` (§5.7). Structured access comes first (data embedded in the page, sitemaps, JSON files, feeds); HTML parsing is the fallback. **[server]** marks what still has to be checked from the target server.

**C1 `ministry_projects`** (S1)
- **Access:** no API; every page embeds its complete loader data as a React Router turbo-stream (`streamController.enqueue("…")`). Decode it and read `loaderData["projects.list" | "projects.list.page" | "projects.view"]`; DOM fallback (card links, `h1`, footer) if the payload is missing; `<path>.data` (same data, no nonce) only as a fallback because it is an internal framework endpoint.
- **Per run (about 28 requests at 1 request/s):** `/projects` and `/projects/page/<n>` up to `pagination.lastPage`; all 12 rubric listings `/projects/<rubric>` (rubrics with only news are cheap to skip later, but `additionalRubrics` can list entries anywhere, e.g. `how-tos`); one detail page per `type = content` entry (14 on 2026-10-29). The ministry URL of a `type = link` entry is not fetched (the one requested in Phase 0b, WINWIN, answered 302 to its `externalUrl`, which the listing already carries).
- **Per entry:** title (uk; there is no English version), primary rubric (slug + Ukrainian label), additional rubrics, caption, `externalUrl` or the project page; from the page `project.id` (UUID), tags and outbound links from `blocks` (to the C2, C4 and C6 queues).
- **Observations** are stored per (entry, rubric listing), so additional rubrics appear as extra observations; on 2026-10-29 Diia.City had a single rubric, and `/projects/regions/city` is the same record as `/projects/business/city`.
- **Matching:** `project.id` first, then the slug from the data (never the request URL or `<link rel=canonical>`, which echoes any accepted path), then aliases; record final URL and redirect chain; URL variants (`/projects/yevrointegraciya` → 302, legacy `/projects/<slug>`) are kept as aliases. New or missing entries become **proposals**; projects are never created automatically.
- **Dates:** projects carry none, so C1 yields only first/last-seen observations; launch dates come from C4/C4b and archive upper bounds from C5.
- **Idempotency:** no ETag or Last-Modified and a fresh CSP nonce per response, so hash the canonical decoded data without volatile parts (`publishedAt.related`, image `?v=` parameters, nonces).

**C2 `project_sites`** (S2), generic plus specialised
- **Generic, for every project's ministry page and official domain:** title, meta and OpenGraph tags, JSON-LD (e.g. UNITED24 Media's `NewsMediaOrganization` with founder and founding date), main text (about page), footer statements on operator, owner and licence (stored verbatim), outbound links, and a `sitemap.xml` inventory (counts only, no full crawl). Sites rendered only in the browser (winwin.gov.ua: 68 visible characters, no data API) are flagged "no server-rendered content" instead of yielding an empty description.
- **Client rules from Phase 0b:** never follow `/cdn-cgi/…` or hidden `rel=nofollow` links (Cloudflare traps), detect soft 404s by content (usf.com.ua, u24.gov.ua), treat a challenge or edge 403 on robots.txt as a block (codeua.com: Cloudflare managed challenge). codeua.com is out of scope since 2026-10-30 ("Ist unwichtig, wird nicht gebraucht" [user]): no collector requests it; CodeUA stays a seed project.
- **Outbound links feed other collectors:** legal acts go to the C6 queue; PDFs on `storage.thedigital.gov.ua` and `cms.thedigital.gov.ua` go to C4 with metadata from the linking page; partner organisations become D3 proposals later.
- **Domain verification:** an official domain must be linked from the ministry page or from a gov.ua page, or the other way round. The chain of links is stored as evidence. Resolved in Phase 0b: brave1.gov.ua, mriia.gov.ua/app, www.cdto-campus.com/ua/, hromada.gov.ua, e-resident.diia.gov.ua, city.diia.gov.ua, plus the six `externalUrl` domains; Дія.Engine and Віртуальні активи link no own domain, and playcity.gov.ua is not linked from the ministry's PlayCity page (`docs/SOURCES.md` S2).
- **Specialised collectors decided in Phase 0b:**
  - **C2a `digitalstate_catalog`** (C-1; deferred beyond Phase 3, D-12, `docs/COLLECTORS.md` §14): 3 listing pages in English and 3 in Ukrainian plus 17 detail pages per run; the same turbo-stream decoder as C1 (Remix v2); key `project.id`; observations only (no dates); all rights reserved, so releases carry metadata only.
  - **(d) UNITED24:** harvest the weekly report PDF links on the server-rendered home page (`files.u24.gov.ua/reports/<yyyy>/<month>/<dd>/report-<yyyymmdd>-<area>.pdf`, the path date is the report date) as report documents; the JSON API behind the running total was not identified (one browser check from the server if needed).
  - **(f) centres:** take the list of centres from the guide's CNAP register (C3b) instead of center.diia.gov.ua, whose map is a Tableau embed.
  - **(b) Diia.Education** (optional): sitemap (254 courses) plus the page's `__NUXT_DATA__`; robots.txt with RFC 9309 semantics; no use of the key-based API.
  - Not needed: USF programmes (free text; the generic pass suffices). Not checked: (c) Diia.Business programmes and (e) Brave1 grants and challenges **[server]**.

**C3 `diia_catalog`** (S3)
- **Access:** server-rendered OctoberCMS HTML, no API, no embedded data (browser check: only a csrf-token XHR). Cloudflare in front: stop the run on any challenge page.
- **Discovery:** union of the services sitemap (`sitemap-kitsoftservicesmodelsservice-1.xml`, 171 URLs with lastmod) and the alphabetical list on `/services` (172 entries; adds `/services/RD4U`, a redirect page on 2026-10-30 [live], SOURCES S3). Category membership from the 27 subcategory pages `/services/categories/<audience>/<subcategory>` (audience pages list no services). About 200 requests per full run (about 3.5 min at 1 request/s); no pagination.
- **Output:** Services under project `diia` (created as unverified), with source categories (audience + subcategory), URL, name (`h1`; the meta title can differ), description, duration and cost pairs, channel hints (`Онлайн`/`Офлайн`), related services, legal acts (zakon.rada.gov.ua links, to the C6 queue) and the my.diia task ID where present; observations per service and per (service, subcategory).
- **Dates:** service pages carry none; sitemap `lastmod` is an observation only (creation vs update unknown), never a launch date.
- **Normalisation:** strip a trailing dot from the host (the dotted variant got no answer from the development environment); keep slug case; match section headings on normalised text ("та"/"й", ’/ʼ).
- **Open:** the 43 Register-of-Damage claim categories listed as services (codebook decision, D-6).
- **App-only services** enter as proposals derived from announcements (C4).

**C3b `diia_guide`** (C-2; decided in Phase 0b; deferred beyond Phase 3, D-12, `docs/COLLECTORS.md` §14)
- **Access:** one conditional GET per run of `https://guide.diia.gov.ua/register/download/json/` (18.5 MB, ETag and Last-Modified, CC BY 4.0), kept as a raw snapshot; the guide keeps no history, so history starts with our own snapshots.
- **Per entry:** key `identifier` (5 digits), thematic area, sector, events, level, applicant types, providers and application ways (channel normalisation table for at least 6 spellings of the Diia channels), `access_link` (maps 46 portal services), `moderation_status` ("Архівна" becomes a "possibly discontinued" proposal). `created_at` dates the register record, not the service.
- **Card pages** only when evidence links are needed (the guide's sitemap answered HTTP 500; card URLs come from `/register/<identifier>/<slug>-<uuid>` links). Never touch `/search/?q=` or `/api/schema/swagger` (robots.txt).
- **Optional:** the CNAP register `/asc/download/json/` (5853 records) for a centres indicator after human review (every record says "Діючий").

**C3c `plan2.diia.gov.ua`** (C-3): no collector, because the project list (`https://plan2-backend.diia.gov.ua/api/front/project`, 94 projects of February-June 2021) has no status, progress or deadline fields. Capture it once as a dated document (C8) as a pre-invasion baseline; whether its projects also become "planned project" records through the importer is a team decision (`docs/SOURCES.md` §5).

**C4 `ministry_news`** (+ documents and ministry pages) and **C4b `kmu_news`** (S4, S4b)
- **thedigital.gov.ua (C4):**
  - *News:* `/news` and `/news/page/<n>` (12 per page, 366 pages and 4385 items on 2026-10-29, back to 2019-10-07); incremental runs stop at the first page whose items are all known. Decode the embedded turbo-stream (`news.list`, `news.list.page`, `news.view`); key `article.id` (UUID); the publication date is `publishedAt.iso8601` (Europe/Kyiv offset; machine-readable on every item, so year-less display dates need no inference); full text from `lead` + `blocks` (TipTap JSON; outbound links from `link` marks); rubric memberships from `rubric` + `additionalRubrics`. Old `/news/<slug>` URLs answer 302 to `/news/<rubric>/<slug>` and are kept as aliases. A full backfill is about 366 listing + 4385 article requests (3-5 h at the observed latency).
  - *Language:* `translations` says `uk` even for English articles, so detect the language deterministically from the text (no LLM).
  - *Documents:* `/documents/page/<n>` (106 pages, 1267 documents); the listing gives all metadata for `file` and `link` items, detail pages only for `type = content` (attachments as `link` marks). The type is `kind` (36 values), never the constant "Розпорядження від …" label. The site's `publishedAt` is stored as a site record date, never as the document date (act dates on `link` items, bulk timestamps 2025-03-18 and 2025-06-02 on migrated items); document dates and numbers come from the title or the file. `zakon0/3/5.rada.gov.ua` links are normalised for C6.
  - *`/ministry`:* snapshot every run (team members with positions; 33 related documents incl. work plans 2020, 2021, 2023 and 2024 and reports 2020, 2021, 2022 and 2023).
  - *Files:* `storage.thedigital.gov.ua`, discovered via links only; the file name is the MD5 of the content (integrity check, dedup), conditional GET with the ETag. `cms.thedigital.gov.ua` (older uploads) does not exist according to the data lead's local check of 2026-10-30 [user]; its links stay references.
  - *Microsites* (`2years.`, `5years.`, `2025.thedigital.gov.ua`): one document each (doc_type `report`); their Last-Modified header is a file time, not a publication date.
  - *Idempotency:* hash the decoded data without `publishedAt.related` (relative time), image `?v=` parameters and nonces.
- **kmu.gov.ua (C4b):**
  - *Discovery:* the UA news sitemaps (`sitemap-rainlab-blog-models-post-{1,2,3}.xml`; files 1 and 2, 11.4 and 9.5 MB, cover 2016-01-08 to 2026-10-28 with a lastmod on every entry; file 3 was not fetched) and the EN sitemap (5.9 MB), one GET each per run (no ETag or Last-Modified, so no conditional GET; diff the URL sets). There is no per-ministry listing, tag or filter, and `/timeline`, `/api/`, `/npas/` and `/storage/` are robots-disallowed (the client re-checks robots.txt on every redirect hop: `/news` redirects to `/timeline`).
  - *Candidates:* slug keywords in **both transliteration styles** (old style until 2022-12: `mincifr`, `cifrovoyi-transformaciyi`, `ministerstv…-cifrov…`; new style from 2022-07: `mintsyfr`, `tsyfrovoi-transformatsii`; plus `fedorov` and `diia`/`diya` tokens) within the date window; lastmod only selects the window. Slug filtering only *discovers* candidates; the publishing body in `div.page_title-desc` and the alias tagger on the content decide relevance, and the discovery path is recorded for the methods section. The recall of the slug filter is unknown (decision in `docs/SOURCES.md` §5: recall sample or one complete pass over the 18,793 UA items of 2019-09-01 to 2022-02-23).
  - *Parsing:* one parser for all years: `h1`, `div.page_title-desc` (body + date "опубліковано DD <month> YYYY року о HH:MM" / "posted D Month YYYY HH:MM", Kyiv local time, stored verbatim in `date_text`), `ul.wcag-tags`, `div.editor-content`; the EN version has the same slug under `/en/news/`.
  - *Snapshots:* normalise CSP nonces, the csrf token and the inline bot-manager script before hashing; strip the bot-manager token (it encodes the client's IP address) from anything exported. Stop on any challenge page (a bot manager is present).
- **Content:** full texts from the embedded data (C4) or the page selectors (C4b), PDFs via pdfminer.six (the PDFs checked have text layers). Output: Documents (unverified, unscreened), suggested project links, event proposals, links to legal acts.
- **Priority:** reports and year-in-review items (doc_type `report`) go first: the plans and reports linked from `/ministry`, the microsites, the 2025 year-in-review on kmu.gov.ua.
- **Duplicates** between thedigital.gov.ua and kmu.gov.ua are detected by content (§5.6; fixture pair: the same 2019 item at 13:21 and 17:48 with different slugs); slugs are useless for this because the transliteration differs. thedigital.gov.ua covers ministry news from 2019-10-07; kmu.gov.ua adds 2019-08-29 to 2019-10-06, English versions and cross-checks.
- **New candidate C-5** `ai.thedigital.gov.ua` (AI policy portal with news and documents, list data loaded client-side from `ai-web-api.thedigital.gov.ua`): scope decision first, then one browser check for its endpoints **[server]**.

**C5 `wayback`** (S5): parameters verified in the CDX README [doc]; **not reachable from the development environment** (no TLS answer from web.archive.org; the archive.org availability API answered 429), so everything below is still to be checked **[server]**. The data lead reports that it works locally ("Wayback: Läuft lokal", 2026-10-30 [user]); the Phase 2 contract therefore specifies C5 against the documentation, tests it with synthetic fixtures in the documented format and records the real fixtures with `mdt fixtures capture wayback` on the server (`docs/COLLECTORS.md` §8.5).
- **Earliest and latest capture per URL** in a single prefix query: `matchType=prefix&collapse=urlkey&showSkipCount=true&lastSkipTimestamp=true&output=json&fl=urlkey,timestamp,original,statuscode,mimetype`. The index is "usually sorted by url and date" [doc], so the first row per `urlkey` is the earliest capture; `lastSkipTimestamp` adds the last one. The skip counters are marked "experimental" in the docs, so this is checked first, with `limit=-1`/`fastLatest=true` as the fallback for single URLs.
- **Prefixes:** `diia.gov.ua/services/` (and the trailing-dot host), `thedigital.gov.ua/projects/` (covers the pre-relaunch scheme `/projects/<slug>` and the current `/projects/<rubric>/<slug>`), `thedigital.gov.ua/news/` (old `/news/<slug>` and current `/news/<rubric>/<slug>`), and kmu.gov.ua news filtered with `filter=original:<regex>`. Large results are split with `showResumeKey=true`/`resumeKey`. Paths that the live site disallows in robots.txt (kmu.gov.ua `/npas/`, `/storage/`) are not read from the archive either (proposed default, `docs/SOURCES.md` §5).
- **URL normalisation:** scheme, `www`, trailing slash and dot, query, case, percent-encoding; renamed slugs need a curated alias table (e.g. the 2021 microsite links `/projects/e-residency`, which answers 404 today).
- **Outputs:**
  - one `first_archived` event per subject (the earliest capture across URL variants, `date_basis = archive_upper_bound`, evidence = capture URL);
  - **the catalogue reconstructed at cut-off dates** (31 Dec of each year 2019–2025, plus 2022-02-23) from the nearest earlier capture (`/web/<timestamp>id_/<url>` returns the original bytes), parsed by layout-specific parsers;
  - documents that are gone from the live site (`via = wayback:<timestamp>`).
- **Throttling:** default 1 request per 5 s; long backoff on 429/503; CDX responses stored as snapshots. If the server's IP is throttled too, Wayback counts as unavailable for the run (not as "no captures").
- **Save Page Now:** optional and opt-in, only for new evidence, rate-limited.

**C6 `legal_acts`** (S6)
- **Scope:** only acts linked from collected pages (ministry pages and documents, news, Diia service pages and guide cards, PlayCity's legal-basis page). www.kmu.gov.ua cannot serve as an act source: `/npas/` is robots-disallowed, so its act links are references only and their slug suffixes are never used as dates.
- **IDs normalised** (`/go/<id>` ↔ `/laws/show/<id>`; `zakon0/3/5.rada.gov.ua` → `zakon.rada.gov.ua`).
- **Captured per act:** title, number, date, type, edition date, text. Stored as doc_type `legal_act`.
- **Events:** proposals for `legal_basis_adopted` / `governance_change`.
- **Open:** zakon.rada.gov.ua and data.rada.gov.ua did not answer from the development environment; according to the data lead's local check, these subdomains do not exist, while rada.gov.ua does (2026-10-30 [user]). Until C6 is decided in Phase 3 (after one DNS and robots.txt check from the target server), the alternative of SOURCES S6 applies: the ministry's legislation documents (`/documents/legislation`, collected by C4) are the legal-act corpus, and act links stay references.

**C7 `telegram`, `ckan`** (S7, optional)
- **Telegram:** web preview `https://t.me/s/mintsyfra`, following `<link rel="prev">` (`?before=<id>`) down to the oldest posts (ID 9, 2019-09-27); incremental runs stop at the newest known ID. robots.txt answers 404 (allow all). Each post becomes a document (doc_type `announcement`) keyed by its ID, dated by its machine-readable `<time datetime>` (UTC; stored as a Europe/Kyiv calendar date with the timestamp verbatim) [0b]; view counts and the per-render `data-view` attribute are excluded from change detection. Several hundred pages for a full backfill.
- **CKAN (data.gov.ua):** the CKAN action API is robots-disallowed, so the inventory comes from the Atom feed `/feeds/organization/mincyfry.atom` (or the HTML listing) and the metadata from DCAT per dataset (`/dataset/<id>.jsonld`); the licence comes from the listing facet or the dataset page (DCAT has none). Minimum interval 10 s per robots.txt `Crawl-delay`. Datasets of `mincyfry` (30, `cc-by`) → Documents (statistics); figures become Indicators only after human review. Feeds and DCAT carry personal contact data: keep it out of exports. The Diia guide register is not on data.gov.ua; it comes from C3b.

**C8 `manual`**
- **By URL:** fetched with the polite client, so a snapshot exists. (The SSRF filter planned here is dropped: D-15.)
- **By upload:** PDF/DOCX/HTML/TXT, offered back as downloads (e.g. the KIIS/UNDP report if www.undp.org stays blocked).
- Provenance `manual`.
<!-- COLLECTORS:END -->

### 5.3 Matching and auto-tagging

- **Aliases per project and service** are curated in the UI. When a single-word Ukrainian alias is added, `pymorphy3` suggests its inflected forms (e.g. nominative, genitive, accusative, instrumental); a person confirms them and they are stored explicitly. Matching itself is plain and deterministic (compiled patterns with word boundaries, after the text normalisation of §4.7).
- **Compound brand names** (`Дія.City`, `Дія.Бізнес`, `Дія.Освіта`, spellings with a space or dot, Latin/Cyrillic variants) are separate aliases. Overlapping matches are resolved **longest match first**, so a mention of `Дія.Бізнес` is not also counted as `Дія`.
- **Homonyms:** case-sensitive aliases and per-alias `exclude_patterns` (e.g. phrases in which `дія` means "action").
- **Output:** a `DocumentLink` with `origin = auto`, `state = suggested`, the matched aliases, a match count and a snippet. In the document view a person confirms or rejects it in one click. Only confirmed links count in analyses; suggested links count only in an explicitly labelled "auto" view.
- **Phase 2 contract:** matching rules in `docs/COLLECTORS.md` §7.6, link rules in `docs/DATA_MODEL.md` §15.8. The `pymorphy3` suggestions move to Phase 3; until then a person enters inflected forms as aliases (`kind: inflection`).

### 5.4 Event proposals from texts

Phrases such as `запустили`, `запустило`, `запрацювала`, `запрацював`, `з'явилася послуга`, `стартувала`, `оновили`, `розширили`, `перейменували` and English equivalents (`launched`, `now available`, …) near an alias match produce **`create_event` proposals**, never facts. Each proposal carries the guessed subject, the guessed event type, the document date as `date_basis = inferred` (the announcement date is not automatically the event date), the quote and the document. A person edits and accepts it, or rejects it. The pattern list lives in the codebook (versioned) so the procedure can be reported in the methods section. Phase 2 contract: `codebook/event_patterns.yaml`, `docs/COLLECTORS.md` §7.7, `docs/DATA_MODEL.md` §16.1.

### 5.5 Dates

- **Order of preference for machine-readable dates:** API fields → `<time datetime>` → JSON-LD `datePublished` → `article:published_time` / other meta tags → URL or ID schemes (only if verified) → visible text. Sitemap `lastmod` is **not** a publication date.
- **Never guess.** A date without a year (e.g. `22 жов., 14:00` [user]) is stored verbatim in `date_text`, with no `date_start`, until a reliable source supplies the year: the same item from a machine-readable endpoint, an archived capture of a listing that shows the year, or kmu.gov.ua. Any inference rule (e.g. "the year is omitted only for the current year", combined with the capture date of an archived listing) is used only after the site convention has been verified, is marked `date_basis = inferred` and is documented.
- Ukrainian month names in all forms (`жовтня`, `жов.`, `жовтень`) are parsed by a tested helper; ambiguous input is rejected.

### 5.6 Idempotency, incremental runs, resumability

- **Stable keys:** canonical URLs and external IDs; entity IDs are never regenerated.
- **Incremental:** conditional requests; unchanged snapshots skip parsing; unchanged values create **no revision and no version bump**.
- **Duplicates:** canonical URLs plus content hash. Cross-site duplicates (the same press release on thedigital.gov.ua and kmu.gov.ua) are detected by normalised title, date ± 1 day and text similarity. They become a `possible_duplicate` proposal; both documents are kept, and the team decides whether to merge them or link them as duplicates.
- **Acceptance test (Definition of Done 3):** running a collector twice against the same fixtures yields 0 new entities, 0 new revisions and 0 new proposals on the second run (`docs/COLLECTORS.md` §12.1; the rules behind it: `docs/DATA_MODEL.md` §15.6).

### 5.7 Fixtures

- Tests run **without network** against fixtures in `backend/tests/fixtures/<collector>/`; the format and the capture rules are described in `backend/tests/fixtures/README.md` and checked by `backend/tests/test_fixtures.py`.
- **Format (implemented in Phase 0b):** per fixture a body file `<name>.<ext>` (the original bytes, or a minimal excerpt) and `<name>.meta.json` with `url`, `final_url`, `redirects`, `status`, `retrieved_at`, `content_type`, a subset of the response `headers`, `sha256_original` and `bytes_original` of the capture, `sha256_stored` and `bytes_stored` of the body file, `trimmed` (bool), `trim_note` (what was kept, removed or redacted), `licence` (as quoted from the source), `attribution`, `source`, `collector`, `purpose` and `capture`. Meta files carry no User-Agent and no `mailto:` address (the fetcher's User-Agent contained the contact e-mail); no body may exceed 1 MiB; `.gitattributes` disables line-ending conversion so the hashes stay valid.
- **Phase 0b set (2026-10-29):** 103 fixtures in 12 directories (`ministry_projects`, `project_sites`, `digitalstate_catalog`, `diia_catalog`, `diia_guide`, `plan2`, `ministry_news`, `kmu_news`, `wayback`, `telegram`, `ckan`, `polite_client`), about 3 MB. Missing because the hosts are not reachable from the development environment: Wayback CDX responses and `id_` captures (C5) and legal acts (C6); they are captured **from the target server**.
- **Licences:** fixtures from CC BY sources keep their original bytes and are attributed; changes (excerpts for size or privacy, redactions) are stated in `attribution`. Pages from other sources are kept as minimal excerpts (only the structure a parser needs; long texts shortened). Personal data and per-request tokens (e.g. a bot-manager token that encodes the client's IP address) are removed in every case.
- **Recording later fixtures:** `mdt fixtures capture <source>` (Phase 2, `docs/COLLECTORS.md` §11): a small, fixed list of URLs from `sources.yaml`, fetched politely, written in the same format; run once on the target server for C5, with the result committed. Until then C5 is tested with clearly labelled synthetic fixtures in the documented CDX format (`docs/COLLECTORS.md` §8.5). C6 fixtures wait for the Phase 3 decision on C6.
- Fixtures are test input, not data: nothing from them enters the seed, the codebook or the database.

---

## 6. Versioning, provenance and reconciliation

### 6.1 Revisions

- **All writes go through one domain function:** `apply_change(entity, changes, actor, channel, note)`. It validates, computes the diff against the current state, and does nothing if the diff is empty. Otherwise it bumps `version` and writes the entity and the revision (full snapshot plus field-wise diff) **in one transaction**, then recomputes derived values if needed.
- **Append-only:** SQLite triggers abort every `UPDATE` and `DELETE` on `revision`.
- **Covered:** all curated entities, vocabulary terms, relations, participations, evidence, comment edits, document screening and tags, saved views.
- **Restore** a version = `apply_change` with that version's snapshot, `channel = restore`, `restored_from = <revision>`. This creates a new revision; history is never rewritten.
- **Diff between any two versions** is computed from their snapshots, field by field; long texts get word-level diffs in the UI.
- **Recent changes:** a global feed over `revision`, filterable by entity type, channel and period (no author filter: D-15).

### 6.2 Field provenance

`field_meta[<field>] = {src, by, at, locked, evidence_id?, verified}`

- `src`: `seed` | `collector:<name>@<run_id>` | `manual` | `import:<file>`. A restore keeps the original `src`.
- `by`: who wrote the value (`user` for the app's single user, D-15; otherwise `seed`, `import:<file>` or `collector:<name>`).
- `locked`: becomes `true` as soon as a person sets, accepts, imports, restores or seeds the value. From then on collectors can only propose.
- `verified`: unverified / verified / disputed per field. Clicking the badge creates a revision.
- **UI:** a badge per field (`seed`, `collector`, `manual`, `import`) plus a lock icon and a verification dot; the tooltip shows the run, snapshot or evidence and the time.

### 6.3 Optimistic locking and the conflict dialog (superseded by D-15)

Superseded by decision D-15 (§12): the app has one user, so saves send no base version, there is no 409 conflict and no conflict dialog, and bulk edits send only the record IDs. Writes are serialised by SQLite's write lock, `version` only numbers a record's revisions, and every change stays in the history (`docs/DATA_MODEL.md` §6.5).

### 6.4 Soft delete, trash, merge

- **Delete** sets `deleted_at` and creates a revision. Deleted entities are hidden by default; a trash view per type allows restoring them.
- **Dependent entities:** deleting a project with services asks whether to soft-delete them too (shared `batch_id`) or leave them in place, flagged as orphans.
- **Merging duplicates:** choose the survivor and pick values field by field. All references (services, events, evidence, links, participations, relations, comments, observations) are repointed, each with its own revision. A MergeLog entry makes the merge reversible. Phase 2 contract: `docs/DATA_MODEL.md` §18 (projects and services; the references held in editable fields and document links are repointed, evidence and comments stay on the merged record, observations follow `merged_into`; one transaction; refused on conflicts; an unmerge action reverses it; organisations and components follow in Phase 3).
- **Hard purge:** only via `mdt purge` with explicit confirmation, e.g. for legal takedowns. It is documented, and it is the only path that can remove revisions.

### 6.5 Reconciliation rules for collectors

| Entity | New in source | Unlocked field changed | Locked field changed | Missing from a *complete* listing |
|---|---|---|---|---|
| Project | proposal `create_entity` (projects are never created automatically) | direct update (revision by the collector) | proposal `update_field` | proposal `possibly_discontinued` after 2 consecutive complete runs |
| Service | created as `unverified` (appears in the review inbox) | direct update | proposal | proposal `possibly_discontinued` (same rule) |
| Document | created as `unverified`, `unscreened` | new text version | proposal | observation marked "removed from source"; no proposal |
| Event | always a proposal; only `first_archived` (a mechanical archive fact) is created directly as `unverified` | n/a | n/a | n/a |
| Document link | created as `suggested` | n/a | n/a | n/a |
| Organization / Participation / Relation | proposals only | n/a | n/a | n/a |

Partial or failed runs **never** trigger the disappearance logic. `last_seen` keeps the last successful observation; nothing is deleted.

**Phase 2 contract:** `docs/DATA_MODEL.md` §15 (the field decision table, records a person verified count as locked, add-only URL lists, collectors never clear a value, a person's deletion is never undone, observations as the binding between source keys and records, one candidate per record and run). It refines the sentence above: the disappearance step needs a run that parsed the collector's complete listing, whatever its end status, so a failed detail page does not prevent it, while a failed listing page does. Organisations, participations and relations get no proposals in Phase 2 (Phase 3).

### 6.6 Proposal lifecycle

- `dedup_key = hash(kind, subject, field, normalised proposed value)`. An identical open proposal is not duplicated (only `last_run` is updated). A **rejected** proposal with the same key is not opened again; a different new value opens a new proposal.
- When the source value changes again, older open proposals for the same field become `superseded`.
- **Accept** applies the value (keeps the collector `src`, sets `by` to `user` and `locked = true`). **Edit & accept** stores `manual` with a reference to the proposal. **Reject** requires a short reason. Bulk actions are available.
- **Phase 2 contract:** `docs/DATA_MODEL.md` §16: kinds `create_entity`, `update_field`, `create_event`, `possible_duplicate`, `possibly_discontinued` (`link_document` is replaced by suggested links); states `open`, `accepted`, `accepted_modified`, `rejected`, `superseded`; the dedup key includes the collector (except for event and duplicate proposals); accepting writes on channel `ui` with `revision.proposal_id`; observed values keep the collector `src` and their snapshots, edited values and suggested interpretations (events, discontinuation, duplicates) are recorded as `manual`; an accepted value is proposed again only after the source changed in between; bulk accept leaves proposals whose field changed meanwhile open.

### 6.7 Releases

- `make release NAME=<name>` runs `mdt release` in the container and writes `releases/<YYYY-MM-DD>_<name>/`:
  - `dataset.json` (nested), `csv/*.csv` (one file per entity), `dataset.xlsx`;
  - `codebook.md` and `codebook/*.yaml`;
  - `field_provenance.csv`;
  - `manifest.json` (counts per entity and status, SHA-256 per file, code commit (image label), Alembic schema revision, included collector runs, creation time);
  - `SHA256SUMS` and a `README.md` with citation guidance.
- On the host, the Makefile then refreshes `docs/CODEBOOK.md` and `codebook/` from the release, checks that no other files are modified, commits (`data: release <name>`) and sets the tag `data-<YYYY-MM-DD>-<name>`. **No push.**
- **Content policy (decision D-5):** releases contain curated data, evidence quotes, vocabularies and provenance. They exclude comments, proposals, raw snapshots and the **full texts** of documents not under an open licence. Full texts are delivered through the internal QDA export instead.
- **No release button that writes to git (recommendation).** The container would need write access to the repository and a git identity, would mix runtime data with the code checkout, could commit a dirty working tree, and the tag would not reliably point to the code that is actually running. Instead the UI offers a **release preview** (a manifest and diff against the last release, without git), lists all finished releases from `releases/` (mounted read-only) with downloads, and shows the exact `make release` command.

### 6.8 Backups

- **Daily** `mdt backup`: SQLite online backup API (safe under WAL) → `data/backups/db/app-<date>.sqlite.gz`, followed by `PRAGMA integrity_check` on the copy. Raw snapshots are immutable and content-addressed, so the backup adds only new files to `data/backups/raw-<date>.tar`.
- Rotation 7 daily / 4 weekly / 6 monthly (configurable). `mdt restore <file>` plus a documented procedure (stop, restore, check, start). An **off-host copy** is strongly recommended and documented; it is not part of the app.

---

## 7. Web app

> **Phase 3 contract (2026-10-31, revised the same day after review):** `docs/UI.md` §9, `docs/API.md` §8 and `docs/DATA_MODEL.md` §19–§24 are binding and supersede the navigation of §7.1, the document view, timeline and dashboard of §7.2 and the exports of §7.4 where they differ. The main changes: the navigation groups its items into the menus "Data" and "Activity", and the dashboard replaces the Overview at `/`; the document view is the default tab of a document's page, with a queue for screening and coding, evidence captured from a text selection with verbatim quotes and code-point offsets into one text version (evidence stays on the version it quotes when a text changes), fields coded and records created from a passage; components, participations, relations, indicators and evidence get tables and create forms on the detail pages; dimension evidence (`dimension:D1` … `D4`, labels and definitions from the paper's Table 1) can carry the team's analysis codes, a vocabulary that starts empty; the timeline is drawn by the app's own deterministic SVG layout (no chart library; PNG from the SVG in the browser) with the period bands, cut-off lines, date intervals shown as bars and the ministry's portfolio periods; the dashboard is composed of generic crosstab, coverage and facet requests that count by period on two bases (launch, the default, and portfolio entry, D-10), each number linking to the table query that reproduces it; exports are built on request: a dataset bundle (the content Phase 4 releases freeze), a QDA corpus and codebook files, each stamped with the data revision.

### 7.1 Navigation

There is no login and no author picker (D-15): the app has one user, and every write through it is recorded as by `user`. (The earlier plan asked "Who are you?" on first visit and sent the name as an `X-Author` header with every write.)

```
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ MDT Portfolio │ Dashboard  Projects  Services  Events  Documents  Organizations  Timeline   │
│               │ Review (n)  Changes  Runs  Codebook  Releases     [ Search everything… ]   │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Wireframes (rough; all names and numbers are placeholders)

**Table (here: services)**: filtering, sorting and pagination are server-side; the filter state lives in the URL.

```
Services (n)                                      [Saved views ▾] [Columns] [Export CSV/XLSX ▾] [+ New]
Quick: [Unverified n] [Open comments n] [No start date n] [In paper scope] [Period ▾] [Trash]
┌──┬──────────────────┬──────────────┬─────────────┬──────────────┬───────────────┬────────────┬───┬───┐
│☐ │ Name ▲1          │ Project ▾    │ Kind ▾      │ Channels ▾   │ Launch ▼2     │ Period ▾   │ ✓ │ 💬 │
│  │ [contains…]      │ [Example ×]  │ [3 selected]│ [any of…]    │ [from – to]   │ [multi]    │   │   │
├──┼──────────────────┼──────────────┼─────────────┼──────────────┼───────────────┼────────────┼───┼───┤
│☐ │ Example service A│ Example proj.│ e-service   │ app, portal  │ 2020-06 (m)   │ pre_inv.   │ ○ │ 2 │
│☐ │ Example service B│ Example proj.│ e-document  │ app          │ ≤ 2021-05 (a) │ unknown    │ ● │   │
└──┴──────────────────┴──────────────┴─────────────┴──────────────┴───────────────┴────────────┴───┴───┘
2 selected → [Bulk edit…] [Mark verified] [Move to project…] [Delete]        ‹ 1 2 3 … › 50 per page
(m) = month precision · (a) = archive upper bound · facet menus show counts per value
```

**Detail page (project or service)**

```
← Projects / example-project                                         v14 · unverified ▾ · [History] [Compare]
Example Project · Приклад      [cluster badge] [in paper scope ✓]                [Edit] [⋯ Merge · Delete]
┌ Basics ─────────────────────────────────────────────────────┐ ┌ Comments (2 open) ─────────────┐
│ Name (en)        Example Project       seed 🔒 ● verified    │ │ ▸ field launch_date · open       │
│ Ministry pages   /projects/business/…  collector ○           │ │   └ reply                        │
├ Classification ─────────────────────────────────────────────┤ │ [+ Comment] [on field ▾]         │
│ Policy domains   economic_affairs      manual 🔒 ○           │ └──────────────────────────────────┘
│ Beneficiaries    …                     manual 🔒 ○           │
│ Development mode adaptation_of_existing  [2 evidence]        │
├ Wartime ────────────────────────────────────────────────────┤
│ Relevance        indirect · rationale “…”      [1 evidence]  │
│ Derived ⓘ        launch 2020-06 (m) · period pre_invasion · trajectory adapted_in_war │
├ Framework D1–D4 ────────────────────────────────────────────┤
│ D1 need / affected groups / priority link …   [evidence n]  │
│ D2 platforms … · Relations: builds_on → Example component    │
│ D3 Participations: Example org (developer, 2021–) [evidence] │
│ D4 recombination …                                           │
├ Sources & Evidence ─────────────────────────────────────────┤
│ Services (n) · Events (n, timeline strip) · Documents (n linked / n included) · Indicators (n) │
└─────────────────────────────────────────────────────────────┘
```

**Document view**: the extracted text is shown as plain text; stored HTML is never rendered.

```
┌ Metadata ─────────────────┐┌ Text   [search in text: запустили ] 3 hits ‹ › ─────────────────────┐
│ Title (uk) …              ││ … Мінцифри ⟦запустили⟧ нову послугу …                                │
│ Publisher  example.gov.ua ││ select text → [Save as evidence ▾  entity · field / dimension D1–D4] │
│ Published  2023-05-12 (d) │└──────────────────────────────────────────────────────────────────────┘
│ Retrieved  2026-11-02 UTC │┌ Project tags ─────────────────────────┐┌ Evidence from this document ─┐
│ Original ↗  Archive ↗     ││ example-a  suggested  [✓] [✗]           ││ D1 · Example project · “…”   │
│ Screening [included ▾]    ││ example-b  confirmed                    │└──────────────────────────────┘
│ Reason    [code ▾] note   │└───────────────────────────────────────┘
```

**Timeline**: date uncertainty is shown, not hidden.

```
Cluster ▾  Project ▾  Event type ▾  [ ] Aggregate per quarter       [Export SVG] [Export PNG]
                  2019 ┆ 2020    2021    2022 ┆ 2023    2024    2025    2026
Cluster 1          ●───┆──◇──────◇──────────┆──◇────◇───────●
Cluster 2              ┆   ●       ├──◇──┤   ┆  ◇    ●   ■
Cluster 3              ┆                    ┆    ●──◇──◇───●
                29.08.2019               24.02.2022
● launch  ○ beta  ◇ modification  ■ governance change  ✕ discontinuation
├─┤ date range (precision)   ≤ archive upper bound (hollow, dashed)
```

**Dashboard**

```
[Projects n] [Services n] [Documents n] [Unverified n] [Open comments n] [Open proposals n]
┌ Services: cluster × period (heatmap) ───────┐ ┌ war_trajectory per cluster (stacked bars) ┐
┌ Cluster × beneficiary (matrix) ─────────────┐ ┌ development_mode × war_trajectory ─────────┐
┌ Field completeness per project (grid: filled / verified / missing) ─────────────────────────┐
```

**Review inbox**

```
Review   [Proposals n] [New unverified n]       Filter: kind ▾ · source ▾ · run ▾ · entity type ▾
☐ update_field · project example · description_uk · run_123 (ministry_projects)
     current  (manual 🔒, 2026-11-02): «…»
     proposed (snapshot raw_…, 2026-11-09):  «…»            [Accept] [Edit & accept] [Reject…]
☐ possibly_discontinued · service … · missing in 2 complete runs since 2026-11-10
☐ create_event · launch? · “… запустили …” · doc_…             [Open draft]
Selected 2 → [Accept all] [Reject all (reason)]
```

Further views: **Recent changes** (feed with filters; diff popover), **Collector runs** (status, duration, counters, errors, log; "Run now"), **Codebook** (edit vocabularies with definitions and usage counts), **Releases** (list, manifest, downloads, preview).

### 7.3 Table mechanics

- **Filter grammar in the URL**, e.g. `?f.kind=in:e-service,e-document&f.launch=range:2022-02-24..&sort=-launch,name&q=Дія&cols=…`. The TanStack Router schema validates it; the same filter definition drives the API, CSV/XLSX export and saved views.
- **Filter types:** text (contains, prefix FTS); multi-select with counts for vocabulary fields (facet counts for the current filter, computed server-side); date range (aware of date intervals: a launch overlaps / lies within the filter range); yes/no.
- **Quick filters:** unverified, open comments, no start date, in_paper_scope, period.
- **Full-text search** across entities and document texts (FTS5, Cyrillic and Latin, normalised as in §4.7).
- **Bulk edit:** set or add/remove values for vocabulary fields, status and verification across the selection, with one `batch_id` and an optional note.

### 7.4 Exports

- **Current view:** CSV and XLSX (same filters, all matching rows, selected columns).
- **Full dataset:** JSON, CSV and XLSX, including derived fields (`derived_*`) and `field_provenance.csv`.
- **QDA corpus:** one UTF-8 text file per **included** document, grouped in folders by project (a document linked to several projects appears in each folder, and the metadata records that), plus a metadata table in a shape suitable for MAXQDA document variables, ATLAS.ti document groups and NVivo classification sheets. The exact column layout will be checked against the current versions in Phase 3.
- **Codebook** as Markdown.
- **Phase 3 contract** (`docs/API.md` §8.8): the full dataset is a ZIP bundle (CSV per type, `document_link.csv`, `field_provenance.csv` with licences, `provenance_summary.csv`, `merges.csv`, `sources.csv`, `source_observation.csv`, `dataset.json`, `dataset.xlsx`, the codebook with the coding rules, `manifest.json` with SHA-256 per file and `SHA256SUMS`), built on request in one read transaction, with a privacy guard (no contact e-mail, User-Agent token or bot-manager token in any file); the QDA corpus holds **one text file per included document** (UTF-8 with BOM, named by date and ID; earlier versions that codings quote as extra files) instead of folders per project, with `metadata.csv` (document variables), `cases.csv` (case variables of projects and services), `links.csv` (document sets per project or cluster), `codings.csv` (the anchored evidence with document dates and cases) and the codebook; a REFI-QDA (QDPX) project file is not produced in Phase 3; the codebook is exported as Markdown and CSV from the database's working copy.

### 7.5 Security (superseded by D-15)

The planned security layer is superseded by decision D-15 (§12): the server is secured by its environment, so the app has no Host allowlist, no cross-site and origin checks, no security headers (CSP), no HTML sanitiser (`nh3`, DOMPurify) and no upload hardening. What stays, because it is correctness rather than defence:
- **Input validation** with Pydantic and the registry (lengths, vocabulary codes, URL schemes `http`/`https` only).
- **Rendering:** Markdown is rendered server-side with raw HTML disabled; document texts are always rendered as plain text and search highlights as React elements.
- **Secrets** only in `.env` (`.env.example` in the repo). Lockfiles for Python and npm. Delete is soft; hard purge is CLI-only.

---

## 8. Operations

- `docker compose up -d` starts the single `app` service: port `${HOST:-127.0.0.1}:${PORT:-8080}:8080`, volume `./data:/app/data`, bind mount `./releases`, healthcheck, `restart: unless-stopped`. The image is multi-stage (Node build → slim Python runtime), runs as a non-root user and carries the git commit as a label. On start it runs `mdt db upgrade`.
- **Access** (README; D-15 replaces the planned team access): the app is published on 127.0.0.1 by default; its one user reaches it through the server's environment, e.g. an SSH tunnel or a protected network interface set as `HOST`. Access control is the environment's job.
- **Scheduled jobs:** collector runs weekly by default (cron in `.env`, visible in the UI), backup daily.
- **Makefile:** `dev`, `test`, `lint`, `typecheck`, `build`, `up`, `down`, `logs`, `migrate`, `seed`, `collect SOURCE=…`, `import FILE=… [DRY_RUN=1]`, `fixtures SOURCE=…`, `release NAME=…`, `backup`, `restore FILE=…`, `codebook`, `check`.

## 9. Quality and tests

- **Backend:** ruff, mypy; pytest for parsers (offline fixtures), the HTTP client (throttling, robots, conditional GET, backoff, block detection; with a fake transport), the domain logic (revision, empty-diff no-op, restore, serialised writes, locks, proposals including dedup and rejection memory, disappearance only after complete runs, derived-field rules including precision edge cases at both cut-off dates), the API, the importer (mapping, dry run) and release manifests.
- **Frontend:** ESLint, tsc; Vitest for filter-URL round trips, diff views and the edit form.
- **E2E smoke tests** (Playwright, Chromium): start the app on a seeded DB → filter the projects table → edit with a note → history and diff → restore → comment and resolve → export. (The conflict scenario with two browser contexts was dropped with D-15.)
- **CI** (GitHub Actions): lint, type checks and tests for backend and frontend, plus a Docker build. Network-dependent tests are excluded by marker.

---

## 10. Phase plan

| Phase | Content | Done when |
|---|---|---|
| **0 (this)** | Paper read; environment checked; plan, SOURCES and CODEBOOK drafts; open questions | Approval |
| **0b — source checks** | Once there is network access (this environment or the server): for each source robots.txt, licence footer, sitemaps/RSS, JSON endpoints (Playwright XHR log on 1–2 pages), pagination, date formats, archive depth (binary search over listing pages), CDX coverage. **Budget:** ≈ 150 requests overall, ≤ 1 request/s per host. Fixtures captured. `docs/SOURCES.md` and the collector strategy (§5.2) finalised. **Done on 2026-10-29 from the development environment (partially):** all sources except S5 and S6 checked (195 HTTP requests to 34 hosts, more than the planned ≈ 150 because the scope grew to the candidates C-1 to C-5 and the paper leads; ≤ 1 request/s per host for every logged request, while the 9 followed redirect hops came at once; 8 browser page loads); every `[hypothesis]` and `[search-summary]` item of S1–S5 resolved in `docs/SOURCES.md` (confirmed, refuted, or not determinable with the reason); 103 fixtures and `backend/tests/test_fixtures.py` committed; §2.3 and §5.2 updated. **Data lead's local checks (2026-10-30) [user]:** the Wayback Machine and www.undp.org work from the data lead's machine; zakon.rada.gov.ua and data.rada.gov.ua do not exist as subdomains (rada.gov.ua does); cms.thedigital.gov.ua does not exist; codeua.com is not needed (`docs/SOURCES.md` §5). **Open, from the target server:** `mdt fixtures capture wayback` with the S5 checks (CDX coverage, skip counters, throttling, `id_` fixtures), the trailing-dot host, www.undp.org (add the report by URL), one DNS and robots.txt check of zakon.rada.gov.ua for the Phase 3 decision on C6, and `mdt sources check` for geo-blocking (R2) | Every `[hypothesis]` and `[search-summary]` item for S1–S5 is confirmed, refuted or documented as not determinable; fixtures committed. *Status:* met for S1–S4; S5 is documented as not determinable from the development environment and still needs the server checks |
| **1 — skeleton** | Repo structure, `CLAUDE.md`, tooling; models, Alembic migrations, FTS, revision triggers; `apply_change` with diff, no-op, restore; field provenance and locks; optimistic locking (409 + payload; removed again by D-15); soft delete and trash; comments (threads, status, Markdown, revisioned edits); vocabularies (YAML → DB) and seed (19 + 1 projects); API with server-side filters, sort, pagination and facets; UI tables (filters, column chooser, URL state, saved views, bulk edit, CSV/XLSX export of the current view), detail pages with edit, badges, history, diff, restore, conflict dialog (removed again by D-15), comments; Recent changes; Docker and compose | Definition of Done 1, 2, 4 and 6 on seed data; tests green |
| **2 — data acquisition** | **Contract of 2026-10-30** (revised the same day): `docs/COLLECTORS.md`, `docs/DATA_MODEL.md` §14–§18, `docs/API.md` §7, `docs/UI.md` §8. `PoliteHttpClient` (httpx2, protego), raw snapshot store with field-level snapshot references, runs (one at a time, in a server thread or the CLI; fetch log, run messages, cancel, stale-run recovery), migration `0002`; reconciler, proposals and review inbox; source observations and "possibly discontinued"; collectors C1 `ministry_projects`, C2 `project_sites`, C3 `diia_catalog`, C4 `ministry_news` and `kmu_news`, C5 `wayback` (synthetic fixtures; the real ones are captured on the server); alias tagging and event proposals (`tagger`); duplicate detection, merging and unmerging of projects and services; importer (CSV/XLSX mapping + dry run); manual documents (upload, URL, archived copies; the planned XML-bomb and SSRF protections are dropped, D-15); runs and sources pages | Definition of Done 3 and 5: the acceptance tests of `docs/COLLECTORS.md` §12.1 and the E2E scenarios (i) and (j) of `docs/UI.md` §8.9 green; all gates green |
| **3 — analysis** | **Contract of 2026-10-31** (revised the same day after a four-lens review): `docs/DATA_MODEL.md` §19–§24, `docs/API.md` §8, `docs/UI.md` §9, `docs/COLLECTORS.md` §15, `docs/CODEBOOK.md` §2.10. Migration `0003`; document view with screening and coding queues, evidence capture anchored in text versions (offsets, verbatim quotes, fields coded from a passage), link and proposal decisions; organisations, participations (with date bases; the focal organisation's portfolio roles drive `portfolio_entry` and the new `entry_period`), components, relations and indicators as tables with create forms on detail pages; dimension evidence with team analysis codes (`dimension`, `analysis_code`) and cases; computed periods of events, documents, participations and evidence; timeline (deterministic SVG, PNG, portfolio bands); dashboard (generic crosstabs and coverage, periods on both D-10 bases, screening flow, checks); exports built on request: dataset bundle, QDA corpus, codebook (Markdown, CSV); optionally and last C7a Telegram. **Deferred** (`docs/COLLECTORS.md` §14): C3b and C2a (D-12), C7b data.gov.ua, C6 (S6 alternative), Wayback reconstruction of the catalogues, proposals for organisations, participations and relations from page statements, pymorphy3 alias suggestions, re-anchoring, merging organisations and components, the UNITED24 harvester, a QDPX export | Definition of Done 7 except releases: the backend tests of `docs/DATA_MODEL.md` §24, the E2E scenarios (q)–(u) of `docs/UI.md` §9.8 (document view, analysis records, timeline, dashboard, exports) and all gates green; no collector is needed |
| **4 — operations** | `make release` with manifest and tag; releases view; backups with rotation and restore test; schedules; CI; README, DATA_MODEL, CODEBOOK (generated), SOURCES, METHODS | Definition of Done 1–8 |

Phase 1 does not depend on the source checks and can start right after approval; Phase 0b can run before or alongside it. Phase 2 builds C1–C4 (with C4b) on the Phase 0b fixtures and C5 on synthetic fixtures in the documented CDX format; C5 is enabled on the server after `mdt fixtures capture wayback` and the S5 checks. C2a, C3b, C6 and C7 move to Phase 3, which specifies C7a (Telegram) as optional and defers C2a, C3b, C6 (the S6 alternative applies) and C7b (`docs/COLLECTORS.md` §14).

---

## 11. Risks and mitigations

<!-- RISKS:BEGIN -->
| # | Risk | Effect | Mitigation |
|---|---|---|---|
| R1 | No network access to sources in the development environment (Phase 0: confirmed; Phase 0b: access enabled on 2026-10-29, but web.archive.org, zakon.rada.gov.ua, data.rada.gov.ua and cms.thedigital.gov.ua still give no TLS answer [0b]) | No checks and fixtures for S5 and S6 | Check S5/S6 and capture their fixtures from the target server (`mdt fixtures capture`); all other sources are checked and have fixtures |
| R2 | gov.ua sites block or throttle foreign IPs or bots. Known for some state services (the State Tax Service blocks foreign IPs [search]). Phase 0b [0b]: from the development environment no gov.ua host showed a challenge or geo-block page, but the Rada hosts never answered (cause not determinable), www.kmu.gov.ua and diia.gov.ua run bot managers (no challenge at 1 request/s), codeua.com serves a Cloudflare challenge and www.undp.org an Akamai 403 | Gaps; runs break off | Re-check every host from the target server before Phase 2; block detection → `partial` run, log, report; Wayback fallback where configured; no circumvention |
| R3 | thedigital.gov.ua is a beta relaunch [user] [0b]: structure changes; the collectors depend on the embedded React Router turbo-stream format, route ids and build version (C1, C4, also digitalstate.gov.ua) | Parser breakage | Decoder and DOM fallback with fixture tests; a format change fails the run loudly instead of yielding empty data. Dates without year and archive depth are resolved: machine-readable dates on every item, news back to 2019-10-07 [0b] |
| R4 | Diia app services are only partly on the web [user] | Incomplete service inventory | App services enter as proposals from announcements; the gap is stated in METHODS |
| R5 | Wayback rate limits and gaps; not reachable from the development environment, and archive.org answered 429 on the first request from its shared egress IP [0b] | Slow runs, missing upper bounds; possibly no Wayback at all from the server | Strong throttling, caching, CDX `collapse`; archive dates are upper bounds only; test from the target server; "unavailable" is recorded as such, never as "no captures" |
| R6 | Catalogue HTML changed over the years | Historic captures need era-specific parsers | Parsers versioned per layout era with fixtures for each era; scope limited to the yearly cut-off dates and 2022-02-23 |
| R7 | Homonyms and inflection in auto-tagging (`дія` = action) [local] | False or missed tags | Curated alias forms, case-sensitive brand aliases, exclusions, suggested state, one-click review |
| R8 | Portfolio changes (PlayCity, 19 vs. 20 entries) [user] | Unclear unit of analysis | Listing date as an observation; governance_change events; `in_paper_scope` with reason |
| R9 | Training-knowledge leakage into the data | Unverifiable values | No writes without channel and provenance; seed limited to §3 of the assignment; reviews |
| R10 | Copyright of full texts from third-party media | Publishing risk | Releases without non-open full texts; QDA export internal only |
| R11 | SQLite concurrency | Lock errors | WAL, `busy_timeout`, serialised runs, small transactions |
| R12 | No authentication and no security layer in the app (D-15) | Exposure if the server's environment stops protecting it | Binding to 127.0.0.1 by default; access control stays with the server's environment (decision of the data lead) |
| R13 | Interview transcripts (later) contain personal data | Data protection | Not in v1; if added later: a separate protected document class, excluded from releases (decision for the team) |
| R14 | Responsibilities change during the observation window (PlayCity coordination, Brave1 management, leadership and mandate of the ministry in 2025–2026 [search]) | Portfolio statements in the paper go stale | Participations with periods, governance_change and context events, statements tied to a release date (§13) |
| R15 | Wayback rate limits are undocumented [doc] | Blocks or bans | 1 request per 5 s by default, backoff, cached CDX responses, no parallelism |
| R16 | Strategies and brands listed as "projects" (WINWIN as a strategy [search-summary], European Integration as a policy workstream [search-summary]) | Inconsistent unit of analysis | Capture everything, code `unit_type` (product/service, platform, programme, strategy/policy area, organisation) and decide scope with a reason (D-1) |
| R17 | Robots.txt rules close paths the plan relied on [0b]: kmu.gov.ua `/npas/` (act pages), `/storage/` (attachments), `/timeline` and `/api/` (listing, search); data.gov.ua `/api/` (CKAN API) and dataset history | Acts and some PDFs only as references; no CKAN API | Acts from zakon.rada.gov.ua (server check); kmu.gov.ua news via its sitemaps; data.gov.ua via Atom feed and DCAT; robots.txt re-checked on every redirect hop; Wayback is not used to read disallowed paths (proposed default) |
| R18 | Snapshots contain data about the requester or third persons [0b]: the kmu.gov.ua bot-manager token encodes the client's IP address; feeds and pages carry staff names and e-mail addresses (data.gov.ua, a ministry document page) | Privacy breach through exports, releases or fixtures | Raw snapshots stay on the server; exports, releases and fixtures strip such tokens and personal data; `test_fixtures.py` guards the fixtures |
| R19 | Licences narrower than assumed [0b]: only the ministry site, the kmu.gov.ua portal, the Diia guide and one microsite state CC BY 4.0; the project sites, the Diia portal, two microsites, Telegram and Digital State UA reserve all rights or state nothing; usf.com.ua's robots.txt reserves rights under Art. 4 of Directive (EU) 2019/790 | Full texts of most project sites cannot be released | Releases carry metadata and short excerpts for those sources (D-5); licence per source in `sources.yaml`; the team confirms the usf.com.ua position (`docs/SOURCES.md` §5) |
<!-- RISKS:END -->

---

## 12. Decisions for the team

<!-- DECISIONS:BEGIN -->
| ID | Decision | Proposal |
|---|---|---|
| D-1 | Unit of analysis "project": does European Integration (Євроінтеграція) belong in scope? General inclusion criteria? | Capture everything the ministry lists (`in_paper_scope = false` until decided); criteria in CODEBOOK |
| D-2 | Which event types count as a modification for `adapted_in_war`? | expansion, major_update, rebrand, governance_change, suspension |
| D-3 | Period for items with only an archive bound before the invasion | Strict `unknown` + flag `existed_before_invasion`; optional extra value `pre_invasion_or_earlier` |
| D-4 | Definitions of `wartime_relevance` (direct/indirect/none/unclear) | Draft in CODEBOOK |
| D-5 | Release content (full texts, comments) | Without comments, proposals or non-open full texts. Author names no longer arise (D-15): changes made in the app are recorded as `user`, the others under their channel (`seed`, `import:<file>`, `collector:<name>`) |
| D-6 | Service granularity (what is a sub-service? app features vs. portal services) | Rules in CODEBOOK (draft) |
| D-7 | Policy domains and beneficiaries | COFOG divisions as the top level + subcodes from the data (draft in CODEBOOK) |
| D-8 | May collectors create Services directly (unverified)? | Yes for catalogue sources; projects only via proposal |
| D-9 | Release via UI button with git access? | No (§6.7); UI preview + CLI |
| D-10 | Basis for `period`/`war_trajectory` at project level: launch of the initiative or entry into the ministry's portfolio? | Compute both; launch as default, portfolio entry as an alternative view. **Phase 3 contract:** the portfolio entry gives `entry_period` (the period on that basis), but no war trajectory: a trajectory describes how the initiative changed, which the entry date does not tell. The portfolio roles are the `participation_role` terms marked `portfolio_role` (`initiator`, `owner`, `operator`; whether `coordinator` counts is part of this decision); services get an entry only from their own participations |
| D-11 | Add `unit_type` to Project (product/service, platform, programme, strategy/policy area, organisation)? | Yes (R16); the vocabulary draft is in CODEBOOK |
| D-12 | Add the Digital State UA catalogue and the Diia service guide as sources (after 0b)? | Yes if 0b confirms structured access; as cross-check sources, not as the portfolio definition. Phase 0b (2026-10-29) found structured access for both (embedded loader data; the guide's open JSON register), see `docs/SOURCES.md` C-1 and C-2; the decision itself is still open. Phase 2 deferred both collectors to Phase 3, and the Phase 3 contract defers them again (observations only would serve no Phase 3 analysis; `docs/COLLECTORS.md` §14); this default applies when they are built |
| D-13 | Enforce the coding rules of CODEBOOK §2.3 and §2.8 in the app: "verified" only with evidence that quotes the source verbatim; an excluded document needs a screening reason, and only excluded documents carry one? | Yes (enforced since the Phase 1 review). Side effect: excluding documents needs the reason in the same change, so a single-field bulk edit cannot exclude |
| D-14 | Full-text search over comments: also match status words and the resolver (`open`, `user`), as now (DATA_MODEL §10), or comment text only? | Comment text only (the status has its own filter, and the resolver is always `user`, D-15); a small change with a reindex. Until decided, the current behaviour stays |
| D-15 | Single user, no concurrent editing, no additional security layer | **Decided by the data lead on 2026-10-29.** The data lead only provides the server; one other person uses the app. No names are entered (writes in the app are recorded as `user`), nothing has to work for several users at once, and the server is secured by its environment, so the app needs no security functions of its own. Removed: the author picker and `X-Author`, author filters and `TEAM_MEMBERS`; optimistic locking (`expected_version`) and the conflict dialog; the request guard (`ALLOWED_HOSTS`, origin checks, size limits), the security headers and the HTML sanitisers; the team access notes. Kept: revisions, restore, field provenance and locks, soft delete, input validation. Definition of Done item 4 changed accordingly (CLAUDE.md) |
| D-16 | Do the events of a project's services count for the project's derived `period` and `war_trajectory` (e.g. a service launched in war makes its pre-war project `adapted_in_war`)? | No (Phase 3 default): derived values use the subject's own events (`docs/DATA_MODEL.md` §8.2); the project fields `services_new_in_war` and `services_adapted_in_war` and a dashboard check show projects whose services changed in war, so a person can record a project-level event with its evidence |
<!-- DECISIONS:END -->

---

## 13. Notes for the paper (Hinweise fürs Paper)

<!-- PAPER-NOTES:BEGIN -->
**Status:** these notes concern the project list and responsibilities. They come from the assignment [user], the paper [paper] or search results [search]/[search-summary]. Phase 0b (2026-10-29) checked some of them against the pages themselves; those checks are marked **[0b]** and say only what a page showed on that day. **None of the notes has been entered into the data.** Each one says what still has to be verified (Phase 2). The full evidence list with URLs is in `docs/SOURCES.md` § "Leads for the paper".

**N1 — Define the unit of analysis by listing and date.**
- The paper counts 19 projects; the ministry's page shows 20 [user]. Missing in the paper: "Євроінтеграція" (European Integration).
- Its category `progress` is titled "Досягнення" (achievements) [search]. The search summary describes it as continuing the EU-integration course, gradual integration into the EU Digital Single Market and alignment with EU digital law [search-summary]. That makes it a policy workstream rather than a digital product [hypothesis].
- WINWIN is described as a national innovation strategy [search-summary], so it too may not be a single product.
- The search index also contains a URL variant of the European Integration entry without `/progress/` [search], so the listing itself changes.
- [0b] On 2026-10-29 the listing showed 20 entries; the variant without `/progress/` redirects (302) to `/projects/progress/yevrointegraciya`, and the older URL scheme `/projects/<slug>` redirects only while a slug still exists (`/projects/e-residency`, linked from the 2021 microsite, answers 404). Six entries are links to external domains rather than ministry project pages (WINWIN, USF, CodeUA, UNITED24, UNITED24.media, Digital State UA). Project pages carry no dates. The ministry's second catalogue, Digital State UA, lists 17 projects, of which 13 match ministry entries by name (derived comparison).
- *Suggestion:* define the portfolio as "initiatives listed on thedigital.gov.ua/projects on <date> (dataset release X)", report additions and removals over time, and code each entry's `unit_type` (D-1, D-11).

**N2 — PlayCity: responsibility changed during 2026** (all to verify against the resolutions)
- Cabinet resolution 314-2025-п set up the central executive body for gambling and lotteries [search]. The date 21.03.2025 is [search-summary], consistent with the suffix of the kmu.gov.ua URL.
- Interfax-Ukraine: "Кабмін вивів PlayCity із сфери координації Мінцифри" (the Cabinet removed PlayCity from the ministry's sphere of coordination) [search; date not shown]. Forbes Ukraine reported that the Cabinet resubordinated PlayCity to itself (15.05.2026, date from the URL) [search]. The legal act is reportedly resolution №613 of 13.05.2026 [search-summary]. [0b] Both items exist: the Interfax-Ukraine article carries that title with `datePublished` 2026-05-15T13:57:21+03:00 (English version 2026-05-15, "Cabinet removes PlayCity from Digital Development Ministry’s coordination sphere"), the Forbes Ukraine article "Кабмін перепідпорядкував «ПлейСіті» собі. Регулятор азартних ігор виходить з-під Мінцифри" `datePublished` 2026-05-15T14:40:51+03:00. The resolution itself was not retrieved (zakon.rada.gov.ua not reachable; kmu.gov.ua act pages robots-disallowed).
- In September 2026, resolution №1133 of 17.09.2026 reportedly amended PlayCity's regulation (coordination by the Prime Minister) [search-summary]. A related PDF on kmu.gov.ua and a trade-press article exist [search].
- The interview the assignment refers to: Forbes Ukraine with minister Oksana Ferchuk, 11.08.2026 [search]; [0b] the page exists with `datePublished` 2026-08-11T09:45:57+03:00 (the passage on PlayCity was not looked for). It contains the quote "we do not influence the actions of this agency, but we are responsible for policy development" [search-summary]. The Interfax articles citing this interview found so far concern Brave1 [search]; the piece with the PlayCity passage still has to be identified.
- PlayCity's 2026 budget-programme passport is titled as approved by an order of the Ministry of Digital Transformation [search], so the ministry may still be the main budget administrator [hypothesis]. "Responsibility" thus has several dimensions: coordination, budget and policy.
- PlayCity's own website reportedly still names coordination through the minister [search-summary]. [0b] On 2026-10-29 its meta description describes the agency as coordinated by the Cabinet "через Першого віце-прем’єр-міністра України - Міністра цифрової трансформації"; the ministry still lists PlayCity under `technologies`, and its PlayCity page says the ministry "відіграє ключову роль у формуванні ефективної політики та координуванні роботи держагентства". The legal-basis page of playcity.gov.ua lists ministry orders up to 30.07.2026 among its bases. Official pages lag behind legal changes, so cite them with the retrieval date.
- *Suggestion:* once verified, describe PlayCity with dates and the Cabinet resolutions as primary sources (e.g. "set up in 2025 under the ministry's coordination; since 2026 coordinated by the Prime Minister; the ministry keeps policy responsibility"). In the data: governance_change events and Participations with periods.

**N3 — The leadership and mandate of the ministry changed in 2025–2026** (context for the post-invasion period; to verify)
- A ministry news title "Зберігаємо темп: Олександр Борняков очолив Мінцифру" shows an interim head [search].
- Interfax reports that the Verkhovna Rada appointed Oksana Ferchuk [search]; [0b] the article "Рада призначила заступницю Міноборони Ферчук очільницею Мінцифри" has `datePublished` 2026-07-16T16:39:44+03:00, and on 2026-10-29 the ministry's `/ministry` page and kmu.gov.ua's ministry page name her as Minister of Digital Transformation. The Forbes Ukraine profile is dated 17.07.2026 [search]. The previous minister left in January 2026 [search-summary].
- Resolution 214-2026-п replaces the title "First Vice Prime Minister – Minister of Digital Transformation" with "Minister of Digital Transformation" in a working group [search]. Whether the post lost its vice-PM rank is [hypothesis].
- Amendment 386-2025-п adds AI and semiconductor development to the ministry's regulation [search].
- *Suggestion:* the period "after 24.02.2022" is not institutionally homogeneous. State the end of the observation window explicitly (release date) and mark these changes as context events on the timeline.

**N4 — "In the ministry's portfolio" does not mean "developed by the ministry"** (for D3; to verify)
- **UNITED24** was launched "at the initiative of the President" [search]. [0b] u24.gov.ua's title reads "UNITED24 — The initiative of the President of Ukraine", and its home and about pages do not name the Ministry of Digital Transformation.
- **Ukrainian Startup Fund:** a government decision transfers the Innovation Development Fund "into the management of the ministry" [search]. According to the search summary, this fund is the legal entity behind USF, and the transfer happened at the end of 2022 [search-summary]. If confirmed, this is a pre-existing organisation entering the portfolio, not a launch. [0b] usf.com.ua states that the fund (official name "Фонд Розвитку Інновацій") was founded in 2018 at the initiative of the Minister of Finance and has been under the ministry's management since 1 January 2023 (footer; the about page says "since 2023").
- **CodeUA** was launched by the ministry [search], with the Lviv IT Cluster and USAID support [search-summary].
- **UNITED24 Media:** the ministry announced its creation [search]. [0b] The site's JSON-LD names "Ministry of Digital Transformation of Ukraine" as founder, with `foundingDate` 2024-03-29; its visible about text does not name the ministry.
- **Brave1** was launched in April 2023 [search]. One report says it would move to the Ministry of Defence [search]; in August 2026 it "remains under the ministry's management" [search].
- **Digital State UA** was launched by the ministry [search] and is itself a catalogue of digital projects [search]. [0b] Its footer states that the project "is implemented by the Ministry of Digital Transformation of Ukraine" with donor support (Eurasia Foundation/USAID/UK Dev; EGAP/East Europe Foundation/Switzerland).
- *Suggestion:* code the ministry's role per project with dates (initiator, owner, operator, partner, coordinator, regulator), and distinguish **launch** from **portfolio entry** (`portfolio_entry`, D-10). This matters for the pre/post comparison and for the distinction between adaptation and new development (Yoo et al. 2012).

**N5 — Ministry categories are not the paper's clusters** [user]
- The site uses `technologies`, `business`, `regions`, `education`, `progress`; Diia.City appears twice; Diia.Center sits under `regions`. [0b] On 2026-10-29 a sixth rubric is used (`army`, for UNITED24), Diia.City has a single rubric (`business`; the `regions` URL shows the same record), and an entry can carry additional rubrics (Дія.Цифрова громада also under `how-tos`).
- *Suggestion:* present the seven clusters as the authors' classification with coding rules (CODEBOOK) and report the mapping to the ministry categories in an appendix table generated from a release.

**N6 — Dating rules for the methods section** (§4.4)
- Archive captures are upper bounds.
- A launch interval that straddles a cut-off date (29.08.2019 or 24.02.2022) leaves the period unknown.
- `prewar_unchanged` means "no modification recorded up to release X".
- METHODS.md will provide ready-made wording.

**N7 — Claims without evidence in the current draft** [paper]
- The descriptions of PlayCity (tax revenue for the Armed Forces) and Brave1 have no citation yet.
- The platform will supply citable documents with retrieval dates and archive links.

**N8 — High-value documents found** (to retrieve in Phase 2)
- The ministry's 2025 year-in-review on kmu.gov.ua ("…підсумки Мінцифри у 2025 році") [search]; [0b] retrieved (published 24.12.2025 17:07 per the page; it links PDFs on storage.thedigital.gov.ua and the 2025 microsite).
- The microsites `2025.thedigital.gov.ua` ("Підсумки року роботи Мінцифри 2025"), `2years.` and `5years.thedigital.gov.ua` [search]; [0b] all three are single static pages with their full text; only `2years.` carries the CC BY 4.0 sentence, and none states a publication date.
- Annual reports and work-plan reports on `storage.thedigital.gov.ua` (e.g. results report 2022, work plan 2024) [search-summary]; [0b] confirmed by the document titles on `/ministry`, which also links work plans 2020, 2021 and 2023 and execution reports 2020, 2021 and 2023; nothing for 2019 or 2025 was found.
- **KIIS/UNDP 2026:** the report page exists at `undp.org/node/565986` [search]. The URL in the paper's reference list did not appear in the search results, so check that it resolves. [0b] Not determinable from the development environment: www.undp.org answered HTTP 403 (Akamai) to the first request; check from the target server or upload the report (C8).

**N9 — Cite web pages with retrieval date and archived copy**
- "Ministry of Digital Transformation of Ukraine (n.d.). Ministry" points to a page of a site in beta relaunch whose content changes.
- The platform stores the snapshot and the archive URL for every cited page.

**N10 — Further initiatives to screen** (leads only, for D-1; added as proposals after verification)
- A national web platform for administrative service centres (may overlap with Diia.Center) [search].
- The EU-funded programmes DT4UA and EU4DigitalUA [search].
- A Council of Europe child-protection project the ministry joined [search].
- From media reports only: the e-democracy platform "ВзаємоДія", a state AI platform and a unified platform for state registries [search].
- The subdomain `ai.thedigital.gov.ua` [search]; [0b] an ongoing AI policy portal of the ministry ("Центр відповідального ШІ") with its own news and documents in Ukrainian and English, not a year-in-review site (scope decision, `docs/SOURCES.md` §5).

**N11 — Reportable numbers from Phase 3** (for the methods and results sections; no values yet)
- The screening flow (collected → screened → included, exclusions by reason, per source) is counted on the dashboard and reproducible from the revisions.
- Evidence coverage per dimension D1–D4 and per coded field, and the share of verified values, describe how well the portfolio coding is supported.
- Periods can be reported on two bases (D-10): the launch of the initiative and its entry into the ministry's portfolio; state which one a table uses. The timeline draws imprecise dates as intervals instead of hiding them, and its caption counts the events per period.
- Every figure, table and export carries the **data revision** (the newest revision number and its time), which identifies the curated data state; derived and computed values also depend on the cut-off dates and the app version, which figures and crosstab files print next to it. Cite figures and tables with it and keep a dataset bundle of that data revision (Phase 4: the release name and tag make it permanent); every dashboard number can be recomputed from the bundle's CSV files. Take numbers while no collector run is writing, or from the bundle.
- "Coded" documents are those with at least one passage cited for a dimension D1–D4 (`docs/DATA_MODEL.md` §21); citations for a record or a field do not count, so the coded share describes the thematic analysis.
- Periods differ in length and the war period is still open (it ends at the data revision's time); the dashboard shows each period's length and counts per year, and items known only from a pre-invasion archive capture are counted as "shown to exist before the invasion" next to `unknown` (not being shown is no evidence of absence).
<!-- PAPER-NOTES:END -->

---

## 14. Open questions

<!-- QUESTIONS:BEGIN -->
Also asked in the session (in German).

1. **Contact e-mail for the User-Agent:** answered on 2026-10-31: a dedicated address named by the data lead (it replaced the address used for the Phase 0b checks). It lives only in `.env` (development environment and server; the server's `.env` must carry it too), never in the repository.
2. **Server:** operating system and version; Docker and Compose versions; CPU, RAM, free disk; **location/hosting (country)**, relevant for possible geo-blocking; outbound internet access; how the user reaches the app (SSH tunnel or a protected network interface; the server's environment secures it, D-15); off-host backup target.
3. **Existing table:** does the dataset mentioned in the paper exist? Format, columns, who collected it, from which sources and when? If yes: upload it here or put it into `data/import/` on the server; the importer gets a mapping and a dry run.
4. **Network for Phase 0b:** answered on 2026-10-29: the data lead enabled network access for this cloud environment, and Phase 0b ran here; S5 and S6 (and the other hosts in §2.2 that did not answer) are checked from the target server. Further answered on 2026-10-30 by the data lead's local checks [user]: the Wayback Machine and www.undp.org work from the data lead's machine, zakon.rada.gov.ua and data.rada.gov.ua do not exist as subdomains (rada.gov.ua does), cms.thedigital.gov.ua does not exist, and codeua.com is not needed (`docs/SOURCES.md` §5). What remains for the target server is listed in §10 (Phase 0b row).
5. **Team:** answered on 2026-10-29 (D-15): one person uses the app, without names and without concurrent editing.
6. **Git:** the reply "Ok mach weiter" (2026-10-28) was taken as approval to push to the working branch `claude/sharp-heisenberg-inzace`; on 2026-10-29 the data lead asked for the simplified state (D-15) to be merged into `main`.
7. **Decisions D-1 to D-16** (§12; D-15 is decided): the open ones can be answered later; the defaults above apply until then.
8. **Phase 3** (2026-10-31; the proposed defaults apply until answered): (a) Do the posts of t.me/mintsyfra belong in the screening corpus (collector C7a, `docs/COLLECTORS.md` §15.1)? Default: C7a is built only after confirmation, and the posts are not attributed to the ministry. (b) Name analysis codes below D1–D4 now, or develop them while coding? Default: while coding; the vocabulary starts empty. (c) Which QDA program, and is a REFI-QDA (QDPX) file needed? Default: no QDPX in Phase 3. (d) May the internal QDA corpus hold full texts of sources that are not openly licensed? Default: yes, never published. (e) D-5 for the dataset bundle and releases: include evidence quotes and collected text fields (e.g. service descriptions) of sources that are not openly licensed, and the internal `notes`? Default: included, with the licence recorded per value so that Phase 4 can filter. (f) Is 1 000 characters per coded passage enough? Default: yes.
<!-- QUESTIONS:END -->
