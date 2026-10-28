# Frontend (UI)

> **Status:** v1 contract for Phase 1, revised 2026-10-28 after a five-lens contract review.
> **Stack:** React + TypeScript (strict) + Vite (base `/`), Mantine, TanStack Router, Query and Table, jsdiff, DOMPurify, dayjs, @tabler/icons-react.
> **Character:** English UI, sober, information-dense and readable; it is a research tool.
> **Related:** `docs/API.md` (all data comes from there), `PLAN.md` §7 (wireframes).

## 1. Principles

### 1.1 Driven by metadata

- Tables, filters, forms and detail pages are generated from `GET /api/meta` (field specs incl. `default`, `in_create`, `constraints`; groups; quick filters; default sorts; limits).
- There are no hard-coded field lists, except for layout preferences such as the order of groups.

### 1.2 URL holds the state

The table's query string *is* the API query string (`f.*`, `q`, `sort`, `page`, `page_size`, `deleted`, `cols`). TanStack Router is configured with exactly:

```ts
parseSearch: (s) => Object.fromEntries(new URLSearchParams(s)),
stringifySearch: (o) => {
  const p = new URLSearchParams(Object.entries(o).filter(([, v]) => v != null && v !== '').map(([k, v]) => [k, String(v)]));
  p.sort();
  const s = p.toString();
  return s ? '?' + s : '';
},
```

- `validateSearch` passes every string key through unchanged; no schema strips the dynamic `f.*` keys.
- **Saved views** store the canonical (sorted) query string without `?`, and are applied by navigating with `Object.fromEntries(new URLSearchParams(view.query))`.
- **Detail-page state** in the URL: the history tab's compare selection (`from`, `to`) and the comment thread (`thread`).
- **Query keys:**
  - the list key uses the canonical string without `cols` and without detail-page parameters;
  - facet keys also omit `f.<field>`, `page`, `page_size` and `sort`.

### 1.3 No silent overwrite: 409 handling per action

Every write sends `expected_version`. Nothing is retried blindly.

| Action | On 409 |
|---|---|
| Edit form (PATCH, `action = patch`, live row) | Conflict dialog (§4.1). |
| verify-field | Refetch. If the field value is unchanged between base and current, retry once with `current_version`. Otherwise ask "Value changed from A to B by X — verify B?". |
| delete, undelete, restore, codebook modal | Show the confirmation again, listing the intervening revisions (author, time, note); resend with `current_version` only on confirm. |
| comment edit | Two-way dialog (theirs vs yours, word diff); resend only on confirm. |
| comment resolve/reopen | Idempotent on the server; a 409 only arises for real changes and is shown like delete. |
| bulk | Per-row results (§3). |
| `entity_deleted`, `invalid_state` | Notice "Changed by <updated_by> at <updated_at>" with **Reload**. |

### 1.4 Safe rendering

- **Values as text:** document texts and all field values are rendered as text. Data strings in inline contexts (names, authors, labels in feeds) are wrapped in `<bdi>`, so bidi characters cannot reorder adjacent text.
- **Links:** exactly one `ExternalLink` component builds links from data. It renders `<a href target="_blank" rel="noopener noreferrer nofollow">` only if `new URL(value)` succeeds with protocol `http:` or `https:`, and it shows `URL.host` (punycode) next to the text. Otherwise it renders plain text. No other component builds an `href` from data.
- **Injected HTML:** the only HTML injected is the server-sanitised comment `body_html`, passed through DOMPurify again with the same tag and attribute allowlist as the server and `ALLOWED_URI_REGEXP = /^(?:https?:|mailto:|\/(?!\/))/i`.
  - ESLint `react/no-danger` is an error, with one inline exception in `CommentBody`.
  - jsdiff output and search snippets (segments) are rendered as React elements.
- **No inline scripts:** `index.html` has none; the colour scheme is fixed to light (no `ColorSchemeScript`, no `@vitejs/plugin-legacy`).

### 1.5 Attribution, not authentication

- **Author modal:** on first visit it asks for a name: a quick pick from `meta.team_members` or free text, with recently used names remembered.
  - The same validation as the server applies: NFC, trim, collapse whitespace; no control, format, bidi or zero-width characters, no comma; reserved names refused (DATA_MODEL §7).
  - `encodeURIComponent` errors (lone surrogates) are caught.
