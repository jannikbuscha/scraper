# HTTP API

> **Status:** v1 contract for Phase 1 (2026-10-28). Base path `/api`, JSON only. Field names, types and entity types come from the registry in `docs/DATA_MODEL.md`.

## 1. Conventions

### 1.1 Headers on writes

Writes are `POST`, `PATCH`, `PUT` and `DELETE`. They require:
- **`X-Author`:** the author name, percent-encoded UTF-8 (`encodeURIComponent(name)`). Decoded and trimmed, it must be 1–100 characters without control characters. Missing → `400 author_required`; invalid → `400 author_invalid`. This is attribution, not authentication.
- **`Content-Type: application/json`.** Otherwise `415 unsupported_media_type`.
- **Same origin:** if an `Origin` header is present, its host:port must equal the request's `Host`. If `Sec-Fetch-Site` is present, it must not be `cross-site`. Otherwise `403 cross_origin_forbidden`.

### 1.2 Error format

All errors use one envelope:

```json
{"error": {"code": "validation_error", "message": "Human-readable summary", "details": {"name_en": ["At least one of name_en/name_uk is required"]}}}
```

| Status | `code` | `details` |
|---|---|---|
| 400 | `validation_error` | `{field: [messages]}`. FastAPI/Pydantic request errors are converted to this format; there is no 422. |
| 400 | `author_required`, `author_invalid`, `bad_filter`, `bad_sort` | — |
| 403 | `cross_origin_forbidden` | — |
| 404 | `not_found` | — |
| 409 | `conflict` | the payload from `docs/DATA_MODEL.md` §6.4 |
| 409 | `has_dependents` | `{"service": 12}` |
| 409 | `unique_violation` | `{field}` |
| 415 | `unsupported_media_type` | — |

### 1.3 Other conventions

- **Timestamps** are ISO-8601 UTC (`…Z`). **Partial dates** use the canonical strings from DATA_MODEL §1.
- **No CORS headers.** The SPA is served from the same origin.

## 2. Entity types and item representation

`{type}` is one of:
- `project`, `service`, `event`, `document`, `organization` (also with a table view in the UI);
- `participation`, `component`, `relation`, `indicator`, `evidence`, `vocabulary_term`, `saved_view`.

