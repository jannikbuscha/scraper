# HTTP API

> **Status:** v1 contract for Phase 1, revised 2026-10-28 after a five-lens contract review. Base path `/api`, JSON only. Field names, types, entity types, normalisation and write semantics come from `docs/DATA_MODEL.md`.

## 1. Conventions

### 1.1 Requests

**Writes** (`POST`, `PATCH`, `PUT`, `DELETE`) require all of the following:
- **`X-Author`:** the author name, percent-encoded UTF-8 (`encodeURIComponent(name)`). Decoded and trimmed, it must be 1–100 characters without control characters. Reserved names are rejected (DATA_MODEL §7: `seed`, `system`, prefixes `collector:`, `import:`, `manual:`). Missing → `400 author_required`; invalid → `400 author_invalid`. This is attribution, not authentication.
- **`Content-Type: application/json`.** Otherwise `415 unsupported_media_type`.
- **Body size:** at most 1 MB. Otherwise `413 payload_too_large`.
- **Same origin:**
  - if an `Origin` header is present, its host and port must equal the request's `Host` header, after normalising default ports (80 for http, 443 for https) and lowercasing;
  - if `Sec-Fetch-Site` is present, it must be `same-origin` or `none`;
  - otherwise `403 cross_origin_forbidden`.
  - Browsers send a preflight for cross-origin JSON requests with custom headers, and the server answers no CORS, so cross-site writes are blocked twice.

**Host allowlist** on every request, against DNS rebinding:
- the hostname of the `Host` header (port stripped, case-insensitive) must be in `ALLOWED_HOSTS`, otherwise `400 invalid_host`;
- `*` disables the check (documented as unsafe).

### 1.2 Error format

All errors use one envelope:

```json
{"error": {"code": "validation_error", "message": "Human-readable summary", "details": {"name_en": ["At least one of name_en/name_uk is required"]}}}
```

| Status | `code` | `details` |
|---|---|---|
| 400 | `validation_error` | `{field: [messages]}`. Request-model errors are converted to this format; there is no 422. |
| 400 | `author_required`, `author_invalid`, `invalid_host`, `bad_filter`, `bad_sort`, `evidence_required` | — |
| 403 | `cross_origin_forbidden` | — |
| 404 | `not_found` | — |
| 409 | `conflict` | the payload from DATA_MODEL §6.5 |
| 409 | `entity_deleted` | `{deleted_at, deleted_by}` |
| 409 | `invalid_state` | `{state}` (e.g. deleting a deleted row) |
| 409 | `has_dependents` | `{"service": 12}` |
| 409 | `unique_violation` | `{field}` |
| 409 | `reference_deleted` | `{field, id, type}` |
| 409 | `not_deletable` | — (vocabulary terms) |
| 409 | `fixed_code` | — (fixed vocabulary codes, DATA_MODEL §7) |
| 413 | `payload_too_large` | — |
| 415 | `unsupported_media_type` | — |
| 500 | `internal_error` | — |

Messages never contain stack traces, SQL or file paths.

### 1.3 Other conventions

- **Timestamps** are strings in the exact format of DATA_MODEL §1.1 (`YYYY-MM-DDTHH:MM:SS.ffffffZ`); the API never reformats them. **Partial dates** use the canonical strings.
- **No CORS headers.** The SPA is served from the same origin.
- **Successful writes may return `warnings`** (e.g. restored inactive codes): an array of `{code, message, field}`.

## 2. Entity types and item representation

`{type}` is one of:
- `project`, `service`, `event`, `document`, `organization` (also with a table view in the UI);
- `participation`, `component`, `relation`, `indicator`, `evidence`, `vocabulary_term`, `saved_view`.

An unknown type returns `404 not_found`. Comments have their own endpoints (§3.3).

**Item** (list and detail responses):

