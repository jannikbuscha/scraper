# HTTP API

> **Status:** v1 contract for Phase 1, revised 2026-10-28 after a five-lens contract review, updated the same day with the clarifications of the Phase 1 build and integration, and simplified on 2026-10-29 for a single user without an additional security layer (decision D-15, `PLAN.md` §12). **Extended on 2026-10-30 with the Phase 2 endpoints** (§7: collectors and runs, snapshots, proposals, observations, merge and unmerge, uploads, manual documents, imports) and the marked additions in §1–§6; revised the same day after a four-lens review. **Extended on 2026-10-31 with the Phase 3 endpoints** (§8: document text and queue, evidence capture, timeline, crosstab and coverage, data revision, exports and their formats, indicator metrics) and the additions marked "Phase 3" in §1–§7; revised the same day after a four-lens review. Base path `/api`, JSON only (exceptions: uploads, §7.7, and file downloads). Field names, types, entity types, normalisation, limits and write semantics come from `docs/DATA_MODEL.md`; collector behaviour from `docs/COLLECTORS.md`.

## 1. Conventions

### 1.1 Requests

- The app has one user and no login, and the server it runs on is secured by its environment (D-15). Requests therefore carry no custom headers and no credentials, and the API has no request checks beyond input validation. No CORS middleware is installed: the frontend is served from the same origin (§6), and in development the Vite dev server proxies `/api`.
- Writes send a JSON body with `Content-Type: application/json`; a body that is missing, is not valid JSON or comes with another content type is `400 validation_error` (§1.2). The only exception is `POST /api/uploads` (§7.7), whose body is the raw file.
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
| 409 | `invalid_state` | `{state}` (e.g. deleting a deleted row; Phase 3 also `text_changed` with the current `text_hash`, §8.3, and `derived_out_of_date` for exports, §8.8.1) |
| 409 | `has_dependents` | counts per kind of dependent: `{"service": 12}` (deleting a project or service without `cascade`), `{"field_verification": 1}` (deleting evidence that a field verification rests on; `cascade` does not apply, DATA_MODEL §6.4) |
| 409 | `unique_violation` | `{field, existing: {id, label, deleted}}` |
| 409 | `reference_deleted` | `{field, id, type, label}` |
| 409 | `not_deletable` | — (vocabulary terms) |
| 409 | `fixed_code` | — (fixed vocabulary codes, DATA_MODEL §7) |
| 409 | `run_in_progress` | `{run_id}` (Phase 2: another collector run is running, §7.2) |
| 409 | `collector_unavailable` | `{reason}`: `disabled` or `contact_email_missing` (Phase 2, §7.2, §7.8) |
| 409 | `merge_conflict` | `{conflicts: [{kind, id, label, message}]}` (Phase 2, DATA_MODEL §18) |
| 409 | `privacy_check_failed` | `{file, record_id}` (Phase 3: an export file contains a client identifier, §8.8.1; DATA_MODEL §23.3) |
| 502 | `fetch_failed` | `{reason, status}`: `robots_disallowed`, `robots_unavailable`, `blocked`, `throttled`, `http_error`, `network_error` or `too_large` (Phase 2, manual fetches, §7.8) |
| 500 | `internal_error` | `{request_id}` |
| 503 | `frontend_not_built` | — (`GET`/`HEAD` on non-API paths when `FRONTEND_DIST` has no build, §6; the message points to `make build`) |

- `debug` is always off. Handlers for `HTTPException`, `RequestValidationError`, `IntegrityError` (a UNIQUE violation → `409 unique_violation`, anything else → `500`) and `Exception` produce the envelope. A domain error keeps its status and code; only a `500` is logged and answered as `internal_error` with a request ID (so `502 fetch_failed` reaches the client as listed). An HTTP error raised by the framework with a status that has no code above (a fallback, not expected in Phase 1) uses the code `http_error` with the standard reason phrase as message.
- Messages never contain exception text, SQL, parameter values, file paths or stack traces. These go to the log together with the `request_id`.
- **Validation details:** request-body errors are always `400` (never 422). Field paths are the registry field names for domain errors (e.g. `name_en`) and dotted paths for body errors (e.g. `ids[0]`, `set.status`); an unparsable JSON body is reported under `body`. Invalid query parameters that are not filters (`page`, `page_size`, `deleted`, `cols`, `format`, `limit`, `types`, `status`, `since`, `until`, `channel`, `action`, the feed's `entity_type`, the diff's `from`/`to`, and the parameters of the §7 endpoints) give `400 validation_error` with `{param: [message]}`. The UI maps a path to a form field by its last dot-separated segment; other paths are shown as a general form error.

### 1.3 Other conventions

- **Timestamps** are strings in the exact format of DATA_MODEL §1.1; the API never reformats them. **Partial dates** use the canonical strings.
- **Successful writes may return `warnings`** (so far only `inactive_code`: a restore brought back an inactive vocabulary code): an array of `{code, message, field}`.
- **Every HTTP write** uses channel `ui` (`restore` for the restore endpoints, `merge` for the merge and unmerge endpoints) and is attributed to the fixed actor name `user`, which is recorded as the revision's `author`, in `created_by`, `updated_by`, `deleted_by` and `resolved_by`, and as `field_meta.by`; a value set in the app gets `field_meta.src = manual` (DATA_MODEL §5). No request field selects a channel, an author or a provenance (DATA_MODEL §6.2). Responses keep their author fields, because the seed, imports and collectors write under their own names. Phase 2: accepting a proposal writes on channel `ui` with `revision.proposal_id` and the provenance of DATA_MODEL §16.4; a run started through the API (§7.2) and an import run (§7.9) write on channels `collector` and `import` in the server, under their own names.

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
- `participation`, `component`, `relation`, `indicator`, `evidence`, `vocabulary_term`, `saved_view` (Phase 3: the first five of these get table views too, `table_view: true` in meta; DATA_MODEL §3.5).

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
  "field_meta": {"name_en": {"src": "seed", "by": "seed", "at": "…", "locked": true, "verified": "unverified", "evidence_id": null, "restored_from_version": null, "raw_snapshot_ids": null}},
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
  - **Phase 3:** project and service add `portfolio_entry_basis`, `entry_period` and `entry_period_reason` (DATA_MODEL §8.3 items 6–7); event, document and participation carry `derived: {"period": "<code>"}`, the computed period of their date, and evidence `derived: {"document_period", "case_period"}` (DATA_MODEL §8.4); the other types have no `derived` key.
  - **Launch interval vs. displayed launch** (DATA_MODEL §8.3): `launch_start` and `launch_end` are the **launch interval** over all launch candidates, [earliest start, earliest end]; `launch`, `launch_precision`, `launch_basis` and `launch_event_id` describe the **displayed candidate** (the one that ends first). With one candidate the interval is that candidate's own bounds; candidates of different precision can widen it, e.g. launch events `2022` and `2022-03` give `launch: "2022-03"` with the interval 2022-01-01 – 2022-03-31. The period, the trajectory and their `imprecise_date` reason, the `launch` filter and sort (§4) and the export's `derived_launch_start`/`derived_launch_end` (§5) all use the interval; the UI shows it next to the displayed value whenever the two differ. A missing derived row gives the initial values (DATA_MODEL §8.1: period and war trajectory `unknown`, reason `no_date`) with `computed_at: null`.
- **Document `links`:** `origin` is provenance and read-only for clients; `matched_aliases`, `match_count` and `snippet` are read-only too (DATA_MODEL §1.2).
- **`virtual`:**
  - `open_comments` and `comment_count` for every type;
  - `project_in_paper_scope` (service), `subject_in_paper_scope` (event), `linked_in_paper_scope` (document);
  - Phase 2: `open_proposals` for project, service, event and document (DATA_MODEL §2.4);
  - Phase 3: `evidence_count` for every type that can be an evidence subject (DATA_MODEL §2.4); `period_unevidenced`, `derived_unevidenced`, `entry_unevidenced` and `adaptation_relation` (project, service), `services_new_in_war` and `services_adapted_in_war` (project), `citation_count` and `dimension_citation_count` (document), `subject_current_id`, `dimension` and `case_id` (evidence; DATA_MODEL §3);
  - detail responses add `open_comments_by_field` (`{"<field>": n, "": n for entity-level threads}`) and, in Phase 2, `open_proposals_by_field` (`{"<field>": n}` for open `update_field` proposals).