An unknown type returns `404 not_found`.

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
  "derived": {"launch": "2020-02", "launch_basis": "stated_in_source", "launch_event_id": "evt_…", "existed_by": null, "existed_before_invasion": true, "period": "pre_invasion", "period_reason": null, "war_trajectory": "unknown", "trajectory_reason": "no_date", "portfolio_entry": null},
  "virtual": {"open_comments": 1, "comment_count": 4},
  "refs": {"project_id": {"id": "prj_…", "type": "project", "label": "Diia", "deleted": false}}
}
```

- **`fields`** holds every registry field that is not derived and not virtual, including read-only system-filled fields such as `canonical_url`.
- **`derived`** is present for project and service. Service items also have `virtual.project_in_paper_scope`.
- **`refs`** gives the label of every non-null `ref` field and, for documents, of every link subject (`refs["links"] = {subject_id: {…}}`).
- **`label`** rules:
  - project, service, organization, component: `name_en` → `name_uk` → `slug`/`id`;
  - event: `<event_type label> · <subject label> · <date or "undated">`;
  - document: `title`;
  - participation: `<organization> · <role label> · <subject>`;
  - relation: `<from> <relation_type> <to>`;
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
| `GET /api/vocab` | `{"vocabularies": [{"name", "label", "description", "multi", "terms": [{"id", "code", "label_en", "label_uk", "definition", "include_note", "exclude_note", "examples", "sort_order", "active", "replaced_by", "attributes", "version", "usage_count"}]}]}`. `usage_count` = non-deleted entities whose fields reference the code. |
| `GET /api/stats` | `{"entities": {"project": {"total": 20, "unverified": 20, "deleted": 0}, "…": {}}, "open_comments": 3}` |

`GET /api/meta` returns:

```json
{
  "app_version": "0.1.0",
  "team_members": ["…"],
  "focal_org_slug": "ministry-of-digital-transformation",
  "parameters": {"ministry_founded": "2019-08-29", "full_scale_invasion": "2022-02-24"},
  "groups": [{"key": "basics", "label": "Basics"}, {"key": "classification", "label": "Classification"}, {"key": "wartime", "label": "Wartime"}, {"key": "framework", "label": "Framework D1–D4"}, {"key": "sources", "label": "Sources & Evidence"}, {"key": "system", "label": "System"}],
  "vocabularies": {"paper_cluster": {"label": "Paper cluster", "multi": false}},
  "entity_types": {
    "project": {
      "label": "Project", "label_plural": "Projects", "prefix": "prj", "table_view": true,
      "default_sort": "paper_cluster,name_en",
      "fields": [{"name": "slug", "label": "Slug", "type": "slug", "vocabulary": null, "ref_types": null, "group": "basics", "required": true, "editable": true, "tracked": true, "derived": false, "virtual": false, "filter": "text", "sortable": true, "in_list": true, "bulk_editable": false, "help": "…"}],
      "quick_filters": [
        {"key": "unverified", "label": "Unverified", "query": "f.verification_status=in:unverified"},
        {"key": "open_comments", "label": "Open comments", "query": "f.open_comments=range:1.."},
        {"key": "no_start_date", "label": "No start date", "query": "f.launch=empty:true"},
        {"key": "in_scope", "label": "In paper scope", "query": "f.in_paper_scope=eq:true"}
      ],
      "period_presets": [
        {"key": "pre_ministry", "label": "Before 29 Aug 2019", "field": "launch", "range": "..2019-08-28"},
        {"key": "pre_invasion", "label": "29 Aug 2019 – 23 Feb 2022", "field": "launch", "range": "2019-08-29..2022-02-23"},
        {"key": "full_scale_war", "label": "From 24 Feb 2022", "field": "launch", "range": "2022-02-24.."}
      ]
    }
  }
}
```

**Quick filters per type:**
- project: unverified, open comments, no start date, in paper scope; period via `f.period=in:…`;
- service: the same, with `f.project_in_paper_scope=eq:true`;
- event: unverified, open comments, undated (`f.date=empty:true`), period presets on `date`;
- document: unverified, open comments, unscreened (`f.screening_status=in:unscreened`), period presets on `published`;
- organization: unverified, open comments.

**`bulk_editable`** is true for editable fields of type `vocab`, `vocab_list` and `bool`, and for `verification_status`.

### 3.2 Generic entity endpoints

| Method and path | Body | Response |
|---|---|---|
| `GET /api/entities/{type}` | — (query grammar §4) | `{"items": [Item], "total": n, "page": 1, "page_size": 50}` |
| `GET /api/entities/{type}/facets?field=<name>&…` | — | `{"field": "kind", "values": [{"value": "e_service", "label": "E-service", "count": 12}], "empty_count": 3}`. All filters apply except the one on `field`. Vocabulary values include zero counts for active terms and are ordered by `sort_order`. Refs are labelled. |
| `GET /api/entities/{type}/export?format=csv\|xlsx&cols=a,b&…` | — | file download, §5 |
| `POST /api/entities/{type}` | `{"data": {…}, "note": "…"}` | `201 {"item": Item, "revision_id": n}` |
| `GET /api/entities/{type}/{id}` | — | `{"item": Item}` (deleted items are returned too, with `deleted_at` set) |
| `PATCH /api/entities/{type}/{id}` | `{"expected_version": 3, "changes": {…}, "note": "…"}` | `{"item": Item, "changed": true, "revision_id": n}`; a no-op returns `changed: false`, `revision_id: null` |
| `POST /api/entities/{type}/{id}/delete` | `{"expected_version": 3, "note": "…", "cascade": false}` | `{"item": Item, "revision_id": n}` |
| `POST /api/entities/{type}/{id}/undelete` | `{"expected_version": 4, "note": "…"}` | `{"item": Item, "revision_id": n}` |
| `POST /api/entities/{type}/{id}/verify-field` | `{"expected_version": 3, "field": "name_en", "status": "verified", "note": "…"}` | `{"item": Item, "revision_id": n}` |
| `GET /api/entities/{type}/{id}/revisions?page=&page_size=` | — | `{"items": [RevisionSummary], "total": n, "page", "page_size"}`, newest first |
| `GET /api/entities/{type}/{id}/revisions/{version}` | — | `{"revision": RevisionFull}` |
| `GET /api/entities/{type}/{id}/diff?from=2&to=5` | — | `{"from": 2, "to": 5, "diff": {"fields": {…}, "meta": {…}, "state": {…}}}` |
| `POST /api/entities/{type}/{id}/restore` | `{"expected_version": 5, "version": 2, "note": "…"}` | `{"item": Item, "changed": true, "revision_id": n}` |
| `POST /api/entities/{type}/bulk` | `{"items": [{"id": "…", "expected_version": 3}], "set": {"status": "active"}, "add": {"channels": ["app"]}, "remove": {}, "note": "…"}` | `{"batch_id": "…", "results": [{"id": "…", "status": "updated\|unchanged\|conflict\|error", "version": 4, "error": null}]}` |

Notes:
- **Revision records:**
  - `RevisionSummary` = `{id, version, at, author, channel, note, changed_fields, restored_from, batch_id}`;
  - `RevisionFull` = `RevisionSummary` + `{snapshot, diff}`.
- **Body keys:** `data` and `changes` use registry field names in API representation. Unknown, derived, virtual or non-editable fields → `400 validation_error`.
- **Optimistic locking:** `expected_version` is required for `PATCH`, `delete`, `undelete`, `verify-field` and `restore`; a mismatch → `409 conflict`.
- **`note`** is optional (≤ 2 000 characters) and stored on the revision.

### 3.3 Comments

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/comments?subject_id=<id>` | optional `status`, `field` | `{"threads": [{"root": Comment, "replies": [Comment]}]}`; every non-deleted thread of the subject, newest root first, replies oldest first |
| `GET /api/comments?status=&entity_type=&author=&q=&page=&page_size=` | without `subject_id` | `{"items": [{"root": Comment, "reply_count": n, "last_activity_at": "…"}], "total", "page", "page_size"}` |
| `POST /api/comments` | `{"subject_id", "field": null, "parent_id": null, "body_md"}` | `201 {"comment": Comment}`; roots start `open` |
| `PATCH /api/comments/{id}` | `{"expected_version", "body_md"}` | `{"comment": Comment}` |
| `POST /api/comments/{id}/resolve` · `/reopen` · `/delete` | `{"expected_version"}` | `{"comment": Comment}`; resolve and reopen only on roots |
| `GET /api/comments/{id}/revisions` | — | as for entities |