```json
{
  "id": "prj_01JBX…",
  "type": "project",
  "label": "Diia",
  "version": 3,
  "created_at": "2026-10-28T17:00:00.000000Z", "created_by": "seed",
  "updated_at": "2026-10-29T08:12:00.000000Z", "updated_by": "Anna",
  "deleted_at": null, "deleted_by": null, "merged_into": null,
  "fields": {"slug": "diia", "name_en": "Diia", "name_uk": "Дія", "verification_status": "unverified", "notes": null, "…": "…"},
  "field_meta": {"name_en": {"src": "seed", "by": "seed", "at": "…", "locked": true, "verified": "unverified", "evidence_id": null, "restored_from_version": null}},
  "derived": {
    "launch": "2020-02", "launch_start": "2020-02-01", "launch_end": "2020-02-29", "launch_precision": "month", "launch_basis": "stated_in_source", "launch_event_id": "evt_…",
    "existed_by": null, "existed_by_event_id": null, "existed_before_invasion": true,
    "period": "pre_invasion", "period_reason": null,
    "war_trajectory": "prewar_unchanged", "trajectory_reason": null, "trajectory_event_id": null,
    "portfolio_entry": null, "portfolio_entry_participation_id": null,
    "computed_at": "…"
  },
  "virtual": {"open_comments": 1, "comment_count": 4},
  "refs": {"project_id": {"id": "prj_…", "type": "project", "label": "Diia", "deleted": false}},
  "search_snippet": null
}
```

- **`fields`** holds every registry field that is neither derived nor virtual, including system fields such as `canonical_url`. It never contains `seed_key`.
- **`derived`** is present for project and service.
- **`virtual`** holds `open_comments` and `comment_count` for every type, plus `project_in_paper_scope` (service), `subject_in_paper_scope` (event) and `linked_in_paper_scope` (document).
- **`refs`** gives the label of every non-null `ref` field, of derived event and participation IDs and, for documents, of every link subject (`refs["links"] = {subject_id: {…}}`).
- **`search_snippet`** is set for documents when the list query has `q` (FTS `snippet()` around the hit in the text; plain text, matches marked by the characters `«` and `»`).
- **`label`** rules:
  - project, service, organization, component: `name_en` → `name_uk` → `slug`/`id`;
  - event: `<event_type label> · <subject label> · <date or "undated">`;
  - document: `title`;
  - participation: `<organization> · <role label> · <subject>`;
  - relation: `<from> <relation_type label> <to>`;
  - indicator: `<metric>: <value> <unit>`;
  - evidence: `<target> · <subject>`;
  - vocabulary term: `<vocabulary>:<code>`;
  - saved view: `name`.
- **Document detail** responses add `fields.text` (from `document_text`); list responses omit it.

## 3. Endpoints

### 3.1 Meta

| Method and path | Response |
|---|---|
| `GET /api/health` | `{"status": "ok", "version": "<app version>", "schema_revision": "<alembic head>"}` |
| `GET /api/meta` | see below |
| `GET /api/vocab` | `{"vocabularies": [{"name", "label", "description", "multi", "fixed_codes", "terms": [{"id", "code", "label_en", "label_uk", "definition", "include_note", "exclude_note", "examples", "sort_order", "active", "replaced_by", "attributes", "version", "usage_count"}]}]}`. `usage_count` = non-deleted entities whose fields reference the code. |
| `GET /api/stats` | `{"entities": {"project": {"total": 20, "unverified": 20, "deleted": 0}, "…": {}}, "open_comments": 3}` |

`GET /api/meta` returns:

```json
{
  "app_version": "0.1.0",
  "team_members": ["…"],
  "focal_org_id": "org_…",
  "parameters": {"ministry_founded": "2019-08-29", "full_scale_invasion": "2022-02-24"},
  "groups": [{"key": "basics", "label": "Basics"}, {"key": "classification", "label": "Classification"}, {"key": "wartime", "label": "Wartime"}, {"key": "framework", "label": "Framework D1–D4"}, {"key": "sources", "label": "Sources & Evidence"}, {"key": "system", "label": "System"}],
  "vocabularies": {"paper_cluster": {"label": "Paper cluster", "multi": false, "fixed_codes": false}},
  "entity_types": {
    "project": {
      "label": "Project", "label_plural": "Projects", "prefix": "prj", "table_view": true,
      "default_sort": "paper_cluster,name_en",
      "fields": [{"name": "slug", "label": "Slug", "type": "slug", "vocabulary": null, "ref_types": null, "group": "basics", "required": true, "editable": true, "create_only": false, "system": false, "tracked": true, "derived": false, "virtual": false, "filter": "text", "sortable": true, "in_list": true, "bulk_editable": false, "help": "…"}],
      "quick_filters": [
        {"key": "unverified", "label": "Unverified", "kind": "toggle", "query": "f.verification_status=in:unverified"},
        {"key": "open_comments", "label": "Open comments", "kind": "toggle", "query": "f.open_comments=range:1.."},
        {"key": "no_start_date", "label": "No start date", "kind": "toggle", "query": "f.launch=empty:true"},
        {"key": "in_scope", "label": "In paper scope", "kind": "toggle", "query": "f.in_paper_scope=eq:true"},
        {"key": "period", "label": "Period", "kind": "chips", "field": "period"}
      ]
    }
  }
}
```