- **`observations`** (Phase 2): detail responses of project, service and document carry, as a top-level property next to `virtual`, the source observations bound to the record or to records merged into it (§7.5 shape, at most 50).
- **`refs`** gives the label of every non-null `ref` field, of the derived event and participation IDs (keys `derived.<name>`), of the virtual refs `subject_current_id` and `case_id` (Phase 3, keys `virtual.<name>`) and, for documents, of every link subject (key `links.<subject_id>`).
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
| `GET /api/stats` | `{"entities": {"project": {"total": 20, "unverified": 20, "deleted": 0}, "…": {}}, "open_comments": 3, "open_proposals": 12, "runs": {"running": {"id", "collector", "started_at"} \| null, "last_finished": {"id", "collector", "status", "finished_at"} \| null}}`. `total` and `unverified` count live rows only; `open_comments` counts the open, non-deleted root comments on all subjects; `open_proposals` and `runs` are Phase 2. Phase 3 adds `"documents": {"unscreened": n, "included": n, "excluded": n}` (live documents), `data_revision`, `data_as_of` and `derived_current` (§8.7). |
| `GET /api/lookup?types=project,service&q=<text>&limit=20[&f.…]` | `{"items": [{"id", "type", "label", "deleted", "context"}]}`. Matches label, names, slug and alias texts by normalised, case-folded prefix first, then FTS; ordered by match quality, then label. Optional `f.` filters apply per type (e.g. the parent-service picker passes `f.project_id=in:<project>`). `context` is a short disambiguation (e.g. the project of a service). |
| `GET /api/lookup?ids=a,b,c` | labels for any IDs, deleted ones included (`deleted: true`); unknown IDs are omitted |

**Lookup details:**
- Without `q` (and without `ids`) it lists non-deleted rows by label, e.g. for the parent-service picker with `f.project_id`.
- `types` defaults to the five Phase 1 table types, plus `component` from Phase 3 (any generic type is allowed, comments are not); `limit` is 1–100 (default 20). Rows matched by `q` are never deleted ones. Exact matches come before other prefix matches.
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
- **Phase 2:** project, service, event and document add the toggle "Open proposals" (`f.open_proposals=range:1..`); service, event and document add "Collected" (`f.created_by=contains:collector:`).
- **Phase 3:**
  - event and document replace their period presets with the **period chips** on their computed `period` (`f.period=in:<codes>`, DATA_MODEL §8.4), which also select `unknown` (undated or straddling); no type uses the `preset` kind any more, which stays defined;
  - "No evidence" (`f.evidence_count=eq:0`) for project, service, event, organization, component, participation, relation and indicator; project and service add "Derived from unsourced dates" (`f.derived_unevidenced=eq:true`);
  - component, participation, relation and indicator: unverified and open comments as well; participation adds "Focal organisation" (`f.organization_id=in:<focal_org_id>`) and the period chips on its computed `period`;
  - document adds "Undated" (`f.published=empty:true`) and "Not coded" (`f.dimension_citation_count=eq:0`, DATA_MODEL §21);
  - evidence: unverified, open comments, "Field evidence" (`f.target=contains:field:`) and the **dimension chips** (kind `chips` on `dimension`, codes `d1`…`d4`: the dimension evidence).

A toggle is active only if the URL contains exactly its key/value pair. Activating it replaces an existing filter on that field; deactivating it removes the parameter.

**`bulk_editable`** is true for editable, non-create-only fields of type `vocab`, `vocab_list` and `bool`, including `verification_status`.

**`exportable`** is true for fields that have a value per list row: every field except the virtual fields without one (the detail-only document `text`, which list responses omit, and the filter-only relation `endpoint`) and the filter-only Phase 3 reason fields (`period_reason`, `trajectory_reason`, `entry_period_reason`, exported as extra columns of their derived value, §5). Exactly these fields are accepted in `cols` (§5); the UI offers only them as table columns.

### 3.2 Generic entity endpoints

| Method and path | Body | Response |
|---|---|---|
| `GET /api/entities/{type}` | — (query grammar §4) | `{"items": [Item], "total": n, "page": 1, "page_size": 50}` |
| `GET /api/entities/{type}/facets?field=<name>&…` | — | `{"field": "kind", "values": [{"value": "e_service", "label": "E-service", "count": 12}], "empty_count": 3}`. All filters apply except the one on `field`. Vocabulary values include zero counts for active terms and are ordered by `sort_order`; inactive terms appear only when in use, and codes missing from the vocabulary are appended with the code as label. Boolean facets always return both values `"true"`/`"false"` (labels "Yes"/"No"). Refs are labelled and ordered by count (descending), then label; so is document `source_id` (Phase 3), labelled with the collector labels of `sources.yaml` (`manual` → "Manual"). Document `links` count suggested and confirmed links (like `in:`); their `empty_count` is the number of documents without any link row. The relation `endpoint` facet counts both ends (`empty_count` 0). Allowed for fields with filter `multiselect`, `bool` or `ref`; any other `field` → `400 bad_filter`. |
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
  - `RevisionSummary` = `{id, version, at, author, channel, action, note, changed_fields, restored_from, restored_from_version, batch_id, run_id, proposal_id}` (`run_id` and `proposal_id` filled from Phase 2 on, DATA_MODEL §6.2);
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
| `GET /api/revisions?entity_type=project,comment&channel=ui,seed&action=…&since=…&until=…&entity_id=&batch_id=&run_id=&proposal_id=&page=&page_size=` | `{"items": [{"id", "entity_type", "entity_id", "entity_label", "version", "at", "author", "channel", "action", "note", "changed_fields", "restored_from_version", "batch_id", "run_id", "proposal_id", "context"}], "total", "page", "page_size"}` |

Notes on `GET /api/revisions`:
- **Order:** newest first (`ORDER BY id DESC`).
- **`since`/`until`:** inclusive; each accepts a date (a UTC day: from its first or to its last microsecond) or an ISO 8601 timestamp with an explicit offset (`Z` or `±HH:MM`; seconds and up to 9 fractional digits optional; a naive timestamp → `400 validation_error`), normalised like a `datetime` value (DATA_MODEL §1.2). The UI sends local-day boundaries as timestamps such as `2026-09-30T21:00:00.000000Z`.
- **Lists:** `entity_type`, `channel` and `action` accept comma-separated lists of known values (DATA_MODEL §4). `entity_id`, `batch_id`, `run_id` and `proposal_id` match exactly (the run page links to `?run_id=…`, an import result to `?batch_id=<import id>`). There is no author filter (D-15): the channel tells changes made in the app (`ui`, `restore`, `merge`) from the seed, imports and collectors.
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

**Derived, virtual and system fields** are filterable like stored fields; a missing derived row counts as `unknown`. A derived date filter uses the derived row's `_start`/`_end`; for `launch` that is the launch interval over all candidates (§2), not the bounds of the displayed candidate. These are `launch`, `existed_by`, `period`, `war_trajectory`, `portfolio_entry`, `open_comments`, `comment_count`, `open_proposals` (Phase 2), the `*_in_paper_scope` fields, `created_at`, `updated_at`, `deleted_at`, `created_by`, `updated_by` and `deleted_by`; Phase 3 adds `entry_period`, `existed_before_invasion`, the reason fields `period_reason`, `trajectory_reason` and `entry_period_reason`, the computed `period` of events, documents and participations, `evidence_count`, `period_unevidenced`, `derived_unevidenced`, `entry_unevidenced`, `adaptation_relation`, `services_new_in_war`, `services_adapted_in_war`, document `citation_count`, `dimension_citation_count` and `source_id`, and evidence `subject_current_id`, `dimension`, `case_id`, `document_period` and `case_period` (DATA_MODEL §19.3).

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
| derived vocab (`period`, `war_trajectory`; Phase 3 also `entry_period`, the reason fields and the computed periods) | as `vocab`; a missing row counts as `unknown` (the reasons as empty) |
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
- **Phase 3:** `entry_period` follows the derived rules above (`derived_entry_period`, `derived_entry_period_label`, `derived_entry_period_reason`; the portfolio entry adds `derived_portfolio_entry_basis`); `existed_before_invasion` is `derived_existed_before_invasion`; the computed periods are `derived_period` (events, documents, participations), `derived_document_period` and `derived_case_period` (evidence), each with its `_label`. The reason fields are filter-only: their values are the `derived_<name>_reason` columns above.
- **Virtual fields:** their values (`open_comments`, `comment_count`, the `*_in_paper_scope` booleans; Phase 3 `evidence_count` and the other virtual fields of DATA_MODEL §19.3; the virtual refs `subject_current_id` and `case_id` as ID plus `_label`, the virtual `dimension` as code plus `_label`). **System columns:** as stored (timestamps as text).
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