- **Storage and sending:** the name is stored in `localStorage["mdt.author"]` and sent on every write as `X-Author: encodeURIComponent(name)`.
- **Write buttons** stay disabled until a name is set.
- **Header:** shows the name; clicking it changes the name.

### 1.6 API client and development

- The fetch wrapper sends `X-Requested-With: mdt` on every request and `Content-Type: application/json` on writes.
- **Exports** are downloaded with `fetch` → Blob → object URL → `a[download]`, with the file name taken from `Content-Disposition`. No plain link points at `/api`.
- **Development:** the Vite dev server proxies `/api` to `http://127.0.0.1:8000` with `changeOrigin: false`, so the backend's same-origin check passes.

## 2. Routes

| Route | Page |
|---|---|
| `/` | **Overview:** counts per entity type from `/api/stats` (total, unverified), open comments, links. The dashboard proper comes in Phase 3. |
| `/projects`, `/services`, `/events`, `/documents`, `/organizations` | `EntityTablePage` |
| `/projects/$id` (likewise for the other four) | `EntityDetailPage`; search params `tab=details\|history`, `from`, `to`, `comments=open`, `thread=<id>`, `edit=1` |
| `/changes` | `RecentChangesPage` |
| `/comments` | `CommentsPage` |
| `/trash` | `TrashPage` (`type=` tab param) |
| `/codebook` | `CodebookPage` (`vocabulary=`, `term=`, `comments=`, `thread=` params) |

Review inbox, collector runs, timeline, dashboard and releases come in later phases. They are **not** shown in the navigation before then.

**Header:**
- app name "MDT Portfolio";
- navigation (Overview, Projects, Services, Events, Documents, Organizations, Changes, Comments, Codebook, Trash);
- global search box: `GET /api/lookup?types=project,service,event,document,organization&q=…`, grouped by type, with "show all" links to `/<type>s?q=…&sort=relevance`;
- author menu.

## 3. EntityTablePage

**Toolbar:**
- title with total count;
- search input (`q`, debounced 300 ms; with `q` set, a "relevance" sort option appears);
- **quick filters** from `meta.quick_filters`:
  - `toggle` → a chip that is active only if the URL contains exactly its key/value pair; activating it replaces any filter on that field; deactivating it removes the parameter;
  - `chips` (period) → a segmented multi-select over the period codes, writing `f.period=in:…`;
  - `preset` (events, documents) → mutually exclusive date presets;
- **Saved views** menu:
  - list via `GET /api/entities/saved_view?f.entity_type=eq:<type>`, applied by navigation (§1.2);
  - "Save current view…" with name and description;
  - delete with confirmation (soft delete);