**Default sort per type:**
- project `paper_cluster,name_en`;
- service `project_id,name_en`;
- event `-date`;
- document `-published`;
- organization `name_en`;
- participation `organization_id`;
- component `name_en`;
- relation `relation_type`;
- indicator `-as_of`;
- evidence `-created_at`;
- vocabulary_term `vocabulary,sort_order`;
- saved_view `name`.

**Quick filters per type:**
- **project:** unverified, open comments, no start date (`f.launch=empty:true`), in paper scope, and the **period chips** (kind `chips` on the derived `period`: `f.period=in:<codes>`, offering the four period codes including `unknown`).
- **service:** the same, with `f.project_in_paper_scope=eq:true` for scope.
- **event:**
  - unverified, open comments, undated (`f.date=empty:true`), in paper scope (`f.subject_in_paper_scope=eq:true`);
  - period presets (kind `preset`) with full queries: `f.date=within:..2019-08-28`, `f.date=within:2019-08-29..2022-02-23`, `f.date=within:2022-02-24..`;
  - dates that straddle a cut-off match no preset.
- **document:** unverified, open comments, unscreened (`f.screening_status=in:unscreened`), in paper scope (`f.linked_in_paper_scope=eq:true`), period presets on `published` like events.
- **organization:** unverified, open comments.

**`bulk_editable`** is true for editable, non-create-only fields of type `vocab`, `vocab_list` and `bool`, including `verification_status`.

### 3.2 Generic entity endpoints

| Method and path | Body | Response |
|---|---|---|
| `GET /api/entities/{type}` | — (query grammar §4) | `{"items": [Item], "total": n, "page": 1, "page_size": 50}` |
| `GET /api/entities/{type}/facets?field=<name>&…` | — | `{"field": "kind", "values": [{"value": "e_service", "label": "E-service", "count": 12}], "empty_count": 3}`. All filters apply except the one on `field`. Vocabulary values include zero counts for active terms and are ordered by `sort_order`. Refs are labelled. Allowed for fields with filter `multiselect`, `bool` or `ref`. |
| `GET /api/entities/{type}/export?format=csv\|xlsx&cols=a,b&…` | — | file download, §5 |
| `POST /api/entities/{type}` | `{"data": {…}, "note": "…"}` | `201 {"item": Item, "revision_id": n, "warnings": []}` |
| `GET /api/entities/{type}/{id}` | — | `{"item": Item}` (deleted items are returned too, with `deleted_at` set) |
| `PATCH /api/entities/{type}/{id}` | `{"expected_version": 3, "changes": {…}, "note": "…"}` | `{"item": Item, "changed": true, "revision_id": n, "warnings": []}`; a no-op returns `changed: false`, `revision_id: null` |
| `POST /api/entities/{type}/{id}/delete` | `{"expected_version": 3, "note": "…", "cascade": false}` | `{"item": Item, "revision_id": n, "batch_id": "…"}` |
| `POST /api/entities/{type}/{id}/undelete` | `{"expected_version": 4, "note": "…", "cascade": false}` | `{"item": Item, "revision_id": n, "batch_id": "…"}` |
| `POST /api/entities/{type}/{id}/verify-field` | `{"expected_version": 3, "field": "name_en", "status": "verified", "evidence_id": "evd_…", "note": "…"}` | `{"item": Item, "revision_id": n}` |
| `GET /api/entities/{type}/{id}/revisions?page=&page_size=` | — | `{"items": [RevisionSummary], "total": n, "page", "page_size"}`, newest first |
| `GET /api/entities/{type}/{id}/revisions/{version}` | — | `{"revision": RevisionFull}` |
| `GET /api/entities/{type}/{id}/diff?from=2&to=5` | — | `{"from": 2, "to": 5, "diff": {"fields": {…}, "meta": {…}, "state": {…}}, "not_recorded": ["field", …]}`; `from=0` = the empty state before creation |
| `POST /api/entities/{type}/{id}/restore` | `{"expected_version": 5, "version": 2, "note": "…"}` | `{"item": Item, "changed": true, "revision_id": n, "warnings": [], "skipped_fields": ["…"]}` |
| `POST /api/entities/{type}/bulk` | `{"items": [{"id": "…", "expected_version": 3}], "set": {"status": "active"}, "add": {"channels": ["app"]}, "remove": {}, "note": "…"}` | `{"batch_id": "…", "results": [{"id": "…", "status": "updated\|unchanged\|conflict\|entity_deleted\|error", "version": 4, "error": null}]}` |