`Comment` = `{id, subject_id, subject_type, subject_label, field, parent_id, body_md, body_html, status, resolved_by, resolved_at, created_at, created_by, updated_at, updated_by, version, edited, deleted_at}`.

`body_html` is rendered server-side with markdown-it-py (CommonMark, `html=False`, linkify on) and sanitised with `nh3`:
- allowed tags: `p`, `br`, `strong`, `em`, `code`, `pre`, `blockquote`, `ul`, `ol`, `li`, `a`, `h1`–`h4`, `hr`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `del`;
- links: `http`/`https`/`mailto` only, with `rel="noopener noreferrer nofollow"`.

### 3.4 Recent changes

| Method and path | Response |
|---|---|
| `GET /api/revisions?author=a,b&entity_type=project,service&channel=ui,seed&since=YYYY-MM-DD&until=YYYY-MM-DD&entity_id=&page=&page_size=` | `{"items": [{"id", "entity_type", "entity_id", "entity_label", "version", "at", "author", "channel", "note", "changed_fields", "restored_from", "batch_id"}], "total", "page", "page_size"}`, newest first; `since`/`until` inclusive in UTC days; includes comment, vocabulary-term and saved-view revisions |
| `GET /api/revisions/authors` | `{"authors": ["Anna", "seed", "…"]}` |