**Startup self-check** (`create_app` and `mdt serve`): the app refuses to start with a clear message (the CLI prints `error: …` and exits 1) when the SQLite version or FTS5 is missing (DATA_MODEL §11), the database file does not exist (run `mdt db upgrade` and `mdt seed` first) or is not at the Alembic head, or `codebook/parameters.yaml` or (Phase 2) `sources.yaml` is unusable. Startup never creates the database or runs migrations or the seed; `create_app` creates nothing at all, while `mdt serve`, like every `mdt` command, first creates a missing `DATA_DIR` directory. The other commands that read or write data (`mdt seed`, `recompute`, `check`, `reindex`, `collect`, `runs`, `import`) make the same database check first (`error: …`, exit 1, without SQL in the message and without creating an empty database file, so a later `mdt serve` still advises `mdt db upgrade` and `mdt seed`); a database file without any schema revision is advised the same way.

**Collector runs (Phase 2):** `POST /api/runs` starts a run in a daemon thread of the server process; at most one run runs at a time in the whole database (CLI included). At startup the app recovers stale runs, and on shutdown it asks its running run to stop (`docs/COLLECTORS.md` §6.1–§6.3). Uploaded files and raw snapshots live under `DATA_DIR/raw` (DATA_MODEL §14.1).

**App and routing:**
- **App options:** `FastAPI(debug=False, docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)`: there is no OpenAPI document and no docs page (this document describes the API), and the app never redirects (`/api/entities/project/` is a 404); FastAPI's telemetry integration is switched off. API routes come first.
- **`/assets/*`:** served by Starlette `StaticFiles(directory=FRONTEND_DIST/"assets")`; a missing asset is a 404 in the error envelope, never `index.html`; conditional requests (`If-None-Match`, `If-Modified-Since`) get `304`.
- **Root files:** the files directly in `FRONTEND_DIST` (e.g. `favicon.svg`, `index.html`) are served by exact name with `Cache-Control: no-cache`; their names are read at startup, so a build that adds a root file is served after a restart.
- **SPA fallback:** every other `GET`/`HEAD` outside `/api/` returns `index.html` with `Cache-Control: no-cache`, so a new build is picked up on the next page load.
- **Other methods** on non-API paths → 405 (`Allow: GET, HEAD`). Unknown `/api` paths → 404. `HEAD` requests to API routes get 405 (FastAPI adds no `HEAD` routes); the UI never sends them.
- **Without a frontend build:** if `FRONTEND_DIST` has no `index.html`, the app still starts, the API works and `GET`/`HEAD` requests to non-API paths return `503 frontend_not_built` with a hint to run `make build`. Docker images always contain the build.

**No security layer** (D-15): the app sets no security headers and has no host allowlist, origin checks or request size limits; access control is the job of the server's environment. The default binding to 127.0.0.1 (README) only decides where the app is reachable.

## 7. Phase 2 endpoints (data acquisition)

### 7.1 Conventions

- Lists take `page` (1–1 000 000, default 1) and `page_size` (1–500, default 50) and return `{"items", "total", "page", "page_size"}`; list filters are plain query parameters (not the `f.` grammar of §4), comma-separated where they accept several values; unknown values of known parameters → `400 validation_error`.
- Bodies are strict (§3.2 notes): unknown keys → `400`. `note` fields are optional (≤ 2 000 characters) unless stated.
- Responses carry `refs` (labels of every record ID they mention, as in §3.2) where they mention records.
- Timestamps and partial dates as in §1.3. The tables behind these endpoints are DATA_MODEL §14.

### 7.2 Collectors and runs

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/collectors` | — | `{"collectors": [Collector]}` |
| `GET /api/collectors/{name}` | — | `{"collector": Collector, "recent_runs": [Run]}` (the 10 newest); unknown name → 404 |
| `POST /api/runs` | `{"collector", "mode": "incremental", "params": {}}` | `202 {"run": Run}` (status `running`; with `COLLECTOR_RUN_INLINE`, the finished run); errors below |
| `GET /api/runs` | `collector`, `status`, `trigger`, `page`, `page_size` | runs, newest `started_at` first |
| `GET /api/runs/{id}` | — | `{"run": Run}` |
| `GET /api/runs/{id}/fetches` | `outcome`, `host`, `purpose`, `page`, `page_size` | `FetchLogEntry` items in request order |
| `GET /api/runs/{id}/messages` | `level`, `code`, `page`, `page_size` | `RunMessage` items in order; `refs` for `subject_id` |
| `POST /api/runs/{id}/cancel` | `{}` | `{"run": Run}` with `cancel_requested_at` set; a finished run → `409 invalid_state {state}` |

- `Collector` = `{name, label, source, builtin, enabled, available, unavailable_reason, needs_server_check, modes, params, hosts: [{host, min_interval_s}], exclude_hosts, licence: {code, statement}, declaration: {<entity type>: {creates, writes, propose_only, discontinued}}, last_run: Run | null, running_run_id, observations: {total, present, missing}, open_proposals}`. Only collectors that are configured in `sources.yaml` and implemented (a module `mdt.collectors.<name>` with `COLLECTOR`, `docs/COLLECTORS.md` §2) are listed; any other name answers 404. `available` is false with `unavailable_reason` = `disabled` or `contact_email_missing` (the latter never for the built-in `tagger` or in replay mode, `docs/COLLECTORS.md` §4.4); `params` lists the run parameters the collector supports (`docs/COLLECTORS.md` §6.4); `hosts` lists the configured per-host intervals.
- `Run` = `{id, collector, collector_label, trigger, mode, params, status, started_at, finished_at, heartbeat_at, duration_s, cancel_requested_at, complete_listing, stats, error, code_version, config_hash, message_counts: {error, warning, info}}`; `duration_s` of a running run is the time elapsed so far. The `host` filter of the fetch log matches exactly.
- `FetchLogEntry` = `{id, at, method, url, host, purpose, attempt, status, outcome, bytes, duration_ms, raw_snapshot_id, retry_after_s, error}`.
- `RunMessage` = `{id, at, level, code, message, url, raw_snapshot_id, subject_id, details}`.
- **`POST /api/runs` errors:** unknown collector → 404; an unknown mode or parameter, or a parameter the collector does not support → `400 validation_error`; another run is running (CLI or server) → `409 run_in_progress {run_id}`; disabled, or `CONTACT_EMAIL` missing or a placeholder → `409 collector_unavailable {reason}`. There is no queue: a refused start is simply tried again later.

### 7.3 Raw snapshots

| Method and path | Response |
|---|---|
| `GET /api/snapshots/{id}` | `{"snapshot": Snapshot}` with `Snapshot` = `{id, run_id, source_id, via, url, final_url, redirects, http_status, fetched_at, headers, content_type, filename, sha256, size}` |
| `GET /api/snapshots/{id}/body` | the decompressed body (DATA_MODEL §14.1), `Content-Type` = the stored `content_type` (else `application/octet-stream`), always `Content-Disposition: attachment; filename="<filename, else id.ext>"` so a stored HTML page is downloaded and never rendered in the app; `Cache-Control: private, max-age=31536000, immutable` (snapshots never change) |

### 7.4 Proposals

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/proposals` | `state` (default `open`; `all`), `kind`, `collector`, `entity_type`, `subject_id` (matches `subject_id` or `related_id`), `run_id` (matches `first_run_id` or `last_run_id`), `field`, Phase 3 `document_id` (§8.4), `sort` (`-last_seen_at` default, `last_seen_at`, `-created_at`, `created_at`), `page`, `page_size` | `Proposal` items with `refs` |
| `GET /api/proposals/summary` | — | `{"open": n, "by_kind": {kind: n}, "by_collector": {collector: n}, "by_entity_type": {type: n}, "patterns": [{"pattern_id", "open", "accepted", "accepted_modified", "rejected", "precision"}]}`; `precision` = (accepted + accepted_modified) / (accepted + accepted_modified + rejected) of `create_event` proposals per pattern, null without decisions |
| `GET /api/proposals/{id}` | — | `{"proposal": Proposal, "refs": {…}, "texts": {"current", "proposed"} \| null}`; `texts` holds both document texts for a text-version proposal (DATA_MODEL §15.6), else null |
| `POST /api/proposals/{id}/accept` | `{"values": null, "match_id": null, "note": null}` | `{"proposal": Proposal, "changed": true, "result_id", "revision_ids": [n], "batch_id"}` |
| `POST /api/proposals/{id}/reject` | `{"note"}` (required) | `{"proposal": Proposal}` |
| `POST /api/proposals/bulk` | `{"ids": [...], "action": "accept"\|"reject", "note"}` | `{"batch_id", "results": [{"id", "status": "accepted"\|"rejected"\|"superseded"\|"stale"\|"needs_values"\|"error", "error": null}]}` |

