# HTTP API

> **Status:** v1 contract for Phase 1, revised 2026-10-28 after a five-lens contract review, updated the same day with the clarifications of the Phase 1 build and integration, and simplified on 2026-10-29 for a single user without an additional security layer (decision D-15, `PLAN.md` §12). Base path `/api`, JSON only. Field names, types, entity types, normalisation, limits and write semantics come from `docs/DATA_MODEL.md`.

## 1. Conventions

### 1.1 Requests

- The app has one user and no login, and the server it runs on is secured by its environment (D-15). Requests therefore carry no custom headers and no credentials, and the API has no request checks beyond input validation. No CORS middleware is installed: the frontend is served from the same origin (§6), and in development the Vite dev server proxies `/api`.
- Writes send a JSON body with `Content-Type: application/json`; a body that is missing, is not valid JSON or comes with another content type is `400 validation_error` (§1.2).
- `GET` handlers never write.

### 1.2 Error format

All errors use one envelope:

```json
{"error": {"code": "validation_error", "message": "Human-readable summary", "details": {"name_en": ["At least one of name_en/name_uk is required"]}}}
```

| Status | `code` | `details` |
|---|---|---|
| 400 | `validation_error` | `{field_path: [messages]}`: field paths and messages only, never the submitted input |
| 400 | `bad_filter`, `bad_sort`, `evidence_required` | — |
| 404 | `not_found` | — |
| 405 | `method_not_allowed` | — (the `Allow` header lists every method of all API routes that match the path; `GET, HEAD` on non-API paths) |
| 409 | `entity_deleted` | `{deleted_at, deleted_by}` |
| 409 | `invalid_state` | `{state}` (e.g. deleting a deleted row) |
| 409 | `has_dependents` | counts per kind of dependent: `{"service": 12}` (deleting a project or service without `cascade`), `{"field_verification": 1}` (deleting evidence that a field verification rests on; `cascade` does not apply, DATA_MODEL §6.4) |
| 409 | `unique_violation` | `{field, existing: {id, label, deleted}}` |
| 409 | `reference_deleted` | `{field, id, type, label}` |
| 409 | `not_deletable` | — (vocabulary terms) |
| 409 | `fixed_code` | — (fixed vocabulary codes, DATA_MODEL §7) |
| 500 | `internal_error` | `{request_id}` |
| 503 | `frontend_not_built` | — (`GET`/`HEAD` on non-API paths when `FRONTEND_DIST` has no build, §6; the message points to `make build`) |

- `debug` is always off. Handlers for `HTTPException`, `RequestValidationError`, `IntegrityError` (a UNIQUE violation → `409 unique_violation`, anything else → `500`) and `Exception` produce the envelope. An HTTP error raised by the framework with a status that has no code above (a fallback, not expected in Phase 1) uses the code `http_error` with the standard reason phrase as message.
- Messages never contain exception text, SQL, parameter values, file paths or stack traces. These go to the log together with the `request_id`.
- **Validation details:** request-body errors are always `400` (never 422). Field paths are the registry field names for domain errors (e.g. `name_en`) and dotted paths for body errors (e.g. `ids[0]`, `set.status`); an unparsable JSON body is reported under `body`. Invalid query parameters that are not filters (`page`, `page_size`, `deleted`, `cols`, `format`, `limit`, `types`, `status`, `since`, `until`, `channel`, `action`, the feed's `entity_type`, and the diff's `from`/`to`) give `400 validation_error` with `{param: [message]}`. The UI maps a path to a form field by its last dot-separated segment; other paths are shown as a general form error.

### 1.3 Other conventions

- **Timestamps** are strings in the exact format of DATA_MODEL §1.1; the API never reformats them. **Partial dates** use the canonical strings.
- **Successful writes may return `warnings`** (so far only `inactive_code`: a restore brought back an inactive vocabulary code): an array of `{code, message, field}`.
- **Every HTTP write** uses channel `ui` (`restore` for the restore endpoints) and is attributed to the fixed actor name `user`, which is recorded as the revision's `author`, in `created_by`, `updated_by`, `deleted_by` and `resolved_by`, and as `field_meta.by`; a value set in the app gets `field_meta.src = manual` (DATA_MODEL §5). No request field selects a channel, an author or a provenance (DATA_MODEL §6.2). Responses keep their author fields, because the seed, imports and collectors write under their own names.

### 1.4 Limits