- **Columns** menu (checkboxes over the type's fields, system columns included; stored in `cols`; default = `in_list` fields);
- **Export** menu: "CSV (for analysis tools)" and "XLSX (for Excel, exact values)", downloaded per §1.6;
- **"+ New"** opens a create modal with the `in_create` fields and their defaults:
  - the "one of" constraints are shown;
  - a project needs a `scope_note`;
  - services and events can be created with a pre-filled parent or subject;
- link to the trash.

**Table:**
- TanStack Table in manual mode: sorting, pagination and filtering are server-side. Sticky header, compact rows (`size="xs"`), row click opens the detail page, middle-click or ctrl-click opens a new tab.
- **Header cell:**
  - label with help tooltip;
  - sort indicator for sortable fields: click cycles asc → desc → none; shift-click adds a secondary sort (max 3);
  - filter button with an active-state dot.
- **Filter popover by filter kind:**
  - `text`: operator (contains, equals, empty or not empty) and input;
  - `multiselect`: checkbox list of values with counts from `/facets` (loaded when opened) plus "(empty)", which writes the `~empty` token; operators in / not in for single values, any / all / none for list fields;
  - `date_range`: from and to (`YYYY-MM-DD`), mode overlaps or within; "empty" is exclusive and disables from/to;
  - `bool`: segmented yes, no, any;
  - `number_range`: min and max;
  - `ref`: multi-select backed by `GET /api/lookup` (labels of IDs from a shared URL via `/api/lookup?ids=…`).
- **Cells by type:**
  - `vocab`: label as a small badge (code in tooltip);
  - `vocab_list`: badges, at most 3 plus "+n" (the first is the main value);
  - `ref`: link with label, struck through if deleted;
  - `partial_date`: canonical string plus precision hint (`2020-06 · month`);
  - derived values: italic with a "derived" tooltip showing basis, reason and the deciding event; `existed_by` shown as `≤ 2021-05-14`;
  - `bool`: check icon;
  - `url_list`: count plus the first host;
  - `verification_status`: coloured dot (grey unverified, green verified, red disputed);
  - `open_comments`: speech-bubble icon with count;
  - documents with `q`: the `search_snippet` segments under the title, hits as `<mark>`.
- **Selection:** checkbox column and select-all on the page.
- **Bulk edit:**
  - **modal:** a field from the `bulk_editable` fields; operation set / add / remove for lists; value; note. A scope change asks for a `scope_note`; setting verified or disputed asks for a note;
  - **versions:** the `expected_version` of each row is captured when the modal opens;
  - **summary** per status (updated, unchanged, conflict, deleted, error): conflicted rows are listed with their current values, with "Retry with current versions" for those rows after review;
  - **Mark verified:** a bulk set of `verification_status`, note required.
- **Footer:** pagination (page numbers, first and last), page size 25 / 50 / 100 / 200, total.
- **Empty states** explain the active filters (labels via lookup) and offer "Clear filters".

## 4. EntityDetailPage

**Header:**
- breadcrumb (type → label);
- badges: `verification_status`, project cluster, `in_paper_scope`, "deleted", version `vN`;
- actions:
  - **Edit**;
  - **Delete** (confirm with note; on `409 has_dependents`, ask about cascade);
  - **Undelete** (offers cascade when the deletion was a cascade);
  - **Copy link**.
- A deleted entity is shown read-only (Edit and verification disabled) with a banner and an Undelete button.

**Tabs:**

### 4.1 Details

Field groups in the order `meta.groups` (Basics · Classification · Wartime · Framework D1–D4 · Sources & Evidence; System collapsed: created/updated/deleted by and at, version).

**Field row:**
- label with help tooltip;
- value;
- **provenance badge** (`seed` / `manual` / `import` / `collector`; tooltip shows `src`, `by`, `at` and, if present, `restored_from_version`);
- **lock icon** if `locked`;
- **verification dot**, with a menu:
  - **Verified:** choose one of the field's evidence rows (`GET /api/entities/evidence?f.subject_id=in:<id>&f.target=eq:field:<name>`), or "Add evidence…" first;
  - **Disputed:** note required; afterwards the comment composer opens, pre-set to that field;
  - **Unverified.**
  The choice is sent as `POST verify-field`.
- **"Add evidence…"** opens a small form that posts to `/api/entities/evidence`: URL, retrieved at (default now), verbatim quote, locator, note. It sets `subject_id` and `target = field:<name>`.
- **comment-on-field** icon with the open field-comment count from `virtual.open_comments_by_field`.

**Derived values** appear in the Wartime group with an explanation: basis, reason code in words, and links to the deciding event or participation (labels from `refs`).

**Edit mode** (`edit=1`):
- **Frozen base:** entering edit mode stores `base = {fields: structuredClone(item.fields), version: item.version}` in component state, outside the query cache.
  - The PATCH sends only the form values that differ from `base.fields`, with `expected_version = base.version`.
  - Background refetches and invalidations never change `base` or the form values.
  - If a refetch shows a newer version, a banner says "Changed by <updated_by> at <updated_at>; saving will open the conflict dialog".
- **Inline form** for all editable fields:

| Field type | Input |
|---|---|
| `string` | TextInput |
| `text` | autosize Textarea |
| `slug` | TextInput with pattern hint |
| `url` | TextInput with the URL rules of DATA_MODEL §1.2 |
| `vocab` | searchable Select (label + code; inactive codes hidden unless current) |
| `vocab_list` | MultiSelect that keeps the order; the first value is marked "main" |
| `bool` | Switch |
| `int` | NumberInput (integers) |
| `number` | NumberInput |
| `url_list`, `string_list` | TagsInput or one item per line |
| `alias_list` | small table editor: text, language, case-sensitive, kind, exclude phrases |
| `partial_date` | TextInput with live validation and the hint "YYYY · YYYY-Qn · YYYY-MM · YYYY-MM-DD" |
| `ref` | lookup select (`/api/lookup`); the parent-service picker passes `f.project_id=in:<project>` and excludes the service itself and its descendants |
| `datetime` (editable ones, e.g. `retrieved_at`) | date-time input in UTC |
| `doc_links`, `json`, system fields | read-only in Phase 1 |

- **Sticky save bar:**
  - optional change note, required where a rule demands it: changing `in_paper_scope` asks for a new `scope_note`; setting `verification_status` to verified or disputed asks for a note;
  - Save / Cancel;
  - unsaved changes trigger a prompt when leaving the page.

**Conflict dialog** (on `409 conflict` with `action = patch` on a live row):
- **Header:** lists the `intervening` revisions (author, time, note, changed fields).
- **Fields table:**
  - **conflicting fields:** columns *Base*, *Theirs (current)*, *Yours*, with a mandatory choice per field: keep theirs, apply yours, or, for text fields, "Edit merged value" (prefilled with yours, a jsdiff of theirs vs yours shown);
  - **fields only you changed:** "will be applied";
  - **fields only they changed:** information;
  - fields whose verification would be reset (`meta_changed_since_base`) are flagged;
  - ref values show labels from `refs`.
- **Actions:**
  - **Apply:** set base := current fields and version := `current_version`, then re-PATCH with the chosen values; a further conflict shows the dialog again;
  - **Discard my changes:** reload.
- Nothing is saved without a choice.

**Error displays:**
- `reference_deleted` offers to open (and undelete) the referenced row;
- `unique_violation` highlights the field and links to the existing record.

**Related panels:**

| Type | Panels |
|---|---|
| project | Services (name, kind, channels, status, launch; "+ Add service"), Events (sorted by date: type, date, basis, description; "+ Add event"), linked Documents, Participations, Relations (`f.endpoint=in:<id>`), Indicators, Evidence (read-only lists with empty states, e.g. "Documents arrive with the collectors in Phase 2") |
| service | project, parent service and child services, Events, linked Documents (`f.links=in:<id>`), Participations, Relations, Indicators, Evidence |
| event | subject, Evidence |
| document | metadata, extracted text as plain text, links (subjects with origin and state), Evidence that cites it |
| organization | Participations |

### 4.2 History

**Revision list:** version, time, author, channel and action badges, note, changed-field chips.

**Diff view:**
- selecting a revision shows its stored diff;
- "Compare" mode picks any two versions (`/diff?from=&to=`; the selection is kept in the URL);
- old → new per field; long texts get word-level diffs (jsdiff); `meta` and `state` changes are shown separately; fields that are not recorded in an older snapshot are marked; refs show labels.

**Restore this version:**
- The modal first calls `restore` with `dry_run: true` and shows the resulting changes, one per field with a checkbox (default all), plus the authors of the revisions that would be undone. It requires a note.
- Confirming sends the selected `fields` with `expected_version` = the current version.
- The button is disabled for the current version and for deleted entities ("Undelete first").
- Afterwards: refetch, plus a notice with the new version, any `warnings` and `skipped_fields`.

### 4.3 Comments panel

A collapsible right-hand panel that can be opened via URL `comments=open`.

**Filters:** open, resolved or all; field (incl. "entity-level only"); "show deleted". A `thread=<id>` link switches the status filter to "all" and scrolls to the thread.

**Thread display:** root comment with field chip, status and author/time, replies below.

**Actions:**
- reply (not on deleted roots);
- edit; the "edited" label opens the comment's revision list with word diffs and "Restore this version";
- resolve or reopen (root);
- delete; undelete (with "show deleted").

**Composer:** Markdown textarea (maximum from `meta.limits`) with an optional field selector. There is no client-side Markdown preview; the server returns `body_html`.

## 5. Other pages

- **RecentChangesPage:**
  - filters: author (multi, from `/api/revisions/authors`), entity type (incl. comment, vocabulary term, saved view), channel, action, date range (local days, sent as timestamps), batch;
  - rows grouped by local day: time, author, channel and action badges, entity link (type + label), version, changed fields, note;
  - link targets: comments link to their subject with `comments=open&thread=<id>`, vocabulary terms to the Codebook page, saved views to their table with the view applied;
  - expanding a row loads `GET /api/revisions/{revision_id}` and shows its diff.
- **CommentsPage:**
  - filters: status, entity type, author, text, deleted;
  - one row per thread: subject link, field, last activity, number of replies;
  - clicking opens the subject page with `comments=open&thread=<id>` (vocabulary terms open the Codebook page).
- **TrashPage:**
  - tabs for every soft-deletable type: the five table types, participation, component, relation, indicator, evidence, saved view, and comments (vocabulary terms are deactivated, not deleted);
  - sorted by `-deleted_at`; deleted items with label, `deleted_at`, `deleted_by` and "deleted together with n others" for cascades;
  - **Undelete** with a note (cascade where applicable).
- **CodebookPage:**
  - vocabulary list (label, number of terms, "fixed" badge);
  - terms table: code, labels, definition, active, `usage_count`, sort order, attributes such as `candidate`, open comments;
  - **Edit** (modal, generic PATCH of `vocabulary_term`; code and vocabulary read-only). For `event_type` it shows a switch for `attributes.counts_as_modification`, with a warning that derived values will be recomputed;
  - **Add term** and **Deactivate**, both disabled for fixed vocabularies and fixed codes;
  - **History** (revision list and diff);
  - **comments panel** per term (`term=`, `comments=open`, `thread=`).

## 6. Code structure

```
frontend/src/
  main.tsx  router.tsx  theme.ts
  api/        client.ts (fetch wrapper, ApiError, ConflictError), types.ts, queries.ts (TanStack Query hooks + keys), lookup.ts
  lib/        query-string.ts (filter grammar helpers incl. ~empty), partial-date.ts, format.ts, diff.ts, author.ts, urls.ts (ExternalLink rules), download.ts
  components/ layout/, table/, fields/ (display + input per type), detail/, history/, comments/, conflict/, evidence/, ExternalLink.tsx
  pages/      Overview, EntityTable, EntityDetail, RecentChanges, Comments, Trash, Codebook
```

**Query keys:** `['meta']`, `['vocab']`, `['stats']`, `['list', type, canonicalQs]`, `['facets', type, field, facetQs]`, `['item', type, id]`, `['revisions', type, id]`, `['comments', subjectId]`, `['changes', qs]`, `['lookup', …]`.

**Invalidation after a write:**
- item, list of the type, revisions, stats, changes (and comments where relevant);
- after any write to an event: also the items of its old and new subject and the project and service lists (derived values changed);
- after a vocabulary-term write: `['vocab']`, `['meta']` and all lists;
- invalidation never touches an open edit form's frozen base.

## 7. Tests

- **Vitest:**
  - round-trip of filter grammar and URL (incl. Cyrillic values, commas in text values, `~empty`, chips, canonical sorting);
  - validation and formatting of partial dates;
  - the conflict-resolution payload (only-mine, only-theirs, conflicting, merged text, repeated conflict);
  - **a refetch during editing leaves the PATCH payload unchanged;**
  - diff helpers;
  - author validation and header encoding;
  - `ExternalLink` (javascript:, data:, `java\tscript:`, userinfo URLs render as text).
- **Playwright E2E:**
  - **setup:**
    - the backend serves the built frontend on a temporary database created with `mdt db upgrade` + `mdt seed`;
    - `@playwright/test` is pinned to the preinstalled Playwright version, and Chromium comes from `/opt/pw-browsers` when present;
    - every scenario fails on a `securitypolicyviolation` event or a CSP console error;
  - **scenarios:**
    - (a) the projects table shows 20 rows;
    - (b) filter by `paper_cluster` and sort by `name_en`, `name_uk` (exact expected order), `policy_domains` and `verification_status` (asc and desc); a `contains:дія` filter on `name_uk`; the URL updates and a reload keeps the state;
    - (c) edit a field with a note → history shows author and note;
    - (d) diff and restore with the dry-run preview;
    - (e) two browser contexts edit the same field → the second sees the conflict dialog with the intervening revision and resolves it;
    - (f) frozen base: B starts editing, A saves a different field, B posts a comment on the same page (which invalidates the item) and then saves → B sees the conflict dialog and A's value survives;
    - (g) comment thread create, reply, resolve, delete and undelete; the "open comments" quick filter;
    - (h) export CSV and XLSX of a filtered view.