Notes:
- **Revision records:**
  - `RevisionSummary` = `{id, version, at, author, channel, note, changed_fields, restored_from, batch_id}`;
  - `RevisionFull` = `RevisionSummary` + `{snapshot, diff, schema_revision}`;
  - `changed_fields` as defined in DATA_MODEL §6.3.
- **Body keys:** `data` and `changes` use registry field names in API representation. Unknown, derived, virtual, system or non-editable fields, and create-only fields in `changes`, → `400 validation_error`.
- **Optimistic locking:** `expected_version` is required for `PATCH`, `delete`, `undelete`, `verify-field`, `restore` and per bulk item. A mismatch → `409 conflict` with the `action` set. Writes to a deleted row → `409 entity_deleted`.
- **Bulk:**
  - the whole request → 400 if a field is not `bulk_editable`, appears in more than one of `set`/`add`/`remove`, `add`/`remove` targets a non-list field, or an ID is duplicated;
  - changing `in_paper_scope` requires `scope_note` in `set`;
  - setting `verification_status` to `verified`/`disputed` requires `note`.
- **`note`** is optional (≤ 2 000 characters) unless a rule above requires it, and is stored on the revision.

### 3.3 Comments

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/comments?subject_id=<id>` | optional `status`, `field`, `deleted=exclude\|only\|include` | `{"threads": [{"root": Comment, "replies": [Comment]}]}`; newest root first, replies oldest first |
| `GET /api/comments?status=&entity_type=&author=&q=&deleted=&page=&page_size=` | without `subject_id` | `{"items": [{"root": Comment, "reply_count": n, "last_activity_at": "…"}], "total", "page", "page_size"}` |
| `GET /api/comments/{id}` | — | `{"comment": Comment}` |
| `POST /api/comments` | `{"subject_id", "field": null, "parent_id": null, "body_md"}` | `201 {"comment": Comment}`; roots start `open` |
| `PATCH /api/comments/{id}` | `{"expected_version", "body_md", "note"}` | `{"comment": Comment}` |
| `POST /api/comments/{id}/resolve` · `/reopen` | `{"expected_version"}` | `{"comment": Comment}` (roots only) |
| `POST /api/comments/{id}/delete` · `/undelete` | `{"expected_version", "note"}` | `{"comment": Comment}` |
| `POST /api/comments/{id}/restore` | `{"expected_version", "version", "note"}` | `{"comment": Comment}` |
| `GET /api/comments/{id}/revisions` · `/revisions/{version}` · `/diff?from=&to=` | — | as for entities |

`Comment` = `{id, subject_id, subject_type, subject_label, field, parent_id, body_md, body_html, status, resolved_by, resolved_at, created_at, created_by, updated_at, updated_by, version, edited, deleted_at, deleted_by}`. The rules (allowed subjects, threads, deletion, `edited`) are those of DATA_MODEL §6.6.

**`body_html`** is rendered on read:
- **Renderer:** markdown-it-py, `MarkdownIt('commonmark', {'html': False, 'linkify': True}).enable(['linkify', 'table', 'strikethrough'])`. The dependency is `markdown-it-py[linkify]`.
- **Sanitiser:** `nh3.clean`.
  - Allowed tags: `p`, `br`, `strong`, `em`, `code`, `pre`, `blockquote`, `ul`, `ol`, `li`, `a`, `h1`–`h4`, `hr`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `s`, `del`.
  - Attributes: only `a: href, title`.
  - URL schemes: `http`, `https`, `mailto`.
  - `link_rel="noopener noreferrer nofollow"`; `rel` itself is not in the allowed attributes.

### 3.4 Recent changes

| Method and path | Response |
|---|---|
| `GET /api/revisions?author=a,b&entity_type=project,comment&channel=ui,seed&since=YYYY-MM-DD&until=YYYY-MM-DD&entity_id=&batch_id=&page=&page_size=` | `{"items": [{"id", "entity_type", "entity_id", "entity_label", "version", "at", "author", "channel", "note", "changed_fields", "restored_from", "batch_id"}], "total", "page", "page_size"}`, newest first (`ORDER BY id DESC`); `since`/`until` inclusive UTC days; includes comment, vocabulary-term and saved-view revisions |
| `GET /api/revisions/authors` | `{"authors": ["Anna", "seed", "…"]}` |

## 4. List query grammar

These parameters apply to list, facets and export endpoints. The frontend keeps exactly these parameters in the page URL, so links can be shared.

### 4.1 Field filters

**Form:** `f.<field>=<op>:<value>`.
- A field may appear at most once; filters on different fields are combined with AND.
- **Lists** in `<value>` are comma-separated. Codes and IDs never contain commas.
- **Text operators** take the whole remainder after the first colon as value.

| Filter kind | Operators and semantics |
|---|---|
| `text` | `contains:<s>` → `instr(mdt_fold(col), fold(s)) > 0` (case-insensitive incl. Cyrillic; no wildcards; list fields match if any element matches; alias lists match on alias texts); `eq:<s>` → `mdt_fold(col) = fold(s)`; `empty:true\|false`. `contains` and `eq` never match NULL. |
| `multiselect` (vocab) | `in:<a,b>`; `nin:<a,b>` (**includes** rows where the field is NULL); `empty:true\|false` |
| `multiselect` (vocab_list) | `any:<a,b>`; `all:<a,b>`; `none:<a,b>` (**includes** empty lists); `empty:true\|false` (empty = `[]`) |
| `bool` | `eq:true\|false` |
| `date_range` | `overlaps:<from>..<to>` (the interval [start, end] intersects [from, to]); `within:<from>..<to>` (start ≥ from and end ≤ to); `empty:true\|false`. Either bound may be omitted; bounds are `YYYY-MM-DD`. A `date` field is the interval [d, d]; a `datetime` field uses its UTC calendar date. |
| `number_range` | `range:<min>..<max>` (either bound optional), `eq:<n>` |
| `ref` | `in:<id,…>`, `empty:true\|false`. For document `links`: `in:` matches links in state `suggested` or `confirmed`, `confirmed:` only confirmed ones. |

**Empty** means NULL for scalars and `[]` for lists.

**Derived and virtual fields** are filterable like stored fields; a missing derived row counts as `unknown`. These are `launch`, `existed_by`, `period`, `war_trajectory`, `portfolio_entry`, `open_comments`, `comment_count`, `project_in_paper_scope`, `subject_in_paper_scope` and `linked_in_paper_scope`.

A malformed filter, an unknown field, a field without `filter`, or an operator not valid for the field → `400 bad_filter`.

### 4.2 Sorting

**Form:** `sort=field[,-field2[,field3]]`.
- At most 3 fields; `-` = descending.
- Only `sortable` fields; invalid → `400 bad_sort`.
- NULLs (and empty lists) sort last in both directions; the final tie-breaker is `id`.
- The default comes from `meta.entity_types[type].default_sort`.

**Sort keys:**

| Type | Key |
|---|---|
| `string`, `text` | `mdt_sortkey(col)`: case-insensitive, Ukrainian alphabetical order (DATA_MODEL §10) |
| `slug`, `date`, `datetime` | the stored text |
| `bool` | false < true |
| `int`, `number` | numeric |
| `vocab` | the term's `sort_order`, then `code` (the same order as in facets) |
| `vocab_list` | the key of the **first** element (the main value), like `vocab` |
| `ref` | the target's label computed in SQL (`mdt_sortkey` of name_en → name_uk → slug, or the title for documents); polymorphic refs use one LEFT JOIN per allowed type |
| `partial_date` and derived dates | ascending (`_start`, `_end`); descending (`_start` DESC, `_end` DESC) |
| derived vocab (`period`, `war_trajectory`) | as `vocab`; a missing row counts as `unknown` |
| virtual counts | numeric |

### 4.3 Other parameters

- **`q`:** full-text search, combined with filters by AND. For documents it matches the metadata and the full text (DATA_MODEL §10); for all other types it matches the entity text. Deleted entities stay searchable (with `deleted=only|include`).
- **`page`** (≥ 1, default 1), **`page_size`** (1–500, default 50).
- **`deleted`:** `exclude` (default) | `only` | `include`.
- **`cols`:** used by export only; the UI also keeps it in the URL.
- Other unknown parameters are ignored.

## 5. Exports

`GET /api/entities/{type}/export?format=csv|xlsx&cols=…&<filters>&sort=…` exports **all** rows matching the filters (no paging), in the requested sort order.

- **Columns:**
  - default `id` + the type's `in_list` fields;
  - derived fields as `derived_<name>`, and for each also `derived_<name>_basis`, `derived_<name>_reason` and `derived_<name>_event_id` where they exist;
  - `ref` fields as the ID plus an extra column `<field>_label`;
  - lists joined with `"; "`;
  - aliases as their texts joined with `"; "`;
  - JSON as compact JSON;
  - booleans `true`/`false`.
- **XLSX:** one sheet named after the type, bold header, frozen first row. Every string cell is written with data type `s` (never as a formula), and characters that XLSX cannot store are removed. Numbers and booleans keep their types.
- **CSV:** UTF-8 with BOM, comma separator, header row. String values that begin with `=`, `+`, `-`, `@`, tab or carriage return are prefixed with an apostrophe (`'`), so spreadsheet programs do not execute them; the README documents this and points to XLSX/JSON for exact values.
- **Headers:** `Content-Disposition: attachment; filename="<type>-<YYYYMMDD-HHMMSS>.<ext>"` (UTC); `Cache-Control: no-store`.