These are in addition to the field limits of DATA_MODEL §1.3:
- **Requests:** `page` ≤ 1 000 000; `page_size` ≤ 500; bulk `ids` ≤ 500; at most 3 sort fields (§4.2).
- **Exports** have no row limit:
  - they stream (CSV via a streaming response, XLSX written in write-only mode to a temporary file);
  - rows are read in chunks of 500, and only what the selected columns need is loaded: their table columns, document links, derived rows, the selected virtual counts and the labels of the selected references, never `field_meta` (so `cols=id` costs a fraction of the default columns). Measured on 20 000 documents: CSV with the default columns about 0.8 s, XLSX about 3 s;
  - an XLSX file is complete before its first byte is sent (openpyxl writes the zip at the end), at roughly 1.5 s per 10 000 rows of the default document columns (200 000 rows take about half a minute); a reverse proxy in front of the app should allow that read timeout. CSV starts at once.

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
  "updated_at": "2026-10-29T08:12:00.000000Z", "updated_by": "user",
  "deleted_at": null, "deleted_by": null, "merged_into": null,
  "fields": {"slug": "diia", "name_en": "Diia", "name_uk": "Дія", "verification_status": "unverified", "notes": null, "…": "…"},
  "field_meta": {"name_en": {"src": "seed", "by": "seed", "at": "…", "locked": true, "verified": "unverified", "evidence_id": null, "restored_from_version": null}},
  "derived": {
    "launch": "2020-02", "launch_start": "2020-02-01", "launch_end": "2020-02-29", "launch_precision": "month", "launch_basis": "stated_in_source", "launch_event_id": "evt_…",
    "existed_by": null, "existed_by_event_id": null, "existed_before_invasion": true,
    "period": "pre_invasion", "period_reason": null,
    "war_trajectory": "prewar_unchanged", "trajectory_reason": null, "trajectory_event_id": null,
    "portfolio_entry": null, "portfolio_entry_start": null, "portfolio_entry_end": null, "portfolio_entry_precision": null, "portfolio_entry_participation_id": null,
    "computed_at": "…"
  },
  "virtual": {"open_comments": 1, "comment_count": 4},
  "refs": {"project_id": {"id": "prj_…", "type": "project", "label": "Diia", "deleted": false}, "derived.launch_event_id": {"id": "evt_…", "type": "event", "label": "Launch · Diia · 2020-02", "deleted": false}},
  "search_snippet": null
}
```

- **`fields`** holds every registry field that is neither derived nor virtual nor a system column, including system-set fields such as `canonical_url`. It never contains `seed_key`.
- **System columns** (`created_at` … `version`) are top-level properties; as registry fields they can also be sorted, filtered and exported (DATA_MODEL §2.3).
- **`derived`** is present for project and service. The `portfolio_entry_*` keys mirror the `launch_*` keys.
  - **Launch interval vs. displayed launch** (DATA_MODEL §8.3): `launch_start` and `launch_end` are the **launch interval** over all launch candidates, [earliest start, earliest end]; `launch`, `launch_precision`, `launch_basis` and `launch_event_id` describe the **displayed candidate** (the one that ends first). With one candidate the interval is that candidate's own bounds; candidates of different precision can widen it, e.g. launch events `2022` and `2022-03` give `launch: "2022-03"` with the interval 2022-01-01 – 2022-03-31. The period, the trajectory and their `imprecise_date` reason, the `launch` filter and sort (§4) and the export's `derived_launch_start`/`derived_launch_end` (§5) all use the interval; the UI shows it next to the displayed value whenever the two differ. A missing derived row gives the initial values (DATA_MODEL §8.1: period and war trajectory `unknown`, reason `no_date`) with `computed_at: null`.
- **Document `links`:** `origin` is provenance and read-only for clients; `matched_aliases`, `match_count` and `snippet` are read-only too (DATA_MODEL §1.2).
- **`virtual`:**
  - `open_comments` and `comment_count` for every type;
  - `project_in_paper_scope` (service), `subject_in_paper_scope` (event), `linked_in_paper_scope` (document);
  - detail responses add `open_comments_by_field` (`{"<field>": n, "": n for entity-level threads}`).
- **`refs`** gives the label of every non-null `ref` field, of the derived event and participation IDs (keys `derived.<name>`) and, for documents, of every link subject (key `links.<subject_id>`).
- **`search_snippet`** is set for documents when the list query has `q`: a list of segments `[{"text": "…", "hit": false}, {"text": "Дія", "hit": true}, …]` (DATA_MODEL §10).
- **`label`** rules:
  - project, service, organization, component: `name_en` → `name_uk` → `slug`/`id`;
  - event: `<event_type label> · <subject label> · <date or "undated">`;
  - document: `title`;
  - participation: `<organization> · <role label> · <subject>`;
  - relation: `<from> <relation_type label> <to>`;
  - indicator: `<metric>: <value> <unit>` (the unit left out when empty; integral values without `.0`);
  - evidence: `<target> · <subject>`;
  - vocabulary term: `<vocabulary>:<code>`;
  - saved view: `name`;
  - comment (in feeds): `Comment on <subject label>[ · <field label>]`.
- **Document detail** responses add `fields.text` (from `document_text`); list responses omit it.

## 3. Endpoints

### 3.1 Meta, lookup and statistics

| Method and path | Response |
|---|---|
| `GET /api/health` | `{"status": "ok", "version": "<app version>", "schema_revision": "<alembic head>"}` |
| `GET /api/meta` | see below |
| `GET /api/vocab` | `{"vocabularies": [{"name", "label", "description", "multi", "fixed_codes", "terms": [{"id", "code", "label_en", "label_uk", "definition", "include_note", "exclude_note", "examples", "sort_order", "active", "replaced_by", "attributes", "version", "usage_count", "open_comments"}]}]}`, vocabularies by name, terms by `sort_order` (empty last), then code. `usage_count` = non-deleted entities whose fields reference the code, including the derived `period` and `war_trajectory` values of live projects and services. `attributes` is `{}` when nothing is stored. |
| `GET /api/stats` | `{"entities": {"project": {"total": 20, "unverified": 20, "deleted": 0}, "…": {}}, "open_comments": 3}`. `total` and `unverified` count live rows only; `open_comments` counts the open, non-deleted root comments on all subjects. |
| `GET /api/lookup?types=project,service&q=<text>&limit=20[&f.…]` | `{"items": [{"id", "type", "label", "deleted", "context"}]}`. Matches label, names, slug and alias texts by normalised, case-folded prefix first, then FTS; ordered by match quality, then label. Optional `f.` filters apply per type (e.g. the parent-service picker passes `f.project_id=in:<project>`). `context` is a short disambiguation (e.g. the project of a service). |
| `GET /api/lookup?ids=a,b,c` | labels for any IDs, deleted ones included (`deleted: true`); unknown IDs are omitted |

**Lookup details:**
- Without `q` (and without `ids`) it lists non-deleted rows by label, e.g. for the parent-service picker with `f.project_id`.
- `types` defaults to the five table types (any generic type is allowed, comments are not); `limit` is 1–100 (default 20). Rows matched by `q` are never deleted ones. Exact matches come before other prefix matches.
- An `f.` filter applies to the requested types that have the field and leaves the others unfiltered; a filter that none of them has → `400 bad_filter`.
- Prefix matching uses names, slug and alias texts; `title`/`title_en` for documents; the saved view's `name`; a term's `code`, `label_en`, `label_uk` and `vocabulary:code`. Types whose labels are composed from other records (event, participation, relation, indicator, evidence) match through FTS only. The FTS stage searches entity text, not document full texts (the list endpoint's `q` does that).
- `context`: service → its project's label; document → `publisher · published`; vocabulary term → `label_en`; saved view → the plural label of its table; organization → country; other types `null`.

`GET /api/meta` returns:

```json
{
  "app_version": "0.1.0",
  "focal_org_id": "org_…",
  "parameters": {"ministry_founded": "2019-08-29", "full_scale_invasion": "2022-02-24"},
  "limits": {"max_comment_chars": 10000, "max_note_chars": 2000, "max_page_size": 500, "max_bulk_items": 500},
  "groups": [{"key": "basics", "label": "Basics"}, {"key": "classification", "label": "Classification"}, {"key": "wartime", "label": "Wartime"}, {"key": "framework", "label": "Framework D1–D4"}, {"key": "sources", "label": "Sources & Evidence"}, {"key": "system", "label": "System"}],
  "vocabularies": {"paper_cluster": {"label": "Paper cluster", "multi": false, "fixed_codes": false}},
  "entity_types": {
    "project": {
      "label": "Project", "label_plural": "Projects", "prefix": "prj", "table_view": true,
      "default_sort": "paper_cluster,name_en",
      "constraints": [{"one_of_required": ["name_en", "name_uk"]}],
      "fields": [{"name": "slug", "label": "Slug", "type": "slug", "vocabulary": null, "ref_types": null, "group": "basics", "required": true, "editable": true, "create_only": false, "system": false, "tracked": true, "derived": false, "virtual": false, "filter": "text", "sortable": true, "in_list": true, "in_create": true, "default": null, "bulk_editable": false, "exportable": true, "help": "…"}],
      "quick_filters": [
        {"key": "unverified", "label": "Unverified", "kind": "toggle", "query": "f.verification_status=in:unverified"},
        {"key": "open_comments", "label": "Open comments", "kind": "toggle", "query": "f.open_comments=range:1.."},
        {"key": "no_start_date", "label": "No start date", "kind": "toggle", "query": "f.launch=empty:true"},
        {"key": "in_scope", "label": "In paper scope", "kind": "toggle", "query": "f.in_paper_scope=eq:true"},
        {"key": "period", "label": "Period", "kind": "chips", "field": "period", "values": ["pre_ministry", "pre_invasion", "full_scale_war", "unknown"]}
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
- saved_view `name`;
- deleted views (trash) `-deleted_at`: with `deleted=only` and no `sort`, the backend applies it itself.

**Quick filter shapes:**
- `toggle`: `{key, label, kind: "toggle", query}` with exactly one `f.<field>=<op>:<value>` pair;
- `chips`: `{key, label, kind: "chips", field, values}`, a multi-select over the codes in `values` (written as `f.<field>=in:<codes>`);
- `preset`: **one** quick filter per type, `{key: "period", label: "Period", kind: "preset", field, presets: [{key, label, query}]}`; the presets are mutually exclusive, and each `query` is one `f.<field>=within:<from>..<to>` pair.

**Quick filters per type:**
- **project:** unverified, open comments, no start date (`f.launch=empty:true`), in paper scope, and the **period chips** (kind `chips` on the derived `period`: `f.period=in:<codes>`, offering the four period codes including `unknown`).
- **service:** the same, with `f.project_in_paper_scope=eq:true` for scope.
- **event:**
  - unverified, open comments, undated (`f.date=empty:true`), in paper scope (`f.subject_in_paper_scope=eq:true`);
  - period presets (kind `preset` on `date`; labels and ranges generated from `parameters`, e.g. "Before the ministry (to 2019-08-28)"): `f.date=within:..2019-08-28`, `f.date=within:2019-08-29..2022-02-23`, `f.date=within:2022-02-24..`;
  - dates that straddle a cut-off match no preset.
- **document:** unverified, open comments, unscreened (`f.screening_status=in:unscreened`), in paper scope (`f.linked_in_paper_scope=eq:true`), period presets on `published` like events.
- **organization:** unverified, open comments.

A toggle is active only if the URL contains exactly its key/value pair. Activating it replaces an existing filter on that field; deactivating it removes the parameter.

**`bulk_editable`** is true for editable, non-create-only fields of type `vocab`, `vocab_list` and `bool`, including `verification_status`.

**`exportable`** is true for fields that have a value per list row: every field except the virtual fields without one (the detail-only document `text`, which list responses omit, and the filter-only relation `endpoint`). Exactly these fields are accepted in `cols` (§5); the UI offers only them as table columns.

### 3.2 Generic entity endpoints

| Method and path | Body | Response |
|---|---|---|
| `GET /api/entities/{type}` | — (query grammar §4) | `{"items": [Item], "total": n, "page": 1, "page_size": 50}` |
| `GET /api/entities/{type}/facets?field=<name>&…` | — | `{"field": "kind", "values": [{"value": "e_service", "label": "E-service", "count": 12}], "empty_count": 3}`. All filters apply except the one on `field`. Vocabulary values include zero counts for active terms and are ordered by `sort_order`; inactive terms appear only when in use, and codes missing from the vocabulary are appended with the code as label. Boolean facets always return both values `"true"`/`"false"` (labels "Yes"/"No"). Refs are labelled and ordered by count (descending), then label. Document `links` count suggested and confirmed links (like `in:`); their `empty_count` is the number of documents without any link row. The relation `endpoint` facet counts both ends (`empty_count` 0). Allowed for fields with filter `multiselect`, `bool` or `ref`; any other `field` → `400 bad_filter`. |
| `GET /api/entities/{type}/export?format=csv\|xlsx&cols=a,b&…` | — | file download, §5 (`format` defaults to `csv`) |
| `POST /api/entities/{type}` | `{"data": {…}, "note": "…"}` | `201 {"item": Item, "revision_id": n, "warnings": []}` |
| `GET /api/entities/{type}/{id}` | — | `{"item": Item}` (deleted items are returned too, with `deleted_at` set) |
| `PATCH /api/entities/{type}/{id}` | `{"changes": {…}, "note": "…"}` | `{"item": Item, "changed": true, "revision_id": n, "warnings": []}`; a no-op returns `changed: false`, `revision_id: null` |
| `POST /api/entities/{type}/{id}/delete` | `{"note": "…", "cascade": false}` | `{"item": Item, "revision_id": n, "batch_id": "…"}` |
| `POST /api/entities/{type}/{id}/undelete` | `{"note": "…", "cascade": false}` | `{"item": Item, "revision_id": n, "batch_id": "…"}`; with `cascade`, the rows deleted in the same batch are undeleted too |
| `POST /api/entities/{type}/{id}/verify-field` | `{"field": "name_en", "status": "verified", "evidence_id": "evd_…", "note": "…"}` | `{"item": Item, "revision_id": n}`; setting the status (and evidence) already recorded is a no-op with `revision_id: null` (DATA_MODEL §6.4) |
| `GET /api/entities/{type}/{id}/revisions?page=&page_size=` | — | `{"items": [RevisionSummary], "total": n, "page", "page_size", "refs": {…}}`, newest first |
| `GET /api/entities/{type}/{id}/revisions/{version}` | — | `{"revision": RevisionFull, "refs": {…}}` |
| `GET /api/entities/{type}/{id}/diff?from=2&to=5` | — | `{"from": 2, "to": 5, "diff": {"fields": {…}, "meta": {…}, "state": {…}}, "not_recorded": ["…"], "refs": {…}}`; both parameters are required and `from` must be older than `to` (else `400 validation_error`); `from=0` = the empty state before creation; an unknown record or version → 404 |
| `POST /api/entities/{type}/{id}/restore` | `{"version": 2, "fields": null, "dry_run": false, "note": "…"}` | `{"item": Item, "changed": true, "revision_id": n, "warnings": [], "skipped_fields": [], "changes": {"field": [current, restored]}}`; with `dry_run: true` only `changes` is computed and nothing is written; a restore that changes nothing returns `changed: false`, `revision_id: null`; an unknown version → 404 |
| `POST /api/entities/{type}/bulk` | `{"ids": ["…", "…"], "set": {"status": "active"}, "add": {"channels": ["app"]}, "remove": {}, "note": "…"}` | `{"batch_id": "…", "results": [{"id": "…", "status": "updated\|unchanged\|entity_deleted\|error", "version": 4, "error": null}]}` |
| `GET /api/revisions/{revision_id}` | — | `{"revision": RevisionFull, "entity_type", "entity_id", "entity_label", "refs": {…}}` for any entity type, comments included |

Notes:
- **Revision records:**
  - `RevisionSummary` = `{id, version, at, author, channel, action, note, changed_fields, restored_from, restored_from_version, batch_id}`;
  - `RevisionFull` = `RevisionSummary` + `{snapshot, diff, schema_revision}`;
  - `changed_fields` as defined in DATA_MODEL §6.3;
  - `refs` in revision responses are keyed by ID (an item's `refs` are keyed by field) and label the IDs in the diffs, for a single revision also those in its snapshot.
- **Body keys:** `data` and `changes` use registry field names in API representation. Unknown, derived, virtual, system or non-editable fields, and create-only fields in `changes`, → `400 validation_error`.
- **Strict bodies:** a body accepts only the keys listed in the tables; an unknown top-level key → `400 validation_error` (e.g. resolve/reopen take an empty object `{}`). `version` is a JSON integer ≥ 0; `cascade` and `dry_run` are JSON booleans. Integers in paths and queries are checked too (`version` ≥ 0, `revision_id` ≥ 1, diff `from`/`to` ≥ 0), else 400. In a restore, `fields` may be omitted (all restorable fields).
- **No version check:** requests send no version (D-15). Each write applies to the record as it is when its write transaction starts (DATA_MODEL §6.5). Writes to a deleted row (`PATCH`, `verify-field`, `restore`, comment edits, resolve and reopen) → `409 entity_deleted`; deleting a deleted row or undeleting a live one → `409 invalid_state`.
- **Bulk:**
  - the whole request → 400 if `ids` is empty or has more than 500 entries, an ID is not a non-empty string or is duplicated, all of `set`/`add`/`remove` are empty, a field is not `bulk_editable`, appears in more than one of them, or `add`/`remove` targets a non-list field;
  - `updated`, `unchanged` and `entity_deleted` results carry the record's `version` (`entity_deleted` changes nothing); `error` results carry the §1.2 error object (e.g. `not_found` for an unknown ID) and `version: null`;
  - changing `in_paper_scope` requires `scope_note` in `set` (accepted there although `scope_note` is not `bulk_editable`);
  - setting `screening_status` to `excluded` requires `screening_reason` in the same `set` (DATA_MODEL §7, screening);
  - setting `verification_status` to `verified`/`disputed` requires `note`.
- **`note`** is optional (≤ 2 000 characters) unless a rule above requires it, and is stored on the revision.

### 3.3 Comments

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/comments?subject_id=<id>` | optional `status`, `field` (`-` = entity-level threads only), `deleted=exclude\|only\|include` | `{"threads": [{"root": Comment, "replies": [Comment]}]}`; newest root first, replies oldest first |
| `GET /api/comments?status=&entity_type=&q=&deleted=&page=&page_size=` | without `subject_id` | `{"items": [{"root": Comment, "reply_count": n, "last_activity_at": "…"}], "total", "page", "page_size"}` |
| `GET /api/comments/{id}` | — | `{"comment": Comment}` |
| `POST /api/comments` | `{"subject_id", "field": null, "parent_id": null, "body_md"}` | `201 {"comment": Comment}`; roots start `open` |
| `PATCH /api/comments/{id}` | `{"body_md", "note"}` | `{"comment": Comment}` |
| `POST /api/comments/{id}/resolve` · `/reopen` | `{}` | `{"comment": Comment, "changed": bool}`; roots only (a reply → `400 validation_error`); idempotent (DATA_MODEL §6.6) |
| `POST /api/comments/{id}/delete` · `/undelete` | `{"note"}` | `{"comment": Comment}` |
| `POST /api/comments/{id}/restore` | `{"version", "note"}` | `{"comment": Comment}`; restores the body of that version (status fields are never restored) |
| `GET /api/comments/{id}/revisions` · `/revisions/{version}` · `/diff?from=&to=` | — | as for entities |

**Listing semantics:**
- `status` is `open`, `resolved` or `all`; a missing `status` means all.
- `deleted` applies to the thread roots: `exclude` (default) shows live roots with their live replies; `include` everything; `only` the deleted roots with all their replies. A deleted reply under a live root therefore shows only with `include` (the comments panel's "show deleted"), not in the trash.
- **Feed (without `subject_id`):** one item per thread, newest last activity first, where last activity = the latest `updated_at` of the root and its live replies; with `deleted=only` (the trash) the newest deletion of the root comes first. `reply_count` counts live replies. `entity_type` (curated types) accepts a comma-separated list; `q` is a full-text match on the root or a live reply. `field` is used only with `subject_id`.

`Comment` = `{id, subject_id, subject_type, subject_label, field, parent_id, body_md, body_html, status, resolved_by, resolved_at, created_at, created_by, updated_at, updated_by, version, edited, deleted_at, deleted_by}`. The rules (allowed subjects, threads, deletion, `edited`) are those of DATA_MODEL §6.6.

**`body_html`** is rendered on every read with markdown-it-py `MarkdownIt('commonmark', {'html': False, 'linkify': True}).enable(['linkify', 'table', 'strikethrough'])` (dependency `markdown-it-py[linkify]`): raw HTML in a body is not rendered but shown as text. The output is used as it is, without further sanitising (D-15). It is never stored in the row or in snapshots and never accepted from clients.

### 3.4 Recent changes

| Method and path | Response |
|---|---|
| `GET /api/revisions?entity_type=project,comment&channel=ui,seed&action=…&since=…&until=…&entity_id=&batch_id=&page=&page_size=` | `{"items": [{"id", "entity_type", "entity_id", "entity_label", "version", "at", "author", "channel", "action", "note", "changed_fields", "restored_from_version", "batch_id", "context"}], "total", "page", "page_size"}` |

Notes on `GET /api/revisions`:
- **Order:** newest first (`ORDER BY id DESC`).
- **`since`/`until`:** inclusive; each accepts a date (a UTC day: from its first or to its last microsecond) or an ISO 8601 timestamp with an explicit offset (`Z` or `±HH:MM`; seconds and up to 9 fractional digits optional; a naive timestamp → `400 validation_error`), normalised like a `datetime` value (DATA_MODEL §1.2). The UI sends local-day boundaries as timestamps such as `2026-09-30T21:00:00.000000Z`.
- **Lists:** `entity_type`, `channel` and `action` accept comma-separated lists of known values (DATA_MODEL §4). `entity_id` and `batch_id` match exactly. There is no author filter (D-15): the channel tells changes made in the app (`ui`, `restore`) from the seed, imports and collectors.
- **Scope:** comment, vocabulary-term and saved-view revisions are included.
- **`context`:** comment → `{subject_id, subject_type, field, parent_id}` (`parent_id` is the root of a reply, so links can open the thread); vocabulary term → `{vocabulary}`; saved view → `{entity_type}`; other types `null`.

## 4. List query grammar

These parameters apply to list, facets and export endpoints. The frontend keeps exactly these parameters in the page URL, so links can be shared. Field names map to registry column expressions; request text is never interpolated into SQL (`ORDER BY` and `json_each` paths included).

### 4.1 Field filters

**Form:** `f.<field>=<op>:<value>`.
- A field may appear at most once; filters on different fields are combined with AND.
- **Lists** in `<value>` are comma-separated; items are trimmed, empty items are dropped and duplicates removed, and at least one value is required. Codes and IDs never contain commas.
- **Text operators** take the whole remainder after the first colon as value.
- **`~empty`:** the reserved token (never a valid code or ID) can be added to `in`, `nin`, `any`, `none`, ref `in` and document-link `confirmed` lists and means "the field is empty" (for `links`: the document has no link row). Example: `f.wartime_relevance=in:direct,~empty`. With `nin` and `none`, which include empty rows anyway, listing `~empty` excludes them.

| Filter kind | Operators and semantics |
|---|---|
| `text` | `contains:<s>` → `instr(mdt_fold(col), fold(s)) > 0`: a literal substring, case-insensitive incl. Cyrillic, no wildcards; list fields match if any element matches; alias lists match on alias texts; an empty `<s>` matches every non-NULL value. `eq:<s>` → `mdt_fold(col) = fold(s)`. `empty:true\|false`. `contains` and `eq` never match NULL. |
| `multiselect` (vocab) | `in:<a,b>`; `nin:<a,b>` (**includes** rows where the field is NULL); `empty:true\|false` |
| `multiselect` (vocab_list) | `any:<a,b>`; `all:<a,b>`; `none:<a,b>` (**includes** empty lists); `empty:true\|false` (empty = `[]`) |
| `bool` | `eq:true\|false` |
| `date_range` | `overlaps:<from>..<to>` (the interval [start, end] intersects [from, to]); `within:<from>..<to>` (start ≥ from and end ≤ to); `empty:true\|false`. Either bound may be omitted; bounds are `YYYY-MM-DD`. A `date` field is the interval [d, d]; a `datetime` field uses its UTC calendar date. |
| `number_range` | `range:<min>..<max>` (either bound optional), `eq:<n>`. Bounds of `number` fields are finite numbers (compared as REAL). Integer bounds of `int` fields and virtual counts must fit the signed 64-bit range (decimal bounds such as `1.5` are allowed); anything larger is a malformed value. |
| `ref` | `in:<id,…>`, `empty:true\|false`. For document `links`: `in:` matches links in state `suggested` or `confirmed`, `confirmed:` only confirmed ones. Relation `endpoint`: `in:` matches `from_id` or `to_id`. |

**Empty** means NULL for scalars and `[]` for lists.

**Derived, virtual and system fields** are filterable like stored fields; a missing derived row counts as `unknown`. A derived date filter uses the derived row's `_start`/`_end`; for `launch` that is the launch interval over all candidates (§2), not the bounds of the displayed candidate. These are `launch`, `existed_by`, `period`, `war_trajectory`, `portfolio_entry`, `open_comments`, `comment_count`, the `*_in_paper_scope` fields, `created_at`, `updated_at`, `deleted_at`, `created_by`, `updated_by` and `deleted_by`.

A malformed filter, a repeated field, an unknown field, a field without `filter`, an operator not valid for the field, a malformed value (e.g. a date that is not `YYYY-MM-DD`, a non-number, a number out of range, a flag other than `true`/`false`), a malformed range (start after end, min > max) or `~empty` with `all` → `400 bad_filter`. Invalid values of the other parameters (§4.3) → `400 validation_error` (§1.2).

### 4.2 Sorting

**Form:** `sort=field[,-field2[,field3]]`.
- At most 3 fields, each at most once; `-` = descending; a missing or blank `sort` means the default.
- Only `sortable` fields, or `relevance` (only together with `q`: FTS `bm25`, best match first; `-relevance` reverses it; for documents the better rank of `fts_entity` and `fts_document` counts); invalid → `400 bad_sort`.
- NULLs (and empty lists) sort last in both directions; the final tie-breaker is `id`.
- The default comes from `meta.entity_types[type].default_sort`.

**Sort keys:**

| Type | Key |
|---|---|
| `string`, `text` | `mdt_sortkey(col)`: case-insensitive, Ukrainian alphabetical order, Latin before Cyrillic (DATA_MODEL §10) |
| `slug`, `date`, `datetime` | the stored text |
| `bool` | false < true |
| `int`, `number` | numeric |
| `vocab` | the term's `sort_order`, then `code` (the same order as in facets) |
| `vocab_list` | the key of the **first** element (the main value), like `vocab` |
| `ref` | the target's label computed in SQL: `mdt_sortkey` of name_en → name_uk → slug → id for named types, the title for documents, the name for saved views, `vocabulary:code` for terms; polymorphic refs use one LEFT JOIN per allowed type. Targets whose labels are composed from other records (event, participation, relation, indicator, evidence; only `evidence.subject_id` can point at them) sort by ID. |
| `partial_date` and derived dates | ascending (`_start`, `_end`); descending (`_start` DESC, `_end` DESC); for the derived `launch` these are the launch interval (§2), so a project whose candidates `2020` and `2020-06` show `2020-06` sorts before one that shows `2020-02` |
| derived vocab (`period`, `war_trajectory`) | as `vocab`; a missing row counts as `unknown` |
| virtual counts | numeric |

### 4.3 Other parameters

- **`q`:** full-text search, combined with filters by AND. For documents it matches the metadata and the full text (DATA_MODEL §10); for all other types it matches the entity text. Deleted entities stay searchable (with `deleted=only|include`). A blank `q` is ignored; a `q` without any searchable token matches nothing. Search snippets of documents matched only through their metadata come from `fts_entity`; snippets show the normalised index text (e.g. unified apostrophes).
- **`page`** (1–1 000 000, default 1), **`page_size`** (1–500, default 50).
- **`deleted`:** `exclude` (default) | `only` | `include`.
- **`cols`:** used by export only; the UI also keeps its column choice in the URL (and builds the export's `cols` from the visible columns, §5).
- Other unknown parameters are ignored.

## 5. Exports

`GET /api/entities/{type}/export?format=csv|xlsx&cols=…&<filters>&sort=…` exports all rows matching the filters (no paging and no row limit, §1.4), in the requested sort order.

**Columns:**
- **Selection:** `cols` takes registry field names (and `id`), exported in the given order; the default is `id` + the type's `in_list` fields. Headers are the registry names. Unknown names and fields that are not `exportable` in meta (the document `text`, the relation `endpoint`) are refused (`400 validation_error`). The UI always sends `cols` = `id` followed by the table's visible columns, so an export of the current view keeps the record ID.
- **Vocab fields:** the code plus `<field>_label` (the term's `label_en`, else the code); `vocab_list` fields: the joined codes plus the joined labels.
- **`partial_date` fields:** `<name>` (canonical), `<name>_start`, `<name>_end`, `<name>_precision`.
- **Derived fields:** prefixed `derived_`; derived partial dates and vocabularies get the same extra columns as stored ones (e.g. `derived_launch_start`, `derived_period_label`), plus `derived_<name>_basis`, `derived_<name>_reason` and `derived_<name>_event_id` where they exist; the portfolio entry has `derived_portfolio_entry_participation_id` instead of an event ID. For `launch`, `derived_launch` and `derived_launch_precision` are the displayed candidate, while `derived_launch_start` and `derived_launch_end` are the launch interval over all candidates (§2), which can be wider than the displayed value's own bounds.
- **Virtual fields:** their values (`open_comments`, `comment_count`, the `*_in_paper_scope` booleans). **System columns:** as stored (timestamps as text).
- **`ref` fields:** the ID plus `<field>_label`.
- **Document `links`:** compact JSON `[{subject_id, origin, state}]` (match details omitted) plus `links_label` = `<label> (<state>)` joined with `"; "`.
- **Lists:** joined with `"; "`; aliases as their texts.
- **JSON:** compact JSON with sorted keys. **Booleans:** `true`/`false`. **Numbers:** integral values without `.0`.

**File formats:**
- **XLSX** (openpyxl `Workbook(write_only=True)`):
  - every string value is a string cell (`data_type = "s"`, also for `WriteOnlyCell`), so a text that looks like a formula or an error value stays text;
  - `int`/`number` values are numbers, booleans are booleans;
  - characters that XLSX cannot hold (openpyxl's `ILLEGAL_CHARACTERS_RE`) are replaced with U+FFFD;
  - strings over 32 767 characters (the XLSX cell limit) are cut with the suffix ` [truncated]`;
  - values are otherwise unchanged;
  - one sheet named after the type, bold header, frozen first row.
- **CSV:**
  - UTF-8 with BOM, `csv.QUOTE_ALL`, header row;
  - values verbatim (text is never prefixed or altered);
  - the UI labels CSV "for analysis tools" and XLSX "for Excel, exact values".

**Headers:** `Content-Type: text/csv; charset=utf-8` or `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`; `Content-Disposition: attachment; filename="<type>-<YYYYMMDD-HHMMSS>.<ext>"` (UTC); `Cache-Control: no-store`.

**Download:** the UI downloads exports with `fetch` → Blob → object URL → `a[download]`, so a refused export shows the server's error message.

## 6. Runtime and static frontend

**Process and binding:**
- One process. Inside the container uvicorn always binds `0.0.0.0:8080` with one worker.
- `HOST`/`PORT` choose the host interface and port that compose publishes, and the default listen address of `mdt serve` outside Docker (the `--host`/`--port` flags override them; `make dev` passes `127.0.0.1:8000`). Inside the container compose pins them and the entrypoint passes `--host 0.0.0.0 --port 8080`.
- The entrypoint runs `mdt db upgrade`, `mdt seed` and then the server on every start, as an unprivileged user.

**Startup self-check** (`create_app` and `mdt serve`): the app refuses to start with a clear message (the CLI prints `error: …` and exits 1) when the SQLite version or FTS5 is missing (DATA_MODEL §11), the database file does not exist (run `mdt db upgrade` and `mdt seed` first) or is not at the Alembic head, or `codebook/parameters.yaml` is unusable. Startup never creates the database or runs migrations or the seed; `create_app` creates nothing at all, while `mdt serve`, like every `mdt` command, first creates a missing `DATA_DIR` directory.

**App and routing:**
- **App options:** `FastAPI(debug=False, docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)`: there is no OpenAPI document and no docs page (this document describes the API), and the app never redirects (`/api/entities/project/` is a 404); FastAPI's telemetry integration is switched off. API routes come first.
- **`/assets/*`:** served by Starlette `StaticFiles(directory=FRONTEND_DIST/"assets")`; a missing asset is a 404 in the error envelope, never `index.html`; conditional requests (`If-None-Match`, `If-Modified-Since`) get `304`.
- **Root files:** the files directly in `FRONTEND_DIST` (e.g. `favicon.svg`, `index.html`) are served by exact name with `Cache-Control: no-cache`; their names are read at startup, so a build that adds a root file is served after a restart.
- **SPA fallback:** every other `GET`/`HEAD` outside `/api/` returns `index.html` with `Cache-Control: no-cache`, so a new build is picked up on the next page load.
- **Other methods** on non-API paths → 405 (`Allow: GET, HEAD`). Unknown `/api` paths → 404. `HEAD` requests to API routes get 405 (FastAPI adds no `HEAD` routes); the UI never sends them.
- **Without a frontend build:** if `FRONTEND_DIST` has no `index.html`, the app still starts, the API works and `GET`/`HEAD` requests to non-API paths return `503 frontend_not_built` with a hint to run `make build`. Docker images always contain the build.

**No security layer** (D-15): the app sets no security headers and has no host allowlist, origin checks or request size limits; access control is the job of the server's environment. The default binding to 127.0.0.1 (README) only decides where the app is reachable.