- `Proposal` = `{id, kind, state, entity_type, subject_id, related_id, field, current_value, proposed_value, live_value, payload, collector, first_run_id, last_run_id, raw_snapshot_id, source_url, quote, locator, observation_id, seen_count, created_at, last_seen_at, decided_at, decided_by, decision_note, result_id}`. `live_value` is the subject's current value of `field` (`update_field`) or `status` (`possibly_discontinued`), read at request time, so the UI shows current against proposed without another request; null for the other kinds. `refs` label the subject, the related record, `result_id`, the `create_entity` candidates, the event subject and the cited document.
- **Accept** (DATA_MODEL §16.4): `values` = the edited fields (edit & accept): for `create_entity` any `in_create` field of the type, and for a project proposal `in_paper_scope` and `scope_note` are required (optional `slug`, else generated); `match_id` = an existing live record of the proposal's type (`create_entity` only: link to existing); `possible_duplicate` requires `values`: `{"duplicate_id"}` for documents, `{"survivor_id", "fields"}` for services and projects (the merge of §7.6, with `fields` as there). `changed: false` with state `superseded` when nothing was left to write.
- **Errors:** a proposal that is not open → `409 invalid_state {state}`; a deleted subject → `409 entity_deleted`; invalid or missing `values` → `400 validation_error` (field paths `values.<field>`); a merge conflict → `409 merge_conflict`; `unique_violation` and `reference_deleted` as for entity writes; reject without a note → `400`.
- **Bulk:** at most 500 IDs, no duplicates; `reject` needs `note`; each proposal is its own write unit. A bulk accept takes no `values`: proposals that need them (new projects, duplicates) get `needs_values`, and `update_field` proposals whose `live_value` differs from `current_value` get `stale`; both stay open.

### 7.5 Observations

| Method and path | Query | Response |
|---|---|---|
| `GET /api/observations` | `collector`, `entity_type`, `subject_id` (bound to the record or to records merged into it), `present` (`true`/`false`), `bound` (`true`/`false`), `q` (case-folded substring of `key`, `label` or `url`), `page`, `page_size` | `Observation` items ordered by collector, key; `refs` |

- `Observation` = `{id, collector, key, entity_type, subject_id, bound_by, bound_at, external_id, url, label, first_seen_at, first_seen_run, last_seen_at, last_seen_run, present, missing_since_at, missing_runs, last_snapshot_id, details}`. Observations are bound by the collectors' matching rules and by accepted `create_entity` proposals (DATA_MODEL §15.3, §16.4); there is no endpoint to bind them by hand.

### 7.6 Merge and unmerge

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/entities/{type}/{id}/merge-preview?merged_id=` | — | `{"fields": [{"name", "survivor", "merged", "list": bool, "default": "survivor"}], "repoint": {"service": 3, "event": 2, …}, "conflicts": [{kind, id, label, message}]}` |
| `POST /api/entities/{type}/{id}/merge` | `{"merged_id", "fields": {"name_en": "merged", "aliases": "union"}, "note", "proposal_id": null}` | `{"item": Item, "merge_id", "batch_id", "revision_ids": [n]}` (the survivor) |
| `POST /api/entities/{type}/{id}/unmerge` | `{"note"}` | `{"item": Item, "merge_id", "batch_id", "revision_ids": [n], "skipped": [{"entity_type", "id", "field", "current"}]}` (the restored record) |

- `type` must be `project` or `service` (else `400 validation_error`; merging organisations and components is deferred, `docs/COLLECTORS.md` §14). For merge, `{id}` is the survivor; `fields` maps field names to `survivor` (default), `merged` or `union` (list fields only). Rules and errors: DATA_MODEL §18 (`409 invalid_state`, `409 merge_conflict`, `409 unique_violation`). `proposal_id` names an open `possible_duplicate` proposal of the pair; it is then accepted with `result_id` = the survivor.
- For unmerge, `{id}` is the merged record; it must be deleted with `merged_into` set and its latest merge not yet unmerged (else `409 invalid_state {state}`). `skipped` lists the references that changed after the merge and were left as they are. The plain undelete endpoint refuses a merged record (`409 invalid_state {state: "merged"}`).

### 7.7 Uploads

`POST /api/uploads?filename=<name>`: the request body is the raw file (any `Content-Type`; no multipart). The server streams it into the snapshot store and returns `201 {"upload": Snapshot, "suggested": Suggested}` (`via = upload`, `source_id = manual`, `content_type` per `docs/COLLECTORS.md` §5). `Suggested` = `{title, language, publisher, extraction_method, char_count, warnings: [{code, message, field}]}`, the defaults derived from the file (`docs/COLLECTORS.md` §10.1; warning codes `no_text_layer`, `no_text`, `unsupported_encoding`; the import page ignores it). A missing or empty `filename` (base name only, path parts are dropped) or an empty body → `400 validation_error`. There is no size limit (D-15). Uploads are used by manual documents (§7.8) and imports (§7.9).

### 7.8 Manual documents

| Method and path | Body | Response |
|---|---|---|
| `POST /api/documents/fetch` | `{"url"}` | `201 {"snapshot": Snapshot, "suggested": Suggested}` |
| `POST /api/documents/manual` | `{"snapshot_id", "title", "url", "retrieved_at", "doc_type", "language", "publisher", "published", "published_basis", "published_text", "license", "note"}` | `201 {"item": Item, "revision_id", "warnings": [{code, message, field}]}` |

- **Fetch** (`docs/COLLECTORS.md` §10.3): fetches the URL with the polite client within 60 s and stores it as a snapshot (`source_id = manual`, `run_id` null); a Wayback capture URL is fetched as an archived copy (`via = wayback:<timestamp>`). Errors, in this order: an invalid `url` → `400 validation_error` on `url`, before anything is fetched (the URL rule of DATA_MODEL §1.2, e.g. another scheme than http(s), user information or whitespace; a Wayback capture URL whose original lacks `http(s)://`); a canonical URL that a live document already has → `409 unique_violation` (checked before fetching); `CONTACT_EMAIL` missing or a placeholder → `409 collector_unavailable {reason: "contact_email_missing"}`; failures → `502 fetch_failed {reason, status}` (reasons in `docs/COLLECTORS.md` §10.3).
- **Create** from an upload or a fetched snapshot (`snapshot_id`, required; `source_id = manual`). For an upload, `url` is optional (the source address of the file) and then needs `retrieved_at`. For a fetched snapshot, `url` and `retrieved_at` must not be given: they are the fetched URL (for an archived copy the original URL, with the capture URL in `archive_urls`) and the fetch time. The other fields are document fields (DATA_MODEL §3.4), which the form pre-fills from `suggested`; `note` is the revision note. Warnings: `no_text_layer`, `no_text` (a type without text extraction).
- **Create errors:** an unknown snapshot or one that is not a manual upload or fetch → `400 validation_error` on `snapshot_id`; an unsupported text encoding → `400 validation_error` on `snapshot_id`; a canonical URL that a live document already has → `409 unique_violation`; field validation → `400`.

### 7.9 Imports

| Method and path | Body / query | Response |
|---|---|---|
| `POST /api/imports/preview` | `{"upload_id", "entity_type", "sheet": null}` | `{"sheets": [names] \| null, "columns": [headers], "preview": [[cells]], "suggested_mapping": {column: field}, "importable_fields": [names], "key_fields": [names]}`; writes nothing |
| `POST /api/imports/dry-run` | `{"upload_id", "entity_type", "sheet", "mapping", "key_field"}` | `{"plan": Plan}`; writes nothing |
| `POST /api/imports` | `{"upload_id", "entity_type", "sheet", "mapping", "key_field", "note"}` | `201 {"import": ImportRun, "result": Plan}`; the import's ID is the `batch_id` of its revisions |
| `GET /api/imports` | `page`, `page_size` | `ImportRun` items, newest first |
| `GET /api/imports/{id}` | — | `{"import": ImportRun}` |