## 6. Runtime, static frontend and security headers

**Process and binding:**
- One process. Inside the container uvicorn always binds `0.0.0.0:8080` with one worker.
- `HOST`/`PORT` are used only for the published port in compose and by `make dev`. They are never read inside the container.
- The container entrypoint runs `mdt db upgrade`, `mdt seed` and then the server on every start, as an unprivileged user.

**Startup self-check:** SQLite version and FTS5 availability (DATA_MODEL §11).

**Routing order:** API routers first, then static files.
- **`/assets/*`:** served with `Cache-Control: public, max-age=31536000, immutable`; a missing asset returns 404 (never `index.html`).
- **Other `GET`/`HEAD` paths outside `/api/` without a file extension** return `index.html` with `Cache-Control: no-cache` (SPA fallback). Existing root files such as the favicon are served as they are.
- **Path safety:** resolved paths must stay inside `FRONTEND_DIST` (no traversal).
- **Without a frontend build:** if `FRONTEND_DIST` has no `index.html`, the app still starts, the API works and non-API paths return `503` with a JSON hint. Docker images always contain the build.

**OpenAPI:** the schema is at `/api/openapi.json`. Swagger UI and ReDoc are disabled (they need inline scripts or a CDN).

**Security headers:** an ASGI middleware sets them on every response (API, static files, errors):
- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`. Mantine injects inline `<style>` elements, so `'unsafe-inline'` must stay in `style-src`. Scripts stay strict: no inline scripts (no `ColorSchemeScript`; the colour scheme is fixed to light).
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: same-origin`
- `X-Frame-Options: DENY`
- `Cross-Origin-Opener-Policy: same-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`

**Reverse proxy:** it must forward the original `Host` header (nginx: `proxy_set_header Host $host`), and its host name must be in `ALLOWED_HOSTS`.