## 4. List query grammar

These parameters apply to list, facets and export endpoints. The frontend keeps exactly these parameters in the page URL, so links can be shared.

### 4.1 Field filters

**Form:** `f.<field>=<op>:<value>`.
- A field may appear at most once; filters on different fields are combined with AND.
- **Lists** in `<value>` are comma-separated. Codes and IDs never contain commas.
- **Text operators** take the whole remainder after the first colon as value.

| Filter kind | Operators |
|---|---|
| `text` | `contains:<s>` (case-insensitive substring on normalised text; for list fields: any element), `eq:<s>`, `empty:true\|false` |
| `multiselect` (vocab) | `in:<a,b>`, `nin:<a,b>`, `empty:true\|false` |
| `multiselect` (vocab_list) | `any:<a,b>`, `all:<a,b>`, `none:<a,b>`, `empty:true\|false` (empty = empty list) |
| `bool` | `eq:true\|false` |
| `date_range` | `overlaps:<from>..<to>` (the interval [start, end] intersects [from, to]), `within:<from>..<to>` (start ≥ from and end ≤ to), `empty:true\|false`; either bound may be omitted; bounds `YYYY-MM-DD` |
| `number_range` | `range:<min>..<max>` (either bound optional), `eq:<n>` |
| `ref` | `in:<id,…>`, `empty:true\|false`. For document `links`: `in:` matches links in state `suggested` or `confirmed`, `confirmed:` only confirmed ones. |

**Derived and virtual fields** (`launch`, `existed_by`, `period`, `war_trajectory`, `portfolio_entry`, `open_comments`, `project_in_paper_scope`) are filterable like stored fields.

A malformed filter, an unknown field or an operator not valid for the field → `400 bad_filter`.

### 4.2 Other parameters

- **`q`:** full-text search (DATA_MODEL §10), combined with filters by AND.
- **`sort`:**
  - format `field[,-field2[,field3]]`: at most 3 sortable fields, `-` = descending;
  - NULLs sort last in both directions; the final tie-breaker is `id`;
  - invalid → `400 bad_sort`;
  - default per type from `meta.entity_types[type].default_sort`.
- **`page`** (≥ 1, default 1), **`page_size`** (1–500, default 50).
- **`deleted`:** `exclude` (default) | `only` | `include`.
- **`cols`:** used by export only; the UI also keeps it in the URL.
- Other unknown parameters are ignored.

## 5. Exports

`GET /api/entities/{type}/export?format=csv|xlsx&cols=…&<filters>&sort=…` exports **all** rows matching the filters (no paging), in the requested sort order.

- **Columns:**
  - default `id` + the type's `in_list` fields;
  - derived fields as `derived_<name>`;
  - `ref` fields as the ID plus an extra column `<field>_label`;
  - lists joined with `"; "`;
  - aliases as their texts joined with `"; "`;
  - JSON as compact JSON;
  - booleans `true`/`false`.
- **CSV:** UTF-8 with BOM (Excel opens Cyrillic correctly), comma separator, header row.
- **XLSX:** one sheet named after the type, bold header, frozen first row.
- **Headers:** `Content-Disposition: attachment; filename="<type>-<YYYYMMDD-HHMMSS>.<ext>"` (UTC).

## 6. Static frontend and security headers

- **SPA serving:** non-`/api` GET requests serve files from the built frontend (`FRONTEND_DIST`, default `frontend/dist`). Unknown paths return `index.html`. Unknown `/api/*` paths → `404 not_found` (JSON).
- **OpenAPI:** the schema is at `/api/openapi.json`. Swagger UI is disabled (it would need inline scripts or a CDN).
- **Host allowlist:** `ALLOWED_HOSTS` (default `127.0.0.1,localhost`), comma-separated; `*` disables the check (documented as unsafe). Other `Host` headers → 400. This protects against DNS rebinding.
- **Response headers:**
  - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: same-origin`
  - `X-Frame-Options: DENY`