- `ImportRun` = `{id, upload_id, filename, file_label, entity_type, sheet, status, mapping, key_field, note, stats, errors, error, created_at, finished_at}` (`status` `done` or `failed`; `errors` = the stored row errors and conflicts).
- `Plan` = `{stats: {rows, create, update, unchanged, conflicts, errors}, rows: [{row, action, id, changes, conflicts, errors}]}` (`docs/COLLECTORS.md` §9.4; at most 500 row items).
- `entity_type` is one of the five table types; an upload that is neither CSV nor XLSX, a CSV that is not UTF-8, a missing sheet or duplicate headers → `400 validation_error`; an invalid mapping (unknown or non-importable field, a field mapped twice, a `key_field` the type does not support) → `400 validation_error` (paths `mapping.<column>`, `key_field`).
- The run executes synchronously in the request (each row one write unit on channel `import`, DATA_MODEL §17.1). Running the same file again is a new import; rows without differences write nothing.

## 8. Phase 3 endpoints (analysis)

### 8.1 Conventions

As in §7.1: strict bodies, `note` ≤ 2 000 characters, `refs` for every record ID a response mentions, lists with `page`/`page_size` where they page, plain query parameters except where a section says that the list grammar of §4 applies. Writes use channel `ui` (DATA_MODEL §6.2). Data rules: DATA_MODEL §19–§23.

### 8.2 Document text and queue

| Method and path | Query | Response |
|---|---|---|
| `GET /api/documents/{id}/text` | `text_hash` (optional; default the current version) | `DocumentText` |
| `GET /api/documents/{id}/neighbours` | the list grammar of the document type (§4: `f.*`, `q`, `sort`) = the queue | `{"in_queue", "position", "total", "unscreened", "previous_id", "next_id", "next_unscreened_id", "refs"}` |

`DocumentText` =

```json
{
  "document_id": "doc_…", "text_hash": "…", "current": true,
  "text": "…", "char_count": 18452,
  "retrieved_at": "…", "raw_snapshot_id": "raw_…", "extraction_method": "turbo-stream",
  "marks": [
    {"kind": "evidence", "start": 120, "end": 245, "id": "evd_…", "subject_id": "prj_…", "target": "dimension:D1", "codes": [], "label": "…"},
    {"kind": "proposal", "start": 300, "end": 411, "id": "prp_…", "subject_id": "svc_…", "event_type": "launch", "label": "…"}
  ],
  "marks_truncated": false,
  "refs": {}
}
```

- **Text:** `text` is the stored text of the version (never HTML; the UI renders it as plain text); a document without text answers `text: null`, `char_count: 0`, no marks. `current` says whether the version is the document's current one; `retrieved_at`, `raw_snapshot_id` and `extraction_method` are those of the requested version (for an earlier one, from the first revision that recorded it). A `text_hash` that is not a text version of the document (DATA_MODEL §21) → 404. Deleted documents are served too (read-only in the UI).
- **Marks** (offsets in code points of this version, DATA_MODEL §20.1; sorted by `start`, `end`, `kind`, `id`): `evidence` = the live anchored evidence rows of this document and version (`label` = the evidence label, §2); `proposal` = the open `create_event` proposals whose `payload.evidence` names this document and version (`label` = `<event type label> · <subject label>`). At most 5 000 marks, evidence first; `marks_truncated` says whether some were left out.
- **Neighbours** (DATA_MODEL §21, queue): `deleted` is ignored (a queue never holds deleted documents); `in_queue` = the document matches the queue's filters and `q`; `position` = its 1-based place in the queue order evaluated with `OR id = <id>`; `total` = the documents matching the queue (the current one counted only when it matches); `unscreened` = the unscreened documents in the queue; `previous_id`, `next_id` = its neighbours in that order (null at the ends); `next_unscreened_id` per DATA_MODEL §21 (null when the queue has no other unscreened document). A malformed filter or sort → `400 bad_filter` / `bad_sort`; an unknown document → 404.

### 8.3 Evidence capture

| Method and path | Body | Response |
|---|---|---|
| `POST /api/evidence/capture` | `Capture` (below) | `201 {"evidence": Item, "record": Item \| null, "subject": Item, "revision_ids": [n], "batch_id", "warnings": []}` |

`Capture` =

```json
{
  "subject_id": "prj_…", "record": null, "values": null,
  "target": "dimension:D1", "codes": [],
  "document_id": "doc_…", "text_hash": "…", "char_start": 120, "char_end": 245, "quote": "…",
  "url": null, "retrieved_at": null, "archive_url": null,
  "locator": null, "description": null,
  "verify_field": false, "note": null
}
```

- **Subject:** exactly one of `subject_id` (an existing record of a type evidence can concern: project, service, event, document, organization, participation, component, relation or indicator, DATA_MODEL §3.5) and `record` = `{"type", "data"}` with `type` one of `event`, `participation`, `relation`, `indicator`, `component`, `organization` and `data` as in `POST /api/entities/{type}` (errors with paths `record.data.<field>`). **`values`** (only with `subject_id`): fields of the subject in the form of a PATCH's `changes` (§3.2), written first (errors with paths `values.<field>`); given with a `field:` target, it must contain that field (DATA_MODEL §20.2 step 1).
- **Source**, exactly one form (else `400 validation_error` on `document_id`): a **passage** (`document_id`, `text_hash`, `char_start`, `char_end`, optional `quote`; all four or none of the first group), a **whole document** (`document_id` alone, optional `quote`), or a **URL** (`url` and `retrieved_at`, optional `archive_url` and `quote`). Rules: DATA_MODEL §20.2 and §7 (citing a document: `retrieved_at` comes from the document, and a typed quote on a document with text must occur in it exactly once and is then anchored).
- `target` defaults to `entity`; `codes` only with a `dimension:` target; `verify_field` only with a `field:` target (DATA_MODEL §20.2 step 4, §20.5).
- **One write unit** with one new `batch_id`: the optional record or the subject's `values`, the evidence row, the optional field verification (`revision_ids` in that order; `values` that change nothing write no revision); `note` is the revision note of each of them. `subject` is the subject after the write (with its new `virtual.evidence_count` and, after `values` or a verification, its fields and `field_meta`).
- **Errors:** `400 validation_error` (paths `subject_id`, `record`, `record.data.<field>`, `values`, `values.<field>`, `target`, `codes`, `document_id`, `char_start`, `char_end`, `quote`, `url`, `retrieved_at`, `verify_field`); `409 reference_deleted` for a deleted subject or document; `409 invalid_state {state: "text_changed", text_hash: <current>}` when `text_hash` is not the document's current version (the UI reloads the text and keeps the person's choices); `409 unique_violation` (e.g. a duplicate relation, an organisation slug); unknown IDs are validation errors on their field, as for entity writes. Capture never changes the document's links (DATA_MODEL §20.2).
- The generic endpoints keep working for evidence: PATCH edits the editable fields (the anchor fields of anchored evidence are refused, DATA_MODEL §20.3), and `POST /api/entities/evidence` creates URL and document citations under the same rule for citing a document; it refuses `char_start` and `char_end`, which are system fields from Phase 3.

### 8.4 Proposals concerning a document

`GET /api/proposals?document_id=<id>` (with the other parameters of §7.4) returns the proposals whose `subject_id` or `related_id` is the document, or whose `payload.evidence.document_id` is it (`create_event` proposals that cite a passage of it). The document view lists them (`docs/UI.md` §9.2); decisions use §7.4.

### 8.5 Timeline

`GET /api/timeline` returns the events of a set of projects or services, grouped into lanes, with everything the client needs to draw them deterministically (`docs/UI.md` §9.4).

