# PLAN: data platform for "Digital Innovation for Governments under Crisis"

> **Status:** Phase 0 plan, 2026-10-28; approved, Phase 1 in progress. For Phase 1 onwards, the contract documents [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md), [`docs/API.md`](docs/API.md) and [`docs/UI.md`](docs/UI.md) are binding; where they differ from this plan in detail (e.g. provenance rules, derived-field algorithm, seed matching), they take precedence.
> **Companion drafts:** [`docs/SOURCES.md`](docs/SOURCES.md) (source register), [`docs/CODEBOOK.md`](docs/CODEBOOK.md) (vocabularies).
> **Language:** code, UI, docs and codebook in English (language of the paper).

## TL;DR

- **One container, one process.** FastAPI serves the API and the built React app. The working store is SQLite (WAL, FTS5). Collectors run as subprocesses of the same image, started by a scheduler, a UI button or the CLI.
- **Traceability built into the model.** Every curated field records where its value came from (`seed`, `collector:<name>@<run>`, `manual:<name>`, `import:<file>`), who set it, whether a human has locked it, and optional evidence. Revisions are append-only, enforced by database triggers. Collectors never overwrite human values: they open **proposals** instead.
- **Collectors** are separate modules with offline tests against saved fixtures. They use a polite HTTP client (robots.txt, about 1 request per second per host, conditional requests, backoff, no circumvention). Every response is kept unchanged as a content-addressed raw snapshot. The Wayback Machine serves as a fallback and supplies *upper bounds* for start dates, never start dates.
- **Main additions to the proposed model:** dates stored as intervals with precision and the verbatim source text; per-source observations (for `first_seen`/`last_seen` and "possibly discontinued"); an explicit `development_mode` field (adaptation vs. new development, Yoo et al. 2012); `unit_type` (product vs. platform, programme, strategy, organisation); the derived `portfolio_entry` (launch ≠ entry into the ministry's portfolio); institutional context events; derived values in their own table; content-addressed document texts; screening reason codes (for a PRISMA-style flow in the paper).
- **Phase 0 findings relevant for the paper (§13, all still to be verified):** responsibility for PlayCity moved away from the ministry in 2026; the ministry's leadership and mandate changed in 2025–2026; for several projects the ministry is not the initiator; European Integration and WINWIN look more like policy areas or strategies than products.
- **Releases** are frozen, hashed exports committed and tagged in git (`make release NAME=…`), created from the CLI only (reasons in §6.7).
- **Blocker found in Phase 0:** this cloud development environment cannot reach any source host, so the hands-on source checks are still open. They are scheduled as **Phase 0b** (§10). Everything this plan says about a source is labelled by how well it is supported (see below).

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

---

## 1. Goals and guiding principles

The platform has two jobs: (1) reproducibly collect the portfolio of projects and digital services of the Ministry of Digital Transformation of Ukraine (Мінцифри) and a corpus of documents for the planned document analysis, and (2) let the team view, filter, comment on and correct those data with a complete history.

**Guiding principle: traceability before completeness.** Each principle maps to a concrete design decision:

| Principle | Design consequence |
|---|---|
| No facts from model knowledge | Values enter only through collectors (each backed by a raw snapshot), the seed, an import or a named person. Every write needs an author. The app makes no LLM calls (non-goal). |
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

- **Outbound network:** all source hosts are blocked by the egress policy of this cloud environment (HTTP 403 from the proxy on CONNECT; checked 2026-10-28). Blocked: thedigital.gov.ua, diia.gov.ua, kmu.gov.ua, web.archive.org, zakon.rada.gov.ua, t.me, data.gov.ua, codeua.com, winwin.gov.ua, usf.com.ua, u24.gov.ua, united24media.com, digitalstate.gov.ua, and also interfax.com.ua, forbes.ua and undp.org. The server-side fetch tool is restricted the same way. Web *search* works, which yields URLs and titles but not page content. GitHub (raw.githubusercontent.com) is reachable, which allowed reading the official Wayback CDX documentation [doc].
- **How Phase 0 was done instead:** three parallel search-only explorations (ministry site and Diia ecosystem; kmu.gov.ua, legal acts, open data, Telegram, Wayback; project domains and governance). Their results are recorded with evidence labels in `docs/SOURCES.md` and in §13. None of it has been entered as data.
- **Consequences:** (a) The Phase 0 source checks (robots.txt, licence footer, JSON endpoints, sitemaps/RSS, pagination, date formats, archive depth, Wayback coverage) could not be done; they move to Phase 0b. (b) Collector development in Phase 2 needs real responses as test fixtures, so either this environment gets network access to the source hosts or fixtures are captured on the target server (`mdt fixtures capture`, §5.7).
- **Available locally:** Python 3.13, uv, Node 22, Docker CLI, pandoc, SQLite 3.45.1 with FTS5 (including the trigram tokenizer).

### 2.3 Source assessment (summary)

<!-- SOURCE-SUMMARY:BEGIN -->
Details, evidence and the Phase 0b checklist per source are in [`docs/SOURCES.md`](docs/SOURCES.md).

| # | Source | Role in the dataset | Known so far | Main risks | Assessment |
|---|---|---|---|---|---|
| S1 | Ministry project list (`thedigital.gov.ua/projects`) | Portfolio backbone, ministry categories | 20 entries on 2 pages, category paths `technologies`, `business`, `regions`, `education`, `progress` [user]; `progress` is titled "Досягнення" (achievements) [search]; CC BY 4.0 footer [user] | Beta relaunch; URL variants (European Integration also indexed without `/progress/` [search]); double listings [user] | **Priority 1.** Small, high value, feasible |
| S2 | Project pages and project sites | Descriptions, operators, outbound links, structured offers | Own sites seen in search: center.diia.gov.ua, osvita.diia.gov.ua, playcity.gov.ua, u24.gov.ua, united24media.com, codeua.com, digitalstate.gov.ua. Digital State UA runs **its own catalogue of projects** (`/projects/<category>/<slug>`) [search] | Heterogeneous sites; licences unknown; winwin.gov.ua, usf.com.ua and a Brave1 domain not seen in search | **Priority 2.** Generic collector plus a few specialised ones |
| S3 | Diia portal catalogue (`diia.gov.ua/services`) | Services with rubric and audience | Category tree `/services/categories/<audience>/<subcategory>` [search]. Related: service guide `guide.diia.gov.ua` (service cards with UUIDs [search]; open data in Excel/JSON [search-summary]) and `plan2.diia.gov.ua` [search] | App-only services missing [user]; history only via Wayback | **Priority 3.** Core of the service inventory |
| S4 | Ministry news, documents and pages; ministry news on kmu.gov.ua | Document corpus; event proposals; filling the 2019–2022 gap | thedigital.gov.ua: two news URL schemes coexist in the index; titles back to about 2020/21, none from 2019 seen; `/documents/{community,legislation,ministry}`; PDFs in hash-sharded storage that cannot be enumerated; year-in-review microsites [search]. kmu.gov.ua: `/news/<slug>`, `/en/news/<slug>`; ministry items from 2019; no per-ministry listing seen; **2025 year-in-review found** [search] | Dates without year [user]; two transliteration styles in slugs [search]; duplicates across both sites | **Priority 4.** Largest volume; kmu.gov.ua essential for 2019–2021 |
| S5 | Wayback Machine (CDX API) | Archive upper bounds; catalogue at cut-off dates; fallback | Parameters verified in the official README [doc]; no rate limit documented [doc]; about 15 requests/min per IP reported by third parties [search-summary] | Throttling, gaps, layout eras | **Priority 5.** Essential, slow by design |
| S6 | zakon.rada.gov.ua | Legal acts, legal-basis events | URL patterns `/laws/show/<id>`, `/go/<id>`; ministry regulation 856-2019-п and later amendments identified [search] | Bot protection [hypothesis] | **Priority 6.** Linked acts only |
| S7 | Telegram (`t.me/s/mintsyfra`); data.gov.ua (CKAN) | Announcements; machine-readable registers | Channel "Мінцифра" (@mintsyfra) with web preview; organisation page `data.gov.ua/organization/mincyfry` [search] | Gaps; API not yet confirmed | **Priority 7.** Optional |
| S8 | Manual (URL or upload) | Reports, interviews, press | KIIS/UNDP report page exists [search] | — | Always available |

**Further candidates found in Phase 0 (to assess in Phase 0b):** the Digital State UA project catalogue; the Diia service guide and its reported open dataset; `plan2.diia.gov.ua` (described as a public dashboard of digital-transformation projects [search-summary]); year-in-review microsites (`2years.`, `5years.`, `2025.thedigital.gov.ua`) [search]; annual ministry reports as PDFs on `storage.thedigital.gov.ua` [search-summary].

**Cross-cutting risk:** some Ukrainian state services block foreign IP addresses (e.g. the State Tax Service, which unblocks only on request [search]); data.gov.ua was temporarily restricted [search-summary]. There is no evidence either way for the target hosts, so access must be tested **from the target server** early in Phase 0b.
<!-- SOURCE-SUMMARY:END -->

---

## 3. Architecture

### 3.1 Overview

```
                ┌──────────────────────────── container "app" (one image) ───────────────────────────┐
 Browser ─HTTP─▶│ uvicorn + FastAPI                                                                  │
 (team via      │   /api/*      REST + Pydantic models                                               │
  VPN / proxy)  │   /*          built React app (static files)                                       │
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
| Markdown | ➕ markdown-it-py + `nh3` | comments rendered and sanitised server-side |
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

- **One container and one uvicorn process** serve the API and the static frontend.
- **Collector runs** (from the schedule, the UI's "Run now" button or the CLI) execute as subprocesses (`mdt collect <source>`). A DB-backed queue runs them **one at a time**. That keeps per-host rate limits valid globally and gives SQLite exactly one background writer. Runs are weekly, so serial execution costs nothing.
- **Resumable runs:** each run stores a checkpoint (page, cursor, URL frontier) on its `CollectorRun` row; `mdt collect X --resume` continues from there.
- **Web requests are never blocked** by collectors: WAL mode, small per-entity transactions and `busy_timeout`.

### 3.5 Configuration (`.env`, template in `.env.example`)

`HOST` (default `127.0.0.1`), `PORT` (`8080`), `DATA_DIR`, `CONTACT_EMAIL` (**required for collectors**: they refuse to start without it), `USER_AGENT` template, `ALLOWED_HOSTS` (Host-header allowlist, §7.5), `COLLECT_SCHEDULE` (cron; default weekly, Monday 03:00 Europe/Kyiv), `BACKUP_SCHEDULE` (daily), `BACKUP_RETENTION` (7 daily / 4 weekly / 6 monthly), `TEAM_MEMBERS` (initial names for the author picker), `MAX_UPLOAD_MB` (50), `MAX_COMMENT_CHARS` (10 000), per-source overrides of throttling in `sources.yaml`.

---

## 4. Data model

### 4.1 Conventions

- **IDs:** prefixed ULIDs: `prj_`, `svc_`, `evt_`, `doc_`, `evd_`, `org_`, `par_`, `cmp_`, `rel_`, `ind_`, `cmt_`, `prp_`, `run_`, `raw_`. The prefix makes polymorphic references self-describing (`subject_id = "svc_01J…"`) and keeps exports readable. Projects also have a `slug` (unique; an old slug becomes an alias when renamed).
- **Common columns of every curated row:** `version` (optimistic locking), `created_at`, `updated_at`, `deleted_at`/`deleted_by` (soft delete), `merged_into`, `verification_status`, `notes`, `field_meta` (JSON, §6.2).
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

Derived values are stored in a `derived` table (one row per project or service). They are recomputed in the same transaction as any change to the subject's events, and in bulk with `mdt recompute`. They are never editable, are not part of curated revisions, are exported with a `derived_` prefix, and are explained in the codebook. Cut-off dates: **MINISTRY = 2019-08-29**, **INVASION = 2022-02-24**. Events marked `disputed` are ignored.

1. **`launch`:** the earliest `launch` event by `date_start`, otherwise the earliest `beta_launch`. The output keeps the interval, precision, basis and the event ID, so the UI can show "2020-06 (month, stated in source)".
2. **`existed_by`:** the earliest `first_archived` event (`archive_upper_bound`). It is displayed as an upper bound ("≤ 2021-05-14, archive") and **never as a start date**.
3. **`period`:**
   - From the launch interval [s, e]: e < MINISTRY → `pre_ministry`; s ≥ MINISTRY and e < INVASION → `pre_invasion`; s ≥ INVASION → `full_scale_war`; an interval that straddles a cut-off → `unknown` (reason `imprecise_date`). Example: a launch known only as "2022" cannot be assigned.
   - Without a launch, using only the archive bound u: u < MINISTRY → `pre_ministry` (certain, because the launch is ≤ u); otherwise `unknown` (reason `archive_bound_only`). The fact that the item existed before the invasion is still recorded (`existed_before_invasion = true` when u < INVASION).
   - No date at all → `unknown` (reason `no_date`).
4. **`war_trajectory`:**
   - `new_in_war`: launch s ≥ INVASION.
   - `adapted_in_war`: existed before the invasion (launch e < INVASION, **or archive bound u < INVASION**) and at least one modification event with s ≥ INVASION.
   - `prewar_unchanged`: existed before the invasion and every modification event has e < INVASION (or there is none).
   - `unknown`: anything else, with a reason (no date, launch straddles a cut-off, or a modification date straddles the cut-off).
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
For every collector, Phase 0b first looks for **structured access** (XHR/JSON seen in the browser, framework data embedded in the page, sitemaps, RSS). HTML parsing is the fallback.

**C1 `ministry_projects`** (S1)
- **Covers** `/projects` and the category listings `/projects/<category>`.
- **Per entry it extracts** the name (uk, plus en where available), the ministry category (URL segment + label), the short description and the link (ministry page or external domain).
- **Observations** are stored per (entry, category), so a double listing such as Diia.City appears twice.
- **Matching:** final URL after redirects → slug → alias. New or missing entries become **proposals**; projects are never created automatically.
- **URL variants** (European Integration with and without `/progress/`) are recorded rather than "fixed".

**C2 `project_sites`** (S2), generic plus specialised
- **Generic, for every project's ministry page and official domain:** title, meta and OpenGraph tags, JSON-LD, main text (about page), footer (statements on operator, owner, licence), outbound links, and a `sitemap.xml` inventory (counts only, no full crawl).
- **Outbound links feed other collectors:** legal acts go to the C6 queue; partner organisations become D3 proposals later.
- **Domain verification:** an official domain must be linked from the ministry page or from a gov.ua page, or the other way round. The chain of links is stored as evidence.
- **Specialised collectors**, only where structured offers exist (decided in Phase 0b). Candidates:
  - (a) **the Digital State UA project catalogue** [search], a second, broader catalogue for cross-checks;
  - (b) the Diia.Education course catalogue;
  - (c) Diia.Business programmes;
  - (d) UNITED24 fundraising directions;
  - (e) Brave1 grants and challenges;
  - (f) the Diia.Center platform (`center.diia.gov.ua`, list of centres → indicator).

**C3 `diia_catalog`** (S3)
- **Path:** category tree → service pages.
- **Output:** Services under project `diia` (created as unverified), with source categories (audience + subcategory), audiences, URL, description and channel hints; observations per service.
- **Normalisation:** host variants such as the trailing dot [search].
- **Candidates for 0b:** **C3b** service guide (`guide.diia.gov.ua`; if the reported open dataset exists with versions, it is a structured inventory including online availability) and **C3c** `plan2.diia.gov.ua` (only if it offers structured status data).
- **App-only services** enter as proposals derived from announcements (C4).

**C4 `ministry_news`** (+ documents and ministry pages) and **C4b `kmu_news`** (S4)
- **thedigital.gov.ua:**
  - news under both URL schemes; rubrics including "Постанови Уряду" [user];
  - `/documents/{community,legislation,ministry}`; `/ministry`;
  - PDFs on `storage.thedigital.gov.ua`, discovered via links only (paths are hash-sharded and cannot be enumerated [search]); their metadata comes from the linking page;
  - year-in-review microsites as documents.
- **kmu.gov.ua:** no per-ministry listing was seen [search]. Candidate discovery strategies for 0b: site search or filters (if any), sitemap, tags, or CDX prefix queries on `/news/` filtered by slug keywords in **both transliteration styles** (`mincifr`/`mintsyfr`, `cifrov`/`tsyfrov` [search]). Slug filtering only *discovers* candidates; the alias tagger on the content decides relevance, and the discovery path is recorded for the methods section.
- **Content:** full texts via trafilatura or site selectors, PDFs via pdfminer.six. Output: Documents (unverified, unscreened), suggested project links, event proposals, links to legal acts.
- **Priority:** annual reports and year-in-review items (doc_type `report`) go first, e.g. the 2025 year-in-review on kmu.gov.ua [search].
- **Duplicates** between thedigital.gov.ua and kmu.gov.ua are detected by content (§5.6); slugs are useless for this because the transliteration differs.

**C5 `wayback`** (S5): parameters verified in the CDX README [doc]
- **Earliest and latest capture per URL** in a single prefix query: `matchType=prefix&collapse=urlkey&showSkipCount=true&lastSkipTimestamp=true&output=json&fl=urlkey,timestamp,original,statuscode,mimetype`. The index is "usually sorted by url and date" [doc], so the first row per `urlkey` is the earliest capture; `lastSkipTimestamp` adds the last one. The skip counters are marked "experimental" in the docs, so this is checked in Phase 0b, with `limit=-1`/`fastLatest=true` as the fallback for single URLs.
- **Prefixes:** `diia.gov.ua/services/`, `thedigital.gov.ua/projects/`, `thedigital.gov.ua/news/`, and kmu.gov.ua news filtered with `filter=original:<regex>`. Large results are split with `showResumeKey=true`/`resumeKey`.
- **URL normalisation:** scheme, `www`, trailing slash and dot, query, case, percent-encoding.
- **Outputs:**
  - one `first_archived` event per subject (the earliest capture across URL variants, `date_basis = archive_upper_bound`, evidence = capture URL);
  - **the catalogue reconstructed at cut-off dates** (31 Dec of each year 2019–2025, plus 2022-02-23) from the nearest earlier capture (`/web/<timestamp>id_/<url>` returns the original bytes), parsed by layout-specific parsers;
  - documents that are gone from the live site (`via = wayback:<timestamp>`).
- **Throttling:** default 1 request per 5 s; long backoff on 429/503; CDX responses stored as snapshots.
- **Save Page Now:** optional and opt-in, only for new evidence, rate-limited.

**C6 `legal_acts`** (S6)
- **Scope:** only acts linked from collected pages (ministry pages, news, Diia service pages, kmu.gov.ua `/npas/` pages). No full search.
- **IDs normalised** (`/go/<id>` ↔ `/laws/show/<id>`).
- **Captured per act:** title, number, date, type, edition date, text. Stored as doc_type `legal_act`.
- **Events:** proposals for `legal_basis_adopted` / `governance_change`.
- **Open-data endpoints** (data.rada.gov.ua) are used only if confirmed in 0b.

**C7 `telegram`, `ckan`** (S7, optional)
- **Telegram:** web preview, paginated with `?before=<id>` [search]. Each post becomes a document (doc_type `announcement`), using the post's machine-readable timestamp [hypothesis].
- **CKAN:** datasets of the organisation `mincyfry` → Documents (statistics); figures become Indicators only after human review.

**C8 `manual`**
- **By URL:** fetched with the polite client, so a snapshot exists. **SSRF protection:** the host is resolved and loopback, private and link-local addresses are refused, re-checked on every redirect.
- **By upload:** PDF/DOCX/HTML/TXT, served back only as attachments (docs/API.md §6).
- Provenance `manual:<name>`.
<!-- COLLECTORS:END -->

### 5.3 Matching and auto-tagging

- **Aliases per project and service** are curated in the UI. When a single-word Ukrainian alias is added, `pymorphy3` suggests its inflected forms (e.g. nominative, genitive, accusative, instrumental); a person confirms them and they are stored explicitly. Matching itself is plain and deterministic (compiled patterns with word boundaries, after the text normalisation of §4.7).
- **Compound brand names** (`Дія.City`, `Дія.Бізнес`, `Дія.Освіта`, spellings with a space or dot, Latin/Cyrillic variants) are separate aliases. Overlapping matches are resolved **longest match first**, so a mention of `Дія.Бізнес` is not also counted as `Дія`.
- **Homonyms:** case-sensitive aliases and per-alias `exclude_patterns` (e.g. phrases in which `дія` means "action").
- **Output:** a `DocumentLink` with `origin = auto`, `state = suggested`, the matched aliases, a match count and a snippet. In the document view a person confirms or rejects it in one click. Only confirmed links count in analyses; suggested links count only in an explicitly labelled "auto" view.

### 5.4 Event proposals from texts

Phrases such as `запустили`, `запустило`, `запрацювала`, `запрацював`, `з'явилася послуга`, `стартувала`, `оновили`, `розширили`, `перейменували` and English equivalents (`launched`, `now available`, …) near an alias match produce **`create_event` proposals**, never facts. Each proposal carries the guessed subject, the guessed event type, the document date as `date_basis = inferred` (the announcement date is not automatically the event date), the quote and the document. A person edits and accepts it, or rejects it. The pattern list lives in the codebook (versioned) so the procedure can be reported in the methods section.

### 5.5 Dates

- **Order of preference for machine-readable dates:** API fields → `<time datetime>` → JSON-LD `datePublished` → `article:published_time` / other meta tags → URL or ID schemes (only if verified) → visible text. Sitemap `lastmod` is **not** a publication date.
- **Never guess.** A date without a year (e.g. `22 жов., 14:00` [user]) is stored verbatim in `date_text`, with no `date_start`, until a reliable source supplies the year: the same item from a machine-readable endpoint, an archived capture of a listing that shows the year, or kmu.gov.ua. Any inference rule (e.g. "the year is omitted only for the current year", combined with the capture date of an archived listing) is used only after the site convention has been verified, is marked `date_basis = inferred` and is documented.
- Ukrainian month names in all forms (`жовтня`, `жов.`, `жовтень`) are parsed by a tested helper; ambiguous input is rejected.

### 5.6 Idempotency, incremental runs, resumability

- **Stable keys:** canonical URLs and external IDs; entity IDs are never regenerated.
- **Incremental:** conditional requests; unchanged snapshots skip parsing; unchanged values create **no revision and no version bump**.
- **Duplicates:** canonical URLs plus content hash. Cross-site duplicates (the same press release on thedigital.gov.ua and kmu.gov.ua) are detected by normalised title, date ± 1 day and text similarity. They become a `possible_duplicate` proposal; both documents are kept, and the team decides whether to merge them or link them as duplicates.
- **Acceptance test (Definition of Done 3):** running a collector twice against the same fixtures yields 0 new entities, 0 new revisions and 0 new proposals on the second run.

### 5.7 Fixtures

- Tests run **without network** against fixtures in `backend/tests/fixtures/<collector>/` (trimmed HTML/JSON plus a small JSON file with status and headers).
- Fixtures are recorded with `mdt fixtures capture <source>`: a small, fixed list of URLs, fetched politely. This needs network access to the source hosts, either in this development environment or once on the target server, with the result committed.
- Fixtures from CC BY sources are attributed. Pages from other sources are kept as minimal excerpts.

---

## 6. Versioning, provenance and reconciliation

### 6.1 Revisions

- **All writes go through one domain function:** `apply_change(entity, changes, actor, channel, note, expected_version)`. It validates, computes the diff against the current state, and does nothing if the diff is empty. Otherwise it bumps `version` and writes the entity and the revision (full snapshot plus field-wise diff) **in one transaction**, then recomputes derived values if needed.
- **Append-only:** SQLite triggers abort every `UPDATE` and `DELETE` on `revision`.
- **Covered:** all curated entities, vocabulary terms, relations, participations, evidence, comment edits, document screening and tags, saved views.
- **Restore** a version = `apply_change` with that version's snapshot, `channel = restore`, `restored_from = <revision>`. This creates a new revision; history is never rewritten.
- **Diff between any two versions** is computed from their snapshots, field by field; long texts get word-level diffs in the UI.
- **Recent changes:** a global feed over `revision`, filterable by author, entity type, channel and period.

### 6.2 Field provenance

`field_meta[<field>] = {src, by, at, locked, evidence_id?, verified}`

- `src`: `seed` | `collector:<name>@<run_id>` | `manual:<name>` | `import:<file>`. A restore keeps the original `src`.
- `by`: who wrote the value (a person, or `collector:<name>`).
- `locked`: becomes `true` as soon as a person sets, accepts, imports, restores or seeds the value. From then on collectors can only propose.
- `verified`: unverified / verified / disputed per field. Clicking the badge creates a revision.
- **UI:** a badge per field (`seed`, `collector`, `manual`, `import`) plus a lock icon and a verification dot; the tooltip shows the run, snapshot or evidence and the time.

### 6.3 Optimistic locking and the conflict dialog

- Every editable resource carries `version`. A save sends the base version (`If-Match`).
- On a mismatch the server answers **409** with the base snapshot (taken from the revisions), the current snapshot and the submitted changes. The conflict dialog shows a three-way comparison per field ("base / theirs / yours"). Fields only one side changed can be taken over with one click; **nothing is saved silently**.
- Bulk edits send one version per row; conflicts are reported per row and the other rows are saved.

### 6.4 Soft delete, trash, merge

- **Delete** sets `deleted_at` and creates a revision. Deleted entities are hidden by default; a trash view per type allows restoring them.
- **Dependent entities:** deleting a project with services asks whether to soft-delete them too (shared `batch_id`) or leave them in place, flagged as orphans.
- **Merging duplicates:** choose the survivor and pick values field by field. All references (services, events, evidence, links, participations, relations, comments, observations) are repointed, each with its own revision. A MergeLog entry makes the merge reversible.
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

### 6.6 Proposal lifecycle

- `dedup_key = hash(kind, subject, field, normalised proposed value)`. An identical open proposal is not duplicated (only `last_run` is updated). A **rejected** proposal with the same key is not opened again; a different new value opens a new proposal.
- When the source value changes again, older open proposals for the same field become `superseded`.
- **Accept** applies the value (keeps the collector `src`, sets `by` to the person and `locked = true`). **Edit & accept** stores `manual:<name>` with a reference to the proposal. **Reject** requires a short reason. Bulk actions are available.

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

### 7.1 Navigation and author attribution

There is no login. Every revision still needs an author, so the app asks "Who are you?" on first visit (team list from `TEAM_MEMBERS`, editable in the UI, or free text). The name is stored in the browser and sent with every write as the `X-Author` header. This is **attribution, not authentication**. On an isolated server that is enough, and the README states it clearly.

```
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ MDT Portfolio │ Dashboard  Projects  Services  Events  Documents  Organizations  Timeline   │
│               │ Review (n)  Changes  Runs  Codebook  Releases     [ Search everything… ] [👤 Name ▾] │
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
│ Name (en)        Example Project       seed 🔒 ● verified    │ │ ▸ field launch_date · Name (open)│
│ Ministry pages   /projects/business/…  collector ○           │ │   └ reply · Name                 │
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
│ Screening [included ▾]    ││ example-b  confirmed (Name)             │└──────────────────────────────┘
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
     current  (manual 🔒 Name, 2026-11-02): «…»
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

### 7.5 Security without login

- **DNS rebinding:** a Host-header allowlist (`ALLOWED_HOSTS`). Without it, a malicious website could rebind its domain to the internal address and read or write data in the name of a team member's browser.
- **Cross-site writes:** all writes require JSON plus the custom `X-Author` header and a same-origin `Origin`/`Sec-Fetch-Site`. Browsers send a preflight for such requests, and since no CORS is allowed, the request fails.
- **Stored XSS:** Markdown is rendered and sanitised server-side (`nh3`). Document texts are always rendered as plain text and search highlights as React elements. A strict **Content-Security-Policy** (`default-src 'self'`, no inline scripts) adds a second line of defence.
- **Uploads:** size limit, file type checked by content (magic bytes), stored content-addressed, served with `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`.
- **Input validation** with Pydantic (lengths, vocabulary codes, URL schemes `http`/`https` only).
- **Secrets** only in `.env` (`.env.example` in the repo). Lockfiles for Python and npm. Delete is soft; hard purge is CLI-only.

---

## 8. Operations

- `docker compose up -d` starts the single `app` service: port `${HOST:-127.0.0.1}:${PORT:-8080}:8080`, volume `./data:/app/data`, bind mount `./releases`, healthcheck, `restart: unless-stopped`. The image is multi-stage (Node build → slim Python runtime), runs as a non-root user and carries the git commit as a label. On start it runs `mdt db upgrade`.
- **Team access** (README): via VPN (e.g. WireGuard or Tailscale), an SSH tunnel, or a reverse proxy (Caddy or nginx) with TLS and preferably basic auth or an IP allowlist in front. The app itself stays bound to 127.0.0.1.
- **Scheduled jobs:** collector runs weekly by default (cron in `.env`, visible in the UI), backup daily.
- **Makefile:** `dev`, `test`, `lint`, `typecheck`, `build`, `up`, `down`, `logs`, `migrate`, `seed`, `collect SOURCE=…`, `import FILE=… [DRY_RUN=1]`, `fixtures SOURCE=…`, `release NAME=…`, `backup`, `restore FILE=…`, `codebook`, `check`.

## 9. Quality and tests

- **Backend:** ruff, mypy; pytest for parsers (offline fixtures), the HTTP client (throttling, robots, conditional GET, backoff, block detection; with a fake transport), the domain logic (revision, empty-diff no-op, restore, conflict 409 with three-way payload, locks, proposals including dedup and rejection memory, disappearance only after complete runs, derived-field rules including precision edge cases at both cut-off dates), the API, the importer (mapping, dry run) and release manifests.
- **Frontend:** ESLint, tsc; Vitest for filter-URL round trips, diff and conflict dialogs.
- **E2E smoke tests** (Playwright, Chromium): start the app on a seeded DB → filter the projects table → edit with a note → history and diff → restore → provoke a conflict (two browser contexts) → comment and resolve.
- **CI** (GitHub Actions): lint, type checks and tests for backend and frontend, plus a Docker build. Network-dependent tests are excluded by marker.

---

## 10. Phase plan

| Phase | Content | Done when |
|---|---|---|
| **0 (this)** | Paper read; environment checked; plan, SOURCES and CODEBOOK drafts; open questions | Approval |
| **0b — source checks** | Once there is network access (this environment or the server): for each source robots.txt, licence footer, sitemaps/RSS, JSON endpoints (Playwright XHR log on 1–2 pages), pagination, date formats, archive depth (binary search over listing pages), CDX coverage. **Budget:** ≈ 150 requests overall, ≤ 1 request/s per host. Fixtures captured. `docs/SOURCES.md` and the collector strategy (§5.2) finalised. | Every `[hypothesis]` and `[search-summary]` item for S1–S5 is confirmed, refuted or documented as not determinable; fixtures committed |
| **1 — skeleton** | Repo structure, `CLAUDE.md`, tooling; models, Alembic migrations, FTS, revision triggers; `apply_change` with diff, no-op, restore; field provenance and locks; optimistic locking (409 + payload); soft delete and trash; comments (threads, status, Markdown, revisioned edits); vocabularies (YAML → DB) and seed (19 + 1 projects); API with server-side filters, sort, pagination and facets; UI tables (filters, column chooser, URL state, saved views, bulk edit, CSV/XLSX export of the current view), detail pages with edit, badges, history, diff, restore, conflict dialog, comments; Recent changes; Docker and compose | Definition of Done 1, 2, 4 and 6 on seed data; tests green |
| **2 — data acquisition** | `PoliteHttpClient`, snapshot store, CollectorRun and FetchLog, run queue and scheduler hook; reconciler, proposals and review inbox; SourceObservations and "possibly discontinued"; collectors C1–C5; alias tagging and event proposals; merging duplicates; importer (CSV/XLSX mapping + dry run; `defusedxml` installed against XML bombs in untrusted XLSX); manual documents (URL with SSRF protection, upload); collector-run view | Definition of Done 3 and 5; idempotency test green |
| **3 — analysis** | Document view with evidence capture; Organizations, Participations, Components, Relations (D2–D4); Indicators; timeline (SVG/PNG); dashboard; all exports (dataset, QDA corpus, codebook); C6 (legal acts) and C7 (Telegram, CKAN) where useful | Definition of Done 7 (except releases) |
| **4 — operations** | `make release` with manifest and tag; releases view; backups with rotation and restore test; schedules; CI; README, DATA_MODEL, CODEBOOK (generated), SOURCES, METHODS | Definition of Done 1–8 |

Phase 1 does not depend on the source checks and can start right after approval; Phase 0b can run before or alongside it.

---

## 11. Risks and mitigations

<!-- RISKS:BEGIN -->
| # | Risk | Effect | Mitigation |
|---|---|---|---|
| R1 | No network access to sources in the development environment (confirmed) | No source checks, no fixtures | Phase 0b after the allowlist is opened, or fixture capture on the server |
| R2 | gov.ua sites block or throttle foreign IPs or bots. This is known for some state services (the State Tax Service blocks foreign IPs [search]); no evidence for the target hosts | Gaps; runs break off | Test from the target server first (Phase 0b); block detection → `partial` run, log, report; Wayback fallback; no circumvention |
| R3 | thedigital.gov.ua is a beta relaunch [user]: structure changes, dates without year, uncertain archive depth | Parser breakage, missing dates | Prefer structured endpoints; tests against fixtures; dates never guessed; kmu.gov.ua and Wayback for 2019–2022 |
| R4 | Diia app services are only partly on the web [user] | Incomplete service inventory | App services enter as proposals from announcements; the gap is stated in METHODS |
| R5 | Wayback rate limits and gaps | Slow runs, missing upper bounds | Strong throttling, caching, CDX `collapse`; archive dates are upper bounds only |
| R6 | Catalogue HTML changed over the years | Historic captures need era-specific parsers | Parsers versioned per layout era with fixtures for each era; scope limited to the yearly cut-off dates and 2022-02-23 |
| R7 | Homonyms and inflection in auto-tagging (`дія` = action) [local] | False or missed tags | Curated alias forms, case-sensitive brand aliases, exclusions, suggested state, one-click review |
| R8 | Portfolio changes (PlayCity, 19 vs. 20 entries) [user] | Unclear unit of analysis | Listing date as an observation; governance_change events; `in_paper_scope` with reason |
| R9 | Training-knowledge leakage into the data | Unverifiable values | No writes without author and provenance; seed limited to §3 of the assignment; reviews |
| R10 | Copyright of full texts from third-party media | Publishing risk | Releases without non-open full texts; QDA export internal only |
| R11 | SQLite concurrency | Lock errors | WAL, `busy_timeout`, serialised runs, small transactions |
| R12 | No authentication | Spoofed author names; exposure if the server becomes reachable from outside | Binding to 127.0.0.1, VPN or proxy auth, Host allowlist, CSRF protection, CSP; README warning |
| R13 | Interview transcripts (later) contain personal data | Data protection | Not in v1; if added later: a separate protected document class, excluded from releases (decision for the team) |
| R14 | Responsibilities change during the observation window (PlayCity coordination, Brave1 management, leadership and mandate of the ministry in 2025–2026 [search]) | Portfolio statements in the paper go stale | Participations with periods, governance_change and context events, statements tied to a release date (§13) |
| R15 | Wayback rate limits are undocumented [doc] | Blocks or bans | 1 request per 5 s by default, backoff, cached CDX responses, no parallelism |
| R16 | Strategies and brands listed as "projects" (WINWIN as a strategy [search-summary], European Integration as a policy workstream [search-summary]) | Inconsistent unit of analysis | Capture everything, code `unit_type` (product/service, platform, programme, strategy/policy area, organisation) and decide scope with a reason (D-1) |
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
| D-5 | Release content (full texts, comments, author names) | Without comments, proposals or non-open full texts; with team author names |
| D-6 | Service granularity (what is a sub-service? app features vs. portal services) | Rules in CODEBOOK (draft) |
| D-7 | Policy domains and beneficiaries | COFOG divisions as the top level + subcodes from the data (draft in CODEBOOK) |
| D-8 | May collectors create Services directly (unverified)? | Yes for catalogue sources; projects only via proposal |
| D-9 | Release via UI button with git access? | No (§6.7); UI preview + CLI |
| D-10 | Basis for `period`/`war_trajectory` at project level: launch of the initiative or entry into the ministry's portfolio? | Compute both; launch as default, portfolio entry as an alternative view |
| D-11 | Add `unit_type` to Project (product/service, platform, programme, strategy/policy area, organisation)? | Yes (R16); the vocabulary draft is in CODEBOOK |
| D-12 | Add the Digital State UA catalogue and the Diia service guide as sources (after 0b)? | Yes if 0b confirms structured access; as cross-check sources, not as the portfolio definition |
<!-- DECISIONS:END -->

---

## 13. Notes for the paper (Hinweise fürs Paper)

<!-- PAPER-NOTES:BEGIN -->
**Status:** these notes concern the project list and responsibilities. They come from the assignment [user], the paper [paper] or search results [search]/[search-summary]. **None of them has been checked against the primary source yet, and none has been entered into the data.** Each one says what has to be verified (Phase 0b/2). The full evidence list with URLs is in `docs/SOURCES.md` § "Leads for the paper".

**N1 — Define the unit of analysis by listing and date.**
- The paper counts 19 projects; the ministry's page shows 20 [user]. Missing in the paper: "Євроінтеграція" (European Integration).
- Its category `progress` is titled "Досягнення" (achievements) [search]. The search summary describes it as continuing the EU-integration course, gradual integration into the EU Digital Single Market and alignment with EU digital law [search-summary]. That makes it a policy workstream rather than a digital product [hypothesis].
- WINWIN is described as a national innovation strategy [search-summary], so it too may not be a single product.
- The search index also contains a URL variant of the European Integration entry without `/progress/` [search], so the listing itself changes.
- *Suggestion:* define the portfolio as "initiatives listed on thedigital.gov.ua/projects on <date> (dataset release X)", report additions and removals over time, and code each entry's `unit_type` (D-1, D-11).

**N2 — PlayCity: responsibility changed during 2026** (all to verify against the resolutions)
- Cabinet resolution 314-2025-п set up the central executive body for gambling and lotteries [search]. The date 21.03.2025 is [search-summary], consistent with the suffix of the kmu.gov.ua URL.
- Interfax-Ukraine: "Кабмін вивів PlayCity із сфери координації Мінцифри" (the Cabinet removed PlayCity from the ministry's sphere of coordination) [search; date not shown]. Forbes Ukraine reported that the Cabinet resubordinated PlayCity to itself (15.05.2026, date from the URL) [search]. The legal act is reportedly resolution №613 of 13.05.2026 [search-summary].
- In September 2026, resolution №1133 of 17.09.2026 reportedly amended PlayCity's regulation (coordination by the Prime Minister) [search-summary]. A related PDF on kmu.gov.ua and a trade-press article exist [search].
- The interview the assignment refers to: Forbes Ukraine with minister Oksana Ferchuk, 11.08.2026 [search]. It contains the quote "we do not influence the actions of this agency, but we are responsible for policy development" [search-summary]. The Interfax articles citing this interview found so far concern Brave1 [search]; the piece with the PlayCity passage still has to be identified.
- PlayCity's 2026 budget-programme passport is titled as approved by an order of the Ministry of Digital Transformation [search], so the ministry may still be the main budget administrator [hypothesis]. "Responsibility" thus has several dimensions: coordination, budget and policy.
- PlayCity's own website reportedly still names coordination through the minister [search-summary]. Official pages lag behind legal changes, so cite them with the retrieval date.
- *Suggestion:* once verified, describe PlayCity with dates and the Cabinet resolutions as primary sources (e.g. "set up in 2025 under the ministry's coordination; since 2026 coordinated by the Prime Minister; the ministry keeps policy responsibility"). In the data: governance_change events and Participations with periods.

**N3 — The leadership and mandate of the ministry changed in 2025–2026** (context for the post-invasion period; to verify)
- A ministry news title "Зберігаємо темп: Олександр Борняков очолив Мінцифру" shows an interim head [search].
- Interfax reports that the Verkhovna Rada appointed Oksana Ferchuk [search]; the Forbes Ukraine profile is dated 17.07.2026 [search]. The previous minister left in January 2026 [search-summary].
- Resolution 214-2026-п replaces the title "First Vice Prime Minister – Minister of Digital Transformation" with "Minister of Digital Transformation" in a working group [search]. Whether the post lost its vice-PM rank is [hypothesis].
- Amendment 386-2025-п adds AI and semiconductor development to the ministry's regulation [search].
- *Suggestion:* the period "after 24.02.2022" is not institutionally homogeneous. State the end of the observation window explicitly (release date) and mark these changes as context events on the timeline.

**N4 — "In the ministry's portfolio" does not mean "developed by the ministry"** (for D3; to verify)
- **UNITED24** was launched "at the initiative of the President" [search].
- **Ukrainian Startup Fund:** a government decision transfers the Innovation Development Fund "into the management of the ministry" [search]. According to the search summary, this fund is the legal entity behind USF, and the transfer happened at the end of 2022 [search-summary]. If confirmed, this is a pre-existing organisation entering the portfolio, not a launch.
- **CodeUA** was launched by the ministry [search], with the Lviv IT Cluster and USAID support [search-summary].
- **UNITED24 Media:** the ministry announced its creation [search].
- **Brave1** was launched in April 2023 [search]. One report says it would move to the Ministry of Defence [search]; in August 2026 it "remains under the ministry's management" [search].
- **Digital State UA** was launched by the ministry [search] and is itself a catalogue of digital projects [search].
- *Suggestion:* code the ministry's role per project with dates (initiator, owner, operator, partner, coordinator, regulator), and distinguish **launch** from **portfolio entry** (`portfolio_entry`, D-10). This matters for the pre/post comparison and for the distinction between adaptation and new development (Yoo et al. 2012).

**N5 — Ministry categories are not the paper's clusters** [user]
- The site uses `technologies`, `business`, `regions`, `education`, `progress`; Diia.City appears twice; Diia.Center sits under `regions`.
- *Suggestion:* present the seven clusters as the authors' classification with coding rules (CODEBOOK) and report the mapping to the ministry categories in an appendix table generated from a release.

**N6 — Dating rules for the methods section** (§4.4)
- Archive captures are upper bounds.
- Dates whose precision straddles 24.02.2022 cannot be assigned to a period.
- `prewar_unchanged` means "no modification recorded up to release X".
- METHODS.md will provide ready-made wording.

**N7 — Claims without evidence in the current draft** [paper]
- The descriptions of PlayCity (tax revenue for the Armed Forces) and Brave1 have no citation yet.
- The platform will supply citable documents with retrieval dates and archive links.

**N8 — High-value documents found** (to retrieve in Phase 2)
- The ministry's 2025 year-in-review on kmu.gov.ua ("…підсумки Мінцифри у 2025 році") [search].
- The microsites `2025.thedigital.gov.ua` ("Підсумки року роботи Мінцифри 2025"), `2years.` and `5years.thedigital.gov.ua` [search].
- Annual reports and work-plan reports on `storage.thedigital.gov.ua` (e.g. results report 2022, work plan 2024) [search-summary].
- **KIIS/UNDP 2026:** the report page exists at `undp.org/node/565986` [search]. The URL in the paper's reference list did not appear in the search results, so check that it resolves.

**N9 — Cite web pages with retrieval date and archived copy**
- "Ministry of Digital Transformation of Ukraine (n.d.). Ministry" points to a page of a site in beta relaunch whose content changes.
- The platform stores the snapshot and the archive URL for every cited page.

**N10 — Further initiatives to screen** (leads only, for D-1; added as proposals after verification)
- A national web platform for administrative service centres (may overlap with Diia.Center) [search].
- The EU-funded programmes DT4UA and EU4DigitalUA [search].
- A Council of Europe child-protection project the ministry joined [search].
- From media reports only: the e-democracy platform "ВзаємоДія", a state AI platform and a unified platform for state registries [search].
- The subdomain `ai.thedigital.gov.ua` [search].
<!-- PAPER-NOTES:END -->

---

## 14. Open questions

<!-- QUESTIONS:BEGIN -->
Also asked in the session (in German).

1. **Contact e-mail for the User-Agent:** ideally a project or functional address. It goes into `.env` only, never into the repository.
2. **Server:** operating system and version; Docker and Compose versions; CPU, RAM, free disk; **location/hosting (country)**, relevant for possible geo-blocking; outbound internet access; team access via VPN, reverse proxy (which?) or SSH tunnel; off-host backup target.
3. **Existing table:** does the dataset mentioned in the paper exist? Format, columns, who collected it, from which sources and when? If yes: upload it here or put it into `data/import/` on the server; the importer gets a mapping and a dry run.
4. **Network for Phase 0b:** open the source domains for this cloud environment (list in the session), or run the exploration and fixture capture on the server?
5. **Team:** names for the author picker; how many people edit at the same time?
6. **Git:** may the Phase 0 commit be pushed to the working branch `claude/sharp-heisenberg-inzace`? (The cloud container is ephemeral; nothing is pushed without approval.)
7. **Decisions D-1 to D-12** (§12): can be answered later; the defaults above apply until then.
<!-- QUESTIONS:END -->