| Parameter | Values | Meaning |
|---|---|---|
| `subject_type` | `project` (default) · `service` | one lane per subject of this type |
| list grammar of that type | `f.*`, `q`, `sort` (§4) | selects the subjects; `sort` orders the lanes within a group (default: label, `mdt_sortkey`); `deleted` is ignored (live subjects only) |
| `ids` | comma-separated IDs of that type (≤ 500) | combined with the filters by AND |
| `event_types` | comma-separated `event_type` codes | default all; an unknown code → 400 |
| `include_services` | `true` · `false` (default; projects only) | project lanes also show the events of the project's live services; such events name their service (`service_id`) |
| `group_by` | `cluster` (default for project; services: their project's cluster) · `project` (default for service) · `none` | lane groups |
| `from`, `to` | `YYYY-MM-DD` (each optional) | the window: dated events whose interval does not intersect it are left out and counted; undated events are listed whatever the window |
| `disputed` | `exclude` (default) · `include` | disputed events, which derived values ignore (DATA_MODEL §8.2) |
| `evidence` | `all` (default) · `with` | `with` shows only events with at least one live evidence row |

Response:

```json
{
  "subject_type": "project",
  "parameters": {"ministry_founded": "2019-08-29", "full_scale_invasion": "2022-02-24"},
  "periods": [
    {"code": "pre_ministry", "label": "Before the ministry", "start": null, "end": "2019-08-28"},
    {"code": "pre_invasion", "label": "Ministry, before the full-scale invasion", "start": "2019-08-29", "end": "2022-02-23"},
    {"code": "full_scale_war", "label": "Full-scale war", "start": "2022-02-24", "end": null}
  ],
  "domain": {"start": "2019-01-01", "end": "2026-12-31"},
  "groups": [{"key": "digital_public_services_infrastructure", "label": "…", "lane_ids": ["prj_…"]}],
  "lanes": [{
    "id": "prj_…", "type": "project", "label": "Diia", "group_key": "…", "project_id": null,
    "derived": {"period": "…", "period_reason": null, "entry_period": "…", "war_trajectory": "…", "trajectory_reason": null, "launch": "2020-02", "launch_start": "…", "launch_end": "…", "existed_by": null, "portfolio_entry": null},
    "events": [Event], "undated": [Event],
    "portfolio": [{"participation_id": "par_…", "role": "operator", "start": "2023-01", "start_start": "…", "start_end": "…", "start_basis": "stated_in_source", "end": null, "end_start": null, "end_end": null, "end_basis": null}]
  }],
  "event_types": [{"code": "launch", "label": "Launch", "counts_as_modification": false, "sort_order": 40}],
  "counts": {"lanes": 20, "events": 57, "undated": 4, "by_period": {"pre_ministry": 1, "pre_invasion": 18, "full_scale_war": 30, "unknown": 8}, "without_evidence": 12, "disputed_excluded": 1, "outside_window": 0},
  "data_revision": 4812, "data_as_of": "2026-11-02T10:00:00.000000Z",
  "refs": {}
}
```

- `Event` = `{id, subject_id, subject_label, service_id, event_type, date, date_start, date_end, date_precision, date_basis, date_text, description_en, verification_status, period, evidence_count}`; `period` is its computed period (DATA_MODEL §8.4); `service_id` is set only for a service's event shown in its project's lane (`include_services`); `undated` holds the events without a date.
- `portfolio`: the focal organisation's live, not disputed participations in a portfolio role whose subject is the lane's subject (DATA_MODEL §8.3 item 6), ordered by start; `end` null = open-ended. The lane `derived` values are those of the subject itself (project values use project events only, DATA_MODEL §8.2).
- **Domain** (deterministic, never from the current date): `from`/`to` when given; otherwise 1 January of the earliest of the year of the earliest shown event start (an archive bound counts with its `date_end`), the year of the earliest portfolio start and the year of `ministry_founded`, to 31 December of the latest of the year of the latest shown event end, the year of the latest portfolio end and the year of `full_scale_invasion`.
- **Order:** groups by the cluster vocabulary's `sort_order` (subjects without a cluster last, as "No cluster"), by project label for `project`, one group for `none`; lanes as stated above; events by `date_start`, `date_end`, the event type's `sort_order`, `id`; undated events by `id`.
- `counts.by_period` counts the shown dated and undated events by their computed period and `counts.without_evidence` the shown events without evidence, so a figure can state both; `data_revision` and `data_as_of` stamp the data state (§8.7).
- **Limits:** more than 500 lanes or 20 000 events → `400 validation_error` `{"lanes": [...]}` or `{"events": [...]}` ("narrow the filters"). Malformed filters → `400 bad_filter`/`bad_sort`; other invalid parameters → `400 validation_error`.

### 8.6 Crosstab and coverage

| Method and path | Query | Response |
|---|---|---|
| `GET /api/entities/{type}/crosstab` | `row`, `col` (field names) and the list grammar (§4: `f.*`, `q`, `deleted`) | `Crosstab` |
| `GET /api/entities/{type}/coverage` | the list grammar | `Coverage` |

These two generic endpoints serve the dashboard (`docs/UI.md` §9.5) for any table type. Every crosstab count and coverage's `filled` and `empty` counts are reproduced by the list endpoint with a filter the client can build; coverage's `verified`, `disputed` and `with_evidence` read `field_meta` and evidence, which no list filter expresses, so they have no table link (the dataset bundle's `provenance_summary.csv`, `field_provenance.csv` and `csv/evidence.csv` recompute them).

```json
{
  "type": "project",
  "row": {"field": "paper_cluster", "label": "Paper cluster", "multi": false},
  "col": {"field": "period", "label": "Period", "multi": false},
  "rows": [{"value": "digital_public_services_infrastructure", "label": "…", "count": 6}, {"value": null, "label": "(empty)", "count": 1}],
  "cols": [{"value": "pre_ministry", "label": "…", "count": 1}, {"value": "pre_invasion", "…": "…"}, {"value": "full_scale_war", "…": "…"}, {"value": "unknown", "…": "…"}],
  "cells": [[1, 4, 1, 0], [0, 0, 0, 1]],
  "total": 20,
  "data_revision": 4812, "data_as_of": "…",
  "refs": {}
}
```

- **Records:** those the list endpoint returns for the same `f.*`, `q` and `deleted`; every filter applies, also one on `row` or `col`.
- **Fields:** `row` and `col` are two different fields that facets accept (filter `multiselect`, `bool` or `ref`, §3.2; Phase 3 adds the derived and virtual fields of DATA_MODEL §19.3 and document `source_id`); anything else → `400 validation_error` on `row` or `col`. A field with more than 500 values → `400 validation_error`.
- **Values** as in facets (§3.2): every active vocabulary term in `sort_order` (inactive terms and unknown codes only when used), booleans `true`/`false`, refs and document `source_id` by count, then label; an `(empty)` value (`value: null`) when a record has none. `rows[].count` and `cols[].count` are the totals per value, `total` counts records. **Multi-valued** fields (`vocab_list`, document links) count a record once per value (`multi: true`), so the totals per value can exceed `total`.
- **Cell links:** the records of a cell are those of the list endpoint with the request's query plus the row and the column filter, written as the table writes a facet value (UI §3): `in:` for vocab, ref and `source_id`, `any:` for `vocab_list`, `eq:` for bool, `empty:true` for the `(empty)` value, `in:` for document links (suggested and confirmed, as facets count them); a filter on the same field in the request is replaced by the cell's.
- `Coverage` = `{"type", "records", "fields": [{field, label, group, filled, empty, verified, disputed, with_evidence}], "data_revision", "data_as_of"}` for the same records: one entry per tracked, editable field of the type except `notes` and `verification_status`, in registry order; `filled` and `empty` by the meaning of empty (DATA_MODEL §1.2); `verified` and `disputed` = records whose `field_meta` entry for the field says so; `with_evidence` = records with at least one live evidence row with `target = field:<name>` whose `subject_id` is the record (field evidence supports the value of the record it was captured for, so a merged record's field evidence does not count for its survivor, DATA_MODEL §18).

### 8.7 Data revision

- `data_revision` (integer) is the highest `revision.id` and `data_as_of` that revision's `at`, read in the same transaction as the data they stamp (DATA_MODEL §23.5). `GET /api/stats`, the timeline, crosstab and coverage responses, the export manifests and the codebook export carry them, and figure captions and crosstab files print them with the cut-off dates and the app version, on which derived and computed values also depend (DATA_MODEL §23.5), so every number can be matched with a bundle of the same data revision.
- `GET /api/stats` also carries `derived_current` (bool): false while the stored derived-inputs hash differs from the current inputs (DATA_MODEL §8.1); the UI then shows the banner "Derived values are out of date: run mdt recompute", and exports are refused (§8.8.1).

### 8.8 Exports

#### 8.8.1 Downloads

| Method and path | Query | Response |
|---|---|---|
| `GET /api/exports/dataset` | — | the dataset bundle (ZIP, §8.8.2), built in the request |
| `GET /api/exports/qda` | — | the QDA corpus (ZIP, §8.8.3), built in the request |
| `GET /api/codebook/export` | `format` = `md` (default) · `csv` | the codebook file (§8.8.4), generated in the request |

- **Building** (DATA_MODEL §23.4): the derived-values check, one read transaction, a temporary file, the privacy guard, then the download with `Content-Length`; the temporary file is deleted afterwards. A request takes as long as the build (seconds; about a minute for a large dataset with its XLSX file), so a reverse proxy should allow that read timeout (§1.4). There is no job list: the app has one user (D-15).
- **Errors:** derived values out of date → `409 invalid_state {state: "derived_out_of_date"}`; a privacy-guard hit → `409 privacy_check_failed {file, record_id}` (`record_id` null for files without records); an invalid `format` → `400 validation_error`.
- **Headers:** `Content-Type: application/zip` (codebook: `text/markdown; charset=utf-8` or `text/csv; charset=utf-8`), `Content-Disposition: attachment; filename="mdt-dataset-<YYYYMMDD-HHMMSS>.zip"` (likewise `mdt-qda-…` and `codebook-<…>.<md|csv>`; UTC), `Cache-Control: no-store`. The UI downloads them like view exports (§5: `fetch` → Blob → `a[download]`).

#### 8.8.2 Dataset bundle

```
mdt-dataset-<YYYYMMDD-HHMMSS>.zip
  README.md                     what the bundle holds, conventions, content policy, attribution, how to verify
  manifest.json                 counts, files with size, SHA-256 and rows, provenance of the export
  SHA256SUMS                    "<sha256>  <path>" per file except itself, sorted by path
  dataset.json                  every record as JSON (below)
  dataset.xlsx                  one sheet per table (below)
  csv/<type>.csv                project, service, event, document, organization, component,
                                participation, relation, indicator, evidence
  csv/document_link.csv         the documents' links
  csv/field_provenance.csv      one row per exported record and field with provenance and licence
  csv/provenance_summary.csv
  csv/merges.csv                the merge log
  csv/sources.csv               the source register with licences
  csv/source_observation.csv    what the collectors saw in their sources (crawl times)
  codebook/codebook.md  codebook/codebook.csv  codebook/parameters.yaml  codebook/CODEBOOK.md
```

- **Records:** the live records of the ten table types (DATA_MODEL §23.2), sorted by `id`.
- **`csv/<type>.csv`:** `id`, then every `exportable` field of the type in registry order with the column rules of §5 (vocab codes plus `_label`, partial dates as four columns, refs plus `_label`, derived fields prefixed `derived_` with their extra columns, lists joined with `"; "`, booleans `true`/`false`, UTF-8 with BOM, `QUOTE_ALL`), except: the document `links` (in `document_link.csv`), the counts `open_comments`, `comment_count` and `open_proposals`, and `deleted_at`/`deleted_by` (only live rows are exported). The other virtual fields are included, e.g. `evidence_count`, the `*_in_paper_scope` flags and evidence `subject_current_id` (the survivor of a merged subject) and `case_id`. `csv/evidence.csv` adds a last column `licence`: the cited document's `license` code, the licence under which the quote was published (empty for URL citations and documents without one).
- **`csv/document_link.csv`:** `document_id`, `subject_id`, `subject_type`, `subject_label`, `origin`, `state`, `match_count`, `matched_aliases` (`"; "`), every state, sorted by `document_id`, `subject_id`. Only confirmed links count in analyses (DATA_MODEL §15.8); the column `state` tells them apart.
- **`csv/field_provenance.csv`:** per exported record and `field_meta` entry: `entity_type`, `entity_id`, `field`, `src_kind` (`seed` · `collector` · `manual` · `import`, from `src`; `manual:<name>` entries count as `manual`), `src`, `licence` (the licence code that applies to the value: for the fields of a document, the document's `license`; for a collected value of another record, its collector's licence from `sources.csv`; empty otherwise, because values written by a person, the seed or an import record no source licence), `by`, `at`, `locked`, `verified`, `evidence_id`, `restored_from_version`, `raw_snapshot_ids` (`"; "`), `snapshot_refs` (compact JSON `[{id, url, final_url, fetched_at, via}]` of those snapshots: where and when a collected value was read; never the body). Sorted by `entity_type`, `entity_id`, `field`.
- **`csv/provenance_summary.csv`:** `entity_type`, `field`, `src_kind` (plus `none` for records without an entry), `records`, `locked`, `verified`, `disputed`, sorted by those three keys.
- **`csv/merges.csv`:** one row per `merge_log` row: `merge_id`, `entity_type`, `survivor_id`, `merged_id`, `at`, `unmerged_at`, sorted by `at`, `merge_id`.
- **`csv/sources.csv`:** one row per collector in `sources.yaml` plus `manual`, `seed` and `import` (with empty licence columns): `source_key`, `label`, `register_id` (the SOURCES ID, e.g. `S3`), `licence` and `licence_statement` (verbatim), sorted by `source_key`.
- **`csv/source_observation.csv`:** one row per observation (DATA_MODEL §14.5): `collector`, `key`, `entity_type`, `subject_id`, `subject_label`, `external_id`, `url`, `label`, `first_seen_at`, `last_seen_at`, `present`, `missing_since_at`, `missing_runs`, `details` (compact JSON), sorted by `collector`, `key`. The README says that these are crawl times, never dates of an initiative.
- **`dataset.json`:** `{"format": "mdt-dataset", "format_version": 1, "parameters", "data_revision", "data_as_of", "entities": {"<type>": [Record, …]}, "codebook": {"vocabularies": [{name, label, description, multi, fixed_codes, terms: [...]}]}}`, where Record is the **list** item of §2 (no `fields.text`, no `*_by_field` counts, no `observations`, no `search_snippet`) without `refs` and the counts `open_comments`, `comment_count` and `open_proposals`; documents keep their `links` with origin, state and match details, and every record its `field_meta` and, where present, `derived`. It holds no export ID or time (those are in `manifest.json`), so it is byte-identical for an unchanged data state (DATA_MODEL §23.5). Written as a stream.
- **`dataset.xlsx`:** a first sheet `README` (the README's lines), one sheet per type with the CSV columns, and the sheets `document_link`, `provenance_summary`, `merges`, `sources` and `codebook`, with the cell rules of §5; `field_provenance` and `source_observation` are in the CSV files only (their row counts can exceed what spreadsheets handle well).
- **`codebook/`:** the two files of §8.8.4, the loaded `codebook/parameters.yaml`, and `CODEBOOK.md`, the coding rules and codebook draft (`docs/CODEBOOK.md`, verbatim; where the exporter finds it: §8.10). Its vocabulary tables are the draft; the vocabularies used for the data are `codebook.md` and `codebook.csv`, which the README says.
- **`manifest.json`:**

  ```json
  {
    "format": "mdt-dataset", "format_version": 1, "export_id": "exp_…", "created_at": "…",
    "app_version": "…", "code_version": "…", "schema_revision": "0003",
    "parameters": {"ministry_founded": "2019-08-29", "full_scale_invasion": "2022-02-24"},
    "data_revision": 4812, "data_as_of": "…", "derived_inputs_hash": "…",
    "counts": {"project": {"total": 20, "verification_status": {"unverified": 18, "verified": 2, "disputed": 0}}, "evidence": {"total": 210, "anchored": 160, "target": {"entity": 40, "field": 70, "dimension": 100}}, "document_link": {"total": 900, "state": {"suggested": 600, "confirmed": 250, "rejected": 50}}},
    "files": [{"path": "csv/project.csv", "bytes": 48211, "sha256": "…", "rows": 20}],
    "references_outside_bundle": {"event.subject_id": 0},
    "collector_runs": [{"id": "run_…", "collector": "ministry_projects", "status": "succeeded", "started_at": "…", "finished_at": "…", "code_version": "…"}],
    "imports": [{"id": "imp_…", "file_label": "…", "created_at": "…"}],
    "excluded": ["deleted and merged records", "comments", "proposals", "raw snapshots", "run, fetch and import logs", "saved views", "document full texts"],
    "privacy_check": {"contact_email": "passed", "user_agent_token": "passed", "bot_manager_token": "passed"}
  }
  ```

  `files` lists every file except `manifest.json` and `SHA256SUMS` (`rows` for tabular files, the number of records for `dataset.json`, null otherwise); `collector_runs` and `imports` are those named in the exported `field_meta.src` values (`collector:<name>@<run_id>`, `import:<file_label>`); `privacy_check` gives `passed` or, for the address when `CONTACT_EMAIL` is unset or blank, `not_checked` (DATA_MODEL §23.3).
- **`README.md`** (generated, English): the export ID, time, code version, schema revision and data revision; the file list with one line per file; the conventions (encoding, list separator, partial dates and their four columns, the `derived_` prefix and the derivation rules in `codebook/CODEBOOK.md` §2.7, provenance kinds, offsets of evidence quotes, crosstab counting: a multi-valued field counts a record once per value, so every dashboard number can be recomputed from the CSV files); the content policy (exclusions; quotes and the `licence` column of `csv/evidence.csv`; the `license` column of documents and the `licence` column of field provenance; outside documents, values written by a person, the seed or an import carry no licence but can contain source text); **attribution**: values whose `licence` is `cc_by_4_0` (field provenance, quotes) are to be credited when reused, and the README lists the sources they come from (collectors and the documents' `source_id`) with the licence statements of `sources.csv`; verification (`sha256sum -c SHA256SUMS`); and a citation line ("MDT Portfolio dataset, export <id>, data revision <n>, <date>"; Phase 4 releases add the release name and git tag).

#### 8.8.3 QDA corpus

```
mdt-qda-<YYYYMMDD-HHMMSS>.zip
  README.md  manifest.json  SHA256SUMS
  metadata.csv              one row per included document (document variables)
  cases.csv                 one row per project and service (case variables)
  links.csv                 confirmed links between documents and cases
  codings.csv               the evidence rows that cite these documents (coded passages)
  texts/<document name>.txt one UTF-8 text file per document with a text (current version)
  texts/<document name>.<text_hash[:12]>.txt   earlier text versions that a coding quotes
  codebook/                 the four files of the dataset bundle's codebook/ folder
```

- **Documents:** live documents with `screening_status = included`, with the texts of every licence (an internal working corpus, DATA_MODEL §23.2). Sorted by document name. There are no parameters.
- **Document name:** `<published_start>_<document id>`, or `undated_<document id>` (e.g. `2022-03-01_doc_01JC…`): ASCII, unique, sortable by date. Titles are metadata, not file names.
- **Text files:** the current text version exactly as stored (`document_text.text`), and every earlier version that one of the document's codings quotes, UTF-8 **with a byte order mark** (QDA programs on Windows detect UTF-8 by it), LF line ends. Offsets in `codings.csv` count code points from the first character after the BOM; `text_hash` is the SHA-256 of a file's content without the BOM. A document without text has no file.
- **`metadata.csv`:** `document_name`, `document_group` (the slug of the first confirmed linked project in slug order, else empty), `document_id`, `title`, `title_en`, `doc_type`, `doc_type_label`, `language`, `published`, `published_start`, `published_end`, `published_precision`, `published_basis`, `published_text`, `derived_period`, `derived_period_label`, `publisher`, `url`, `archive_urls`, `retrieved_at`, `license`, `source_id`, `text_hash`, `char_count`, `text_file` (empty without text), `linked_projects` (slugs, `"; "`), `linked_services` (labels), `linked_clusters` (codes), all three from confirmed links only, like `document_group` and `links.csv`, `linked_in_paper_scope`, `citation_count`, `dimension_citation_count`, `screening_note`, `verification_status`. The first two columns are a document's name and group, the shape QDA programs read as document variables (the exact import steps depend on the program, README).
- **`cases.csv`:** one row per live project and service: `case_id`, `case_type`, `case_label`, `slug` (projects), `project_id` and `project_slug` (a service's project), `project_paper_cluster` and `project_in_paper_scope` (the project's values: a project's own, a service's project's; services have no such fields, so the names say whose values they are), `status`, `development_mode`, `wartime_relevance`, `derived_period`, `derived_entry_period`, `derived_war_trajectory`, with `_label` columns for the codes; sorted by `case_id`. The case variables of QDA programs (classifications, case attributes). `existed_before_invasion` is left out: its `false` means "not shown", which a case variable would read as "did not exist" (DATA_MODEL §3.1); the period and the trajectory with their reasons carry that information, and the dataset bundle exports the field with its definition.
- **`links.csv`:** `document_name`, `document_id`, `subject_id`, `subject_type`, `subject_label`, `project_slug`, `paper_cluster`, one row per confirmed link (document sets per project or cluster; links between documents and cases).
- **`codings.csv`:** one row per live evidence row that cites an exported document: `evidence_id`, `document_name`, `document_id`, `document_published` (with `_start`, `_end`, `_precision`), `derived_document_period`, `text_hash`, `text_version` (`current` · `earlier`), `text_file`, `char_start`, `char_end` (code points in that text version and its file), `quote`, `subject_id`, `subject_type`, `subject_label`, `subject_current_id`, `case_id`, `case_type`, `case_label`, `derived_case_period`, `target`, `target_kind` (`entity` · `field` · `dimension`), `field`, `dimension` and `dimension_label` (the code `d1`…`d4` and its label, empty for other targets), `codes` and `codes_label` (`"; "`), `locator`, `description`, `licence` (the document's `license`), `verification_status`, `created_at`, with the column conventions of the dataset bundle; whole-document evidence has empty offsets. Sorted by document name, `char_start`, `char_end`, `evidence_id`.
- **`manifest.json`:** as for the dataset with `"format": "mdt-qda"`, plus `"internal": true`, `"documents": {"included": n, "texts": n, "earlier_versions": n, "without_text": n}`, `"licences": {"<code>": n}` and `"codings_outside_corpus": {"<screening status>": n}` (codings of documents that are not included).
- **`README.md`:** the purpose; the notice "Internal working corpus: contains full texts of sources that are not openly licensed (column `license`); do not publish or share it"; the text and offset conventions (BOM, code points, `text_hash`); how the files map to a QDA program in general (texts as documents, `metadata.csv` as document variables, `cases.csv` as case variables, `links.csv` as document sets or document–case links, `codebook/` as the code system); that links and the `linked_*` columns count confirmed links only and that the `project_*` columns of `cases.csv` hold the project's values; and that `codings.csv` is meant for analysis tools, because no exchange format for codings (REFI-QDA) is produced.

#### 8.8.4 Codebook

Generated from the database's working copy (the terms as edited on the Codebook page), never from the YAML files, except `parameters.yaml`.
- **`codebook.md`:** a title with "working copy, data revision <n> (<data_as_of>)" (no export time, so the same data state gives the same file); the parameters (code, value, source); one section per vocabulary in name order (`## <label> (`<name>`)`, its description, `multi` and `fixed_codes`, and a table of its terms by `sort_order`: code, English label, Ukrainian label, definition, include note, exclude note, examples, status (`active`, or `inactive → <replaced_by>`), attributes as compact JSON); for each analysis code up to three **anchor examples** from its live coded passages (the quote, at most 300 characters, with the document ID, publication date and `license` code; oldest evidence first); a closing pointer to the coding rules (`CODEBOOK.md`, which the bundles include).
- **`codebook.csv`:** one row per term: `vocabulary`, `vocabulary_label`, `multi`, `fixed_codes`, `code`, `label_en`, `label_uk`, `definition`, `include_note`, `exclude_note`, `examples`, `sort_order`, `active`, `replaced_by`, `attributes` (compact JSON, sorted keys), `usage_count`, `version`; sorted by vocabulary and `sort_order`, then code; the CSV rules of §5.

### 8.9 Indicator metrics

`GET /api/indicators/metrics?q=` → `{"metrics": [{"metric": "…", "count": n, "units": [{"unit": "…", "count": n}]}]}` over live indicators, by count (descending), then metric (`mdt_sortkey`); `q` filters by a case-folded substring of the metric. The indicator forms offer these values (`docs/UI.md` §9.3); nothing is suggested from outside the data.

### 8.10 Runtime and settings

- **Exports** are built inside the request (DATA_MODEL §23.4); temporary files live in `DATA_DIR/exports/.tmp/` (in the `./data` bind mount) and are removed after each build (a file left behind by a crash by a later build, once it is older than a day). Phase 3 adds no setting.
- **`CODEBOOK.md`:** the exporter reads `docs/CODEBOOK.md` below the repository root, the root that relative settings resolve against (`REPO_ROOT`; `/app` in the image), so development, tests and Docker find the same file whatever `CODEBOOK_DIR` is; a missing file fails the export with `error: docs/CODEBOOK.md not found` (API `500`, logged). The image contains it as `/app/docs/CODEBOOK.md` (the `.dockerignore` allowlist adds `!docs/CODEBOOK.md`, and the Dockerfile copies it; `tests/test_docker_layout.py` checks it).
- **CLI** (CLAUDE.md, "Commands"): `mdt export dataset [--out DIR]` and `mdt export qda [--out DIR]` build the bundle in the foreground and write it into `DIR` (default `DATA_DIR/exports/`), printing the path, the export ID and the SHA-256 of the ZIP; `mdt export codebook [--format md|csv] [--out FILE]` writes the codebook (default standard output). Each exits 0, or 1 with `error: …` on failure (a privacy-guard hit, derived values out of date). Makefile: `make export KIND=dataset|qda|codebook`.
- **Startup self-check** (§6): the database must be at head `0003`.
- **Guides** (`backend/tests/test_docs.py`): README.md names the new commands (`export dataset`, `export qda`, `export codebook`) with their options and the `make export` target.
