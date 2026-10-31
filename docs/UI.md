# Frontend (UI)

> **Status:** v1 contract for Phase 1, revised 2026-10-28 after a five-lens contract review, updated the same day with the decisions of the Phase 1 build and integration, and simplified on 2026-10-29 for a single user (decision D-15, `PLAN.md` §12). **Extended on 2026-10-30 with the Phase 2 pages** (§8: review inbox, runs, sources, import, adding documents, merge and unmerge, and the additions to detail pages) and the marked additions in §2–§7; revised the same day after a four-lens review.
> **Stack:** React + TypeScript (strict) + Vite (base `/`), Mantine, TanStack Router, Query and Table, jsdiff, dayjs, @tabler/icons-react.
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
- **Saved views** store the canonical (sorted) query string without `?`, `page` and the detail-page parameters (a view never pins a page number), and are applied by navigating with `Object.fromEntries(new URLSearchParams(view.query))`. The default view (an empty query) cannot be saved: a saved view's `query` is required (DATA_MODEL §3.5), and the default is always available anyway.
- **Detail-page state** in the URL: the history tab's compare selection (`from`, `to`) and the comment thread (`thread`).
- **Query keys:**
  - the list key uses the canonical string without `cols` and without detail-page parameters;
  - facet keys also omit `f.<field>`, `page`, `page_size` and `sort`.

### 1.3 Writes and errors

- Writes send no version (D-15): the app has one user. The edit form sends only the fields the user changed (§4.1).
- Nothing is retried automatically (mutations never retry), so a create is never stored twice.
- Errors are shown where they arise: validation errors at their field (by the last segment of the error path) or as a general form error, `unique_violation` and `reference_deleted` with links (§4.1), `has_dependents` in the delete dialog (§4); other errors (e.g. `entity_deleted`, `invalid_state`) as a plain error message.
- Leaving the edit form with unsaved changes asks "Discard unsaved changes?".

### 1.4 Rendering

- **Values as text:** document texts and all field values are rendered as text, never as HTML. Data strings in inline contexts (names, labels in feeds) are wrapped in `<bdi>`, so text in another writing direction does not reorder adjacent text.
- **Links:** the `ExternalLink` component turns stored URLs (validated as `http`/`https` by the server, DATA_MODEL §1.2) into `<a href target="_blank" rel="noopener noreferrer">` and shows `URL.host` (punycode) next to the text.
- **Comment HTML:** `CommentBody` renders the server's `body_html` as it is (API §3.3). jsdiff output and search snippets (segments) are rendered as React elements.
- **Colour scheme:** fixed to light (no `ColorSchemeScript`).

### 1.5 One user, no names

- The app has one user and no login (D-15). It never asks for a name and sends none; the server records every write by the fixed actor `user` (API §1.3).
- Wherever a person's name would always be the same, the UI shows the channel instead: changes made in the app (channel `ui`, provenance `src = manual`) are labelled **manual**; the other channels keep their codes (restore, seed, import, collector, merge, system). Comments show times only ("Resolved at …", "Deleted at …").
- The system fields `created_by`, `updated_by` and `deleted_by` stay ordinary registry fields (System group, table columns); for records written in the app they read `user`.

### 1.6 API client and development

- The fetch wrapper sends `Accept: application/json` and, on writes, a JSON body with `Content-Type: application/json`; there are no custom headers.
- **Exports** are downloaded with `fetch` → Blob → object URL → `a[download]`, with the file name taken from `Content-Disposition`, so a refused export shows the server's error message.
- **Development:** the Vite dev server (and `vite preview`) proxies `/api` to `http://127.0.0.1:8000`.

## 2. Routes

| Route | Page |
|---|---|
| `/` | **Overview:** counts per entity type from `/api/stats` (total, unverified), open comments, links. The dashboard proper comes in Phase 3. |
| `/projects`, `/services`, `/events`, `/documents`, `/organizations` | `EntityTablePage` |
| `/projects/$id` (likewise for the other four) | `EntityDetailPage`; search params `tab=details\|history`, `from`, `to`, `comments=open`, `thread=<id>`, `edit=1` |
| `/records/$id` | `RecordPage`: the generic record page for records without a table (evidence, participation, component, relation, indicator, saved view; the type comes from the ID prefix). It is the `EntityDetailPage` with the same search params; IDs of table types and vocabulary terms are redirected to their own pages with the search params kept. Related lists, ref values, the change feed, the comment feed and the trash link these records here. |
| `/changes` | `RecentChangesPage` |
| `/comments` | `CommentsPage` |
| `/trash` | `TrashPage` (`type=` tab param: an entity type name or `comment`) |
| `/codebook` | `CodebookPage` (`vocabulary=`, `term=` (the term's ID, `voc_…`; `vocabulary=` is optional with it), `comments=`, `thread=` params) |

Phase 2 adds `/review`, `/runs`, `/runs/$id`, `/sources`, `/sources/$collector` and `/import` (§8.1). Timeline, dashboard and releases come in later phases and are **not** shown in the navigation before then.

**Header:**
- app name "MDT Portfolio";
- navigation (Overview, Projects, Services, Events, Documents, Organizations, Review (n), Changes, Comments, Runs, Sources, Import, Codebook, Trash; the Phase 2 items are described in §8.1);
- global search box: `GET /api/lookup?types=project,service,event,document,organization&q=…&limit=25` from two characters (debounced 250 ms), grouped by type, with "show all" links to `/<type>s?q=…&sort=relevance`.

## 3. EntityTablePage

**Toolbar:**
- title with total count;
- search input (`q`, debounced 300 ms; with `q` set, a "relevance" sort option appears);
- **quick filters** from `meta.quick_filters`:
  - `toggle` → a chip that is active only if the URL contains exactly its key/value pair; activating it replaces any filter on that field; deactivating it removes the parameter;
  - `chips` (period) → a chip group (multi-select) over the codes of the field's vocabulary, writing `f.period=in:…` with the codes in vocabulary order (no chip selected removes the parameter);
  - `preset` (events, documents) → one group of mutually exclusive date presets, from the quick filter's `presets` list (API §3.1); without such a list the UI builds the three `within` presets from `meta.parameters`;
- **Saved views** menu:
  - list via `GET /api/entities/saved_view?f.entity_type=eq:<type>&sort=name&page_size=500`, applied by navigation (§1.2); the view matching the current query is marked; the list scrolls inside the dropdown (at most `min(60vh, 420px)` high, `overscroll-behavior: contain`, so scrolling past its end does not scroll the page away from the dropdown), so every view stays reachable however many are saved;
  - "Save current view…" (below the list, always visible) opens a dialog with name, description and the query to be saved; for the default view its Save button is disabled, with an explanation;
  - delete with confirmation (soft delete);
- **Columns** menu (checkboxes over the type's `exportable` fields, i.e. those with a value per list row, system columns included; the detail-only document `text` is not offered; stored in `cols`; default = `in_list` fields; unknown or non-exportable names in a URL are ignored);
- **Export** menu: "CSV (for analysis tools)" and "XLSX (for Excel, exact values)", downloaded per §1.6; the request sends the page's filters, `q` and sort, and `cols` = `id` followed by the visible columns (never the raw URL `cols`), so every export of the current view identifies its rows and has the table's columns;
- **"+ New"** opens a create modal with the `in_create` fields and their defaults:
  - the "one of" constraints are shown;
  - a project needs a `scope_note`;
  - services and events can be created with a pre-filled parent or subject;
- link to the trash; when the URL shows deleted rows (`deleted=only|include`), a notice says so and offers to return to the live rows.

**Table:**
- TanStack Table in manual mode: sorting, pagination and filtering are server-side. Sticky header, compact rows (Mantine's `Table` has no `size` prop; the theme sets font size `sm` and vertical spacing 4), row click opens the detail page, middle-click or ctrl-click opens a new tab.
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
  - `ref`: condition "is any of" (multi-select backed by `GET /api/lookup`, labels of IDs from a shared URL via `/api/lookup?ids=…`, plus "(empty)", which writes `~empty`) or "has any value" (`empty:false`); a form opened on a filter and applied unchanged keeps it.
- **Cells by type:**
  - `vocab`: label as a small badge (code in tooltip);
  - `vocab_list`: badges, at most 3 plus "+n" (the first is the main value);
  - `ref`: link with label, struck through if deleted;
  - `partial_date`: canonical string plus precision hint (`2020-06 · month`);
  - derived values: italic with a "derived" tooltip showing basis, reason and the deciding event, and for `launch` the interval over all candidates whenever it differs from the displayed candidate (API §2: it decides the period, sorting, filters and exports); `existed_by` shown as `≤ 2021-05-14`;
  - `bool`: check icon;
  - `url_list`: count plus the first host;
  - `verification_status`: coloured dot (grey unverified, green verified, red disputed);
  - `open_comments`: speech-bubble icon with count;
  - documents with `q`: the `search_snippet` segments under the title, hits as `<mark>`.
- **Selection:** checkbox column and select-all on the page.
- **Bulk edit:**
  - **modal:** a field from the `bulk_editable` fields; operation set / add / remove for lists; value; note. A scope change asks for a `scope_note`; setting verified or disputed asks for a note. Set and add offer active codes only; remove also offers the inactive codes that the selected rows carry (marked "(inactive)"), so a deactivated code can be cleaned out of many rows at once (only adding inactive codes is refused, DATA_MODEL §7);
  - **request:** `ids` = the selected rows (API §3.2);
  - **summary** per status (updated, unchanged, deleted, error); deleted rows ("Deleted (not changed)", reachable when the table shows deleted rows) and refused rows ("Errors (not changed)", with the server's message) are listed with links;
  - **Mark verified:** a bulk set of `verification_status`, note required.
- **Footer:** pagination (page numbers, first and last), page size 25 / 50 / 100 / 200, total.
- **Empty states** keep the table header (with its sort buttons and filter popovers) above them, explain the active filters (labels via lookup) with a remove button per line (one filter, the search or the `deleted` mode), and offer "Clear filters", which removes every `f.*` filter, `q` and the `deleted` mode and drops a `relevance` sort (the server refuses it without `q`). A page past the end has its own empty state; an invalid filter or sort in the URL (`400 bad_filter`/`bad_sort`) offers "Reset filters and sort".

## 4. EntityDetailPage

The page of a table type's record and of the record-page types (`/records/$id`, §2). For the latter the breadcrumb shows the type without a table link, the related records are those listed below, and evidence rows have no field verification of their own (evidence cannot be the subject of evidence).

**Header:**
- breadcrumb (type → label);
- badges: `verification_status`, project cluster, `in_paper_scope`, "deleted", version `vN`;
- actions:
  - **Edit**;
  - **Delete** (confirm with note; on `409 has_dependents`, ask about cascade; for evidence that a field verification rests on (`{"field_verification": 1}`) explain instead that the field has to be marked unverified or disputed, or verified with other evidence, first, linking the subject, and offer no cascade);
  - **Undelete** (the shared undelete dialog of the trash, §5: it offers the cascade when the delete revision's batch contains other rows, counted with `GET /api/revisions?batch_id=…&page_size=1`, and preselects it then);
  - **Copy link** (the page's address: `/projects/<id>` etc., `/records/<id>` for the record-page types). It uses the Clipboard API in a secure context; over plain http on a LAN or VPN address, where browsers offer no Clipboard API, it copies through a selected hidden field (`execCommand('copy')`); if the browser refuses both, a dialog shows the link selected for manual copying, so the action never fails silently;
  - **Comments** toggle with the number of open threads (opens the comments panel, §4.3).
- A deleted entity is shown read-only (Edit and verification disabled) with a banner and an Undelete button.

**Tabs:**

### 4.1 Details

Field groups in the order `meta.groups` (Basics · Classification · Wartime · Framework D1–D4 · Sources & Evidence; System collapsed: created/updated/deleted by and at, version). Layout preferences: the virtual counters `open_comments` and `comment_count` are not shown as rows (the comments toggle and the field buttons show them); a document's `text` has its own "Extracted text" panel; System rows have no comment-on-field button, and the composer's field selector leaves out the System group.

**Field row:**
- label with help tooltip;
- value;
- **provenance badge** (`seed` / `manual` / `import` / `collector`; tooltip shows `src`, `at` and, if present, `restored_from_version`);
- **lock icon** if `locked`;
- **verification dot**, with a menu:
  - **Verified:** choose one of the field's evidence rows (`GET /api/entities/evidence?f.subject_id=in:<id>&f.target=eq:field:<name>`), or "Add evidence…" first;
  - **Disputed:** note required; the dialog shows the disputed value; afterwards the comment composer opens, pre-set to that field;
  - **Unverified.**
  The choice is sent as `POST verify-field`.
- **"Add evidence…"** opens a small form that posts to `/api/entities/evidence`: URL, retrieved at (default now), verbatim quote, locator, note (the evidence row's `description`); the inputs come from `meta.entity_types.evidence`. URL, retrieval time and the quote are required, because a verified field needs evidence that quotes the source (CODEBOOK §2.3, DATA_MODEL §6.4). It sets `subject_id` and `target = field:<name>`, and shows the value the evidence is for. Its button "Add evidence and mark verified" creates the evidence row and marks the field verified with it.
- **comment-on-field** icon with the open field-comment count from `virtual.open_comments_by_field`.
- **proposal indicator** (Phase 2, §8.7) when `virtual.open_proposals_by_field` has open proposals for the field.

**Derived values** appear in the Wartime group with an explanation: basis, the reason (label and definition of its `derived_reason` term from `/api/vocab`, verbatim), links to the deciding event or participation (labels from `refs`), and, whenever it differs from the displayed candidate, the launch interval over all candidates (e.g. "2022-03 · month" with "Launch interval over all candidates: 2022-01-01 – 2022-03-31"), so a reason such as `imprecise_date` can be traced to the dates it refers to.

**Edit mode** (`edit=1`; only on a live record):
- While editing, the History tab is disabled, so the form and the typed values stay mounted.
- **Starting values:** entering edit mode keeps the record's fields in component state, together with the form values. The PATCH sends only the form values that differ from these starting values, so fields the user did not touch are never sent (DATA_MODEL §6.5); background refetches never change the form values.
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
| `doc_links`, `json`, system fields | read-only in the edit form; Phase 2 adds one-click confirm and reject of document links on the document page (§8.7) |

- **Sticky save bar:**
  - optional change note, required where a rule demands it: changing `in_paper_scope` asks for a new `scope_note`; setting `verification_status` to verified or disputed asks for a note;
  - Save / Cancel;
  - unsaved changes trigger the prompt "Discard unsaved changes?" when leaving the page or edit mode.

**Error displays:**
- `reference_deleted` offers to open (and undelete) the referenced row;
- `unique_violation` highlights the field and links to the existing record;
- in edit mode these links open in a new tab, so the form keeps its values; errors on fields without an input (e.g. a `canonical_url` clash) and other refused saves (e.g. `entity_deleted`) appear in an alert above the save bar, and the form stays open.

**Related panels:**

| Type | Panels |
|---|---|
| project | Services (name, kind, channels, status, launch; "+ Add service"), Events (sorted by date: type, date, basis, description; "+ Add event"), linked Documents, Participations, Relations (`f.endpoint=in:<id>`), Indicators, Evidence (read-only lists with empty states, e.g. "Documents arrive with the collectors in Phase 2") |
| service | project, parent service and child services, Events ("+ Add event"), linked Documents (`f.links=in:<id>`), Participations, Relations, Indicators, Evidence |
| event | subject, Evidence |
| document | metadata, extracted text as plain text, links (subjects with origin and state), Evidence that cites it |
| organization | Participations |
| evidence | subject and cited document (links) |
| participation | organization and subject (links), Evidence |
| relation | both ends (links), Evidence |
| indicator | subject (link), Evidence |
| component | Relations, Evidence |
| saved view | "Open the view in its table" (the table with the stored query) |

After "+ Add service" or "+ Add event" the user stays on the page and the new row appears in the list. Related lists show the first 100 rows; table types link to their table ("Open in table"). Each row of a type with a page (table types and the record-page types, e.g. an evidence row) is listed by its linked label, which opens that page; there a wrong evidence row is corrected (Edit), withdrawn (Delete) or commented on.

### 4.2 History

**Revision list:** version, time, channel and action badges (§1.5), note, changed-field chips; Phase 2 adds the collector and run link for channel `collector`, a link to the import's changes for channel `import` and a "proposal" badge for revisions with a `proposal_id` (§8.7).

**Diff view:**
- selecting a revision shows its stored diff (the selected single revision is component state, not part of the URL);
- "Compare" mode picks any two versions (`/diff?from=&to=`; the selection is kept in the URL; a single pick is kept as `from` until the second adds `to`);
- old → new per field; long texts get word-level diffs (jsdiff); `meta` and `state` changes are shown separately; fields that are not recorded in an older snapshot are marked; refs show labels.
- Attribution that would name the app's one user is left out of diffs and changed-field chips (§1.5): the provenance key `by` (its `src` says the same) and a comment's `resolved_by` (`resolved_at` is shown).

**Restore this version** (a "Restore" button per row, accessible name "Restore version N"):
- The modal first calls `restore` with `dry_run: true` and shows the resulting changes, one per field with a checkbox (default all), plus the later revisions of the selected fields that would be undone, counted per channel (e.g. "Undoes later changes: manual (1 revision)"). It requires a note.
- Confirming sends the selected `fields`.
- The button is disabled for the current version and for deleted entities ("Undelete first").
- Afterwards: refetch, plus a notice with the new version, any `warnings` and `skipped_fields`.

### 4.3 Comments panel

A collapsible right-hand panel that can be opened via URL `comments=open`.

**Filters:** open (the default), resolved or all; field (incl. "entity-level only"); "show deleted" (`deleted=include`). A `thread=<id>` link switches the status filter to "all" and scrolls to the thread.

**Thread display:** root comment with field chip, status and time, replies below.

**Actions:**
- reply (not on deleted roots);
- edit; the "edited" label opens the comment's revision list with word diffs and "Restore this version";
- resolve or reopen (root);
- delete; undelete (with "show deleted").

**Composer:** Markdown textarea (maximum from `meta.limits`) with an optional field selector for new threads; replies are posted without `field` (they take the root's field, DATA_MODEL §6.6). There is no client-side Markdown preview; the server returns `body_html`. The note of a comment restore is optional; comment edits send `note: null`.

After a successful "Disputed…" (§4.1) the panel opens with the composer set to that field.

## 5. Other pages

- **RecentChangesPage:**
  - filters: record type (incl. comment, vocabulary term, saved view), channel (`ui` labelled "manual", §1.5), action, date range (local days, sent as timestamps), batch; Phase 2: run and proposal (chips when the URL carries `run_id` or `proposal_id`, set by links from the run and review pages), and run and proposal badges on the rows;
  - the page URL keeps the API parameter names, except that `since` and `until` hold local days (`YYYY-MM-DD`); the request sends the first and last instant of those days as timestamps;
  - rows grouped by local day: time, channel and action badges, entity link (type + label), version, changed fields, note;
  - link targets: comments link to their subject with `comments=open&thread=<root id>` (a reply links to its root, `context.parent_id`), vocabulary terms to the Codebook page, saved views to their table with the view applied, the other records without a table to their record page (§2);
  - expanding a row loads `GET /api/revisions/{revision_id}` and shows its diff.
- **CommentsPage:**
  - filters: status, record type (a single-value select), text, deleted; status "All" and "Hide deleted" are expressed by leaving the parameter out;
  - one row per thread: thread (excerpt of the root, linked), subject link, field, status, started (time), number of replies, last activity;
  - clicking opens the subject page with `comments=open&thread=<id>` (vocabulary terms open the Codebook page, records without a table their record page, §2).
- **TrashPage:**
  - tabs for every soft-deletable type: the five table types, participation, component, relation, indicator, evidence, saved view, and comments (vocabulary terms are deactivated, not deleted);
  - sorted by `-deleted_at`; deleted items with label (linked to the record's page, also for the record-page types), `deleted_at`, the deletion note and "deleted together with n others" for cascades. The cascade size comes from one request per page for the delete revisions within ±60 s of the page's deletion times (`page_size=500`), counting the rows that share a batch; if that request is cut off, the count reads "n or more";
  - the comments tab lists deleted threads (roots, `GET /api/comments?deleted=only`), newest deletion first; deleted replies under a live root are undeleted from the comments panel ("show deleted");
  - **Undelete** with a note in the shared undelete dialog (also used by the detail page): the cascade option is offered unless the deletion is known to be a single one, and is preselected for a known cascade.
- **CodebookPage:**
  - vocabulary list (label, number of terms, "fixed" badge);
  - terms table: code, labels, definition, active, `usage_count`, sort order, attributes such as `candidate`, open comments;
  - **Edit** (modal, generic PATCH of `vocabulary_term`; code and vocabulary read-only). For `event_type` it shows a switch for `attributes.counts_as_modification`, with a warning that derived values will be recomputed. "Replaced by" is a picker of active codes, enabled only for inactive terms; "Active" is locked for fixed codes;
  - **Add term** (the `in_create` fields plus the code, whose format `^[a-z0-9_]+$` is checked in the browser, and the `event_type` switch) and **Deactivate**, both disabled for fixed vocabularies and fixed codes;
  - **History** (like every curated record, assignment §6): the revision list, the stored diff of the selected revision, a "Compare two versions" switch that picks any two versions (component state; `/diff?from=&to=`) and a "Restore" button per row (accessible name "Restore version N"; disabled for the current version) that opens the shared restore form inline below the list (dry run with a checkbox per field and required note, as in §4.2); the server applies the codebook rules (fixed codes, `replaced_by`) to a restore like to any edit;
  - **comments panel** per term (`term=`, `comments=open`, `thread=`).

## 6. Code structure

```
frontend/src/
  main.tsx  router.tsx  theme.ts
  api/        client.ts (fetch wrapper, ApiError), types.ts, queries.ts (TanStack Query hooks + keys), lookup.ts
  lib/        query-string.ts (filter grammar helpers incl. ~empty), partial-date.ts, format.ts, diff.ts, urls.ts (URL host and input rules), download.ts,
              clipboard.ts, bulk.ts, write-rules.ts, filter-describe.ts, field-validation.ts, entity.ts, vocab.ts
  hooks/      useUrlSearch, useVocabIndex
  components/ layout/, table/ (incl. filters/), fields/ (display + input per type), detail/ (incl. the add-evidence form), history/,
              comments/, changes/ (recent changes and comment feed), trash/ (incl. the shared undelete dialog), codebook/, ExternalLink.tsx and small shared components
  pages/      Overview, EntityTable, EntityDetail, Record (generic record page), RecentChanges, Comments, Trash, Codebook, NotFound, RouteError;
              Phase 2: Review, Runs, RunDetail, Sources, SourceDetail, Import
  (Phase 2)   components/review/ (proposal cards, edit-and-accept forms, bulk bar), runs/ (start-run modal, stats grid, messages and fetch tables),
              sources/ (collector cards, observation table), import/ (mapping editor, plan table, import history), documents/ (add-document modal, links panel,
              Tag now), merge/ (merge and unmerge dialogs), detail/SeenInSourcesPanel.tsx, changes/ListParamFilter.tsx, SnapshotLink.tsx;
              api/acquisition-types.ts (the types of API §7), api/runs.ts, proposals.ts, imports.ts, documents.ts (the hooks per endpoint group; query keys
              and invalidation stay in queries.ts), api/uploads.ts (raw-body uploads); test/acquisition-fixtures.ts
  test/       Vitest setup, fixtures and the fetch mock
frontend/e2e/ Playwright specs and the server start script (§7)
```

**Query keys:** `['meta']`, `['vocab']`, `['stats']`, `['list', type, canonicalQs]`, `['facets', type, field, facetQs]`, `['item', type, id]`, `['revisions', type, id, …]` (type `comment` for comment histories), `['comments', subjectId, qs]`, `['comments', 'feed', qs]`, `['changes', qs]` (also `['changes', 'revision', id]`), `['lookup', qs]`; Phase 2 keys in §8.8.

**Invalidation after a write:**
- always `['stats']`, `['changes']` and `['lookup']`;
- entity writes: the item (all items of the type after a create), the lists and facets of the type and its revisions;
- comment writes: `['comments']`, the comment's revisions, and the subject's item and the lists of its type (counts; `['vocab']` for a term);
- after any write to an event or a participation: also all project and service items, lists and facets (derived values may have changed);
- after a vocabulary-term write: `['vocab']`, `['meta']` and all lists, facets and items; after a cascading delete or undelete: all lists, facets and items;
- invalidation never changes the values or the starting values of an open edit form (§4.1).

## 7. Tests

- **Vitest:**
  - round-trip of filter grammar and URL (incl. Cyrillic values, commas in text values, `~empty`, chips, canonical sorting);
  - validation and formatting of partial dates;
  - the edit form sends only the fields that differ from its starting values, and asks before leaving with unsaved changes;
  - diff helpers;
  - the URL input rules and `ExternalLink` (new tab, host shown).
- **Playwright E2E:**
  - **setup** (`frontend/playwright.config.ts`, `frontend/e2e/`):
    - the backend (`mdt serve`) serves the built frontend on a free port and a temporary database created with `mdt db upgrade` + `mdt seed` (`e2e/start-server.mjs`); `make e2e` builds the frontend first, `npm run e2e` needs an existing build;
    - `@playwright/test` is pinned to the preinstalled Playwright version, and Chromium comes from `/opt/pw-browsers` when present (`PLAYWRIGHT_BROWSERS_PATH`);
    - every scenario fails on an uncaught page error; there are no retries;
    - the scenarios use synthetic texts and set up synthetic values through the API where the seed leaves fields empty;
  - **scenarios** (the letters are those of the spec names; the conflict scenarios (e) and (f) were dropped with D-15):
    - (a) the projects table shows 20 rows;
    - (b) filter by `paper_cluster` and sort by `name_en`, `name_uk` (exact expected order), `policy_domains` and `verification_status` (asc and desc); a `contains:дія` filter on `name_uk`; the URL updates and a reload keeps the state;
    - (c) edit a field with a note → the history shows the change as "manual" with its note, and the stored revision has channel `ui`;
    - (d) diff of a revision, compare two versions, restore with the dry-run preview (one field deselected; "Undoes later changes: manual (1 revision)"), and the new revision on channel `restore`;
    - (g) comment thread create, reply, resolve, delete and undelete; the "open comments" quick filter;
    - (h) export CSV and XLSX of a filtered view; after ticking a column, the export has the visible columns after the record ID.

## 8. Phase 2 pages and components (data acquisition)

All data comes from `docs/API.md` §7 (and the generic endpoints for records). Values are rendered as text (§1.4); stored HTML is never rendered, and raw snapshots are offered as downloads only.

### 8.1 Navigation and routes

- **Header navigation:** Overview · Projects · Services · Events · Documents · Organizations · **Review (n)** · Changes · Comments · **Runs** · **Sources** · **Import** · Codebook · Trash. `n` = `open_proposals` from `/api/stats` (refetched every 60 s and after writes); hidden when 0. While a run is running, "Runs" shows a small spinner.

| Route | Page | Search params |
|---|---|---|
| `/review` | `ReviewPage` (§8.2) | `tab=proposals\|unverified`, `state` (default `open`), `kind`, `collector`, `entity_type`, `subject_id`, `run_id`, `field`, `sort`, `page`, `page_size`, `proposal` (one expanded proposal) |
| `/runs` | `RunsPage` (§8.3) | `collector`, `status`, `trigger`, `page`, `page_size` |
| `/runs/$id` | `RunDetailPage` (§8.3) | `tab=messages\|fetches\|changes`, `level`, `outcome`, `page` |
| `/sources` | `SourcesPage` (§8.4) | — |
| `/sources/$collector` | `SourceDetailPage` (§8.4) | `present`, `bound`, `q`, `page` |
| `/import` | `ImportPage` (§8.5) | `page` (of the import history) |

Apart from the page-state parameters `tab`, `proposal`, `level`/`outcome` (passed on to the fetch and message lists) and `page`, the query strings are the API's list parameters, as for tables (§1.2).

### 8.2 Review inbox (`/review`)

- **Tabs:** "Proposals (n)" and "New unverified". The second lists, per type (service, document, event), the number of records created by collectors that are still unverified, each linking to its table filtered with `f.created_by=contains:collector:&f.verification_status=in:unverified` (no API of its own).
- **Header:** counts by kind and collector (`GET /api/proposals/summary`); a collapsible "Pattern precision" table for `create_event` proposals (pattern, open, accepted, rejected, precision).
- **Filters:** state (open by default; accepted, accepted with changes, rejected, superseded, all), kind, collector, entity type; `run_id`, `subject_id` and `field` appear as removable chips when the URL carries them (links from run pages and detail pages); sort (last seen, created).
- **Proposal card** (one per proposal, compact, newest first):
  - header: kind badge; the subject as a link (struck through if deleted) or "New <type>" for `create_entity`; the field label (`update_field`); collector and run link; "seen n times, last <time>"; the state badge when not open (with decision note and time);
  - body by kind:
    - `update_field`: "Current" (`live_value` with the field's provenance badge and lock icon) next to "Proposed"; long texts as word diff (jsdiff, as in the history), lists as chips with added and removed items marked; for add-only URL lists the proposed URLs are shown as additions to the current list; a text-version proposal shows the character counts and, when expanded, a word diff of the current and the proposed text (`texts` from `GET /api/proposals/{id}`);
    - `create_entity`: the observed field values as a definition list; "Possible matches" (`payload.candidates`, labels from `refs`), each with "Link to this";
    - `create_event`: subject, event type, date with its basis; for text evidence the quote with the matched alias highlighted (client-side substring match, rendered as React elements) and the document as a link; for archive evidence the archived capture (`ExternalLink` to `archive_url`) with the CDX row;
    - `possible_duplicate`: both records side by side (label, URL, published or source, collector) with basis and similarity;
    - `possibly_discontinued`: reason, last seen, missing since, the current `status`;
  - source line: source URL (`ExternalLink`), "Snapshot" (downloads `/api/snapshots/<id>/body`), the quote where present;
  - **actions** (open proposals only): **Accept**, **Edit & accept…**, **Reject…**; `create_entity` adds **Link to existing…** (a lookup select restricted to the proposal's type); `possible_duplicate` offers **Mark as duplicate…** (documents: choose which of the two is the duplicate) or **Merge…** (services and projects: opens the merge dialog of §8.7 with this proposal), and **Not duplicates…** (reject with note).
- **Edit & accept** opens a modal with the editable values, prefilled from the proposal, using the field inputs of §4.1: the one field (`update_field`); the create form of the type with its `in_create` fields and constraints (`create_entity`: a project needs `in_paper_scope` and a `scope_note`, which the proposal never contains, and an optional slug, empty = generated from the site's slug); the event form (subject, event type, date, date basis, date text, descriptions) (`create_event`); a `status` select (`possibly_discontinued`). It sends the values that differ from the proposal and the person's additions (API §7.4). **Accept** on a project's `create_entity` proposal opens the same form, because the scope is the person's decision.
- **Reject** asks for a note (required).
- **Bulk:** checkboxes and a bar "Accept selected" (a confirmation lists the count; the summary reports proposals that need values (new projects, duplicates) and stale ones (the field changed since the proposal was raised) as left open, to decide one by one) and "Reject selected…" (note); the result is summarised like bulk edits (§3).
- After a decision: an inline notice with a link to the written record (`result_id`; router links cannot render in toasts) and the list refetches. Empty state: "No open proposals" with a link to Runs.
- Details: a `proposal=<id>` link to a proposal that is not on the current page shows it at the top as "Linked proposal"; the summary badges link to the inbox filtered by that kind or collector; Edit & accept is not offered for text-version proposals and system fields (the API refuses `values` for them); an unchanged `update_field` form sends `values: null` (a plain accept), because `values: {}` would clear the field. Each `update_field` card loads its subject (cached per subject) for the provenance badge and lock icon of the current value.

### 8.3 Runs (`/runs`, `/runs/$id`)

- **RunsPage:**
  - "Start run" opens a modal: collector (available collectors; unavailable ones disabled with their reason, e.g. "CONTACT_EMAIL is not set in .env"; `needs_server_check` collectors with a notice), mode (if the collector has modes), and the collector's supported parameters (`limit`, `refetch`, `recall_sample`, `recall_seed`); submitting sends `POST /api/runs` and opens the run's page; `409 run_in_progress` says that another run is running and links to it.
  - Filters: collector, status, trigger (multi-selects, sent as comma lists). The start modal has no `document_ids` input ("Tag now" sets it).
  - Table: collector, status badge (running blue, succeeded green, partial orange, failed red, cancelled grey), trigger, mode, started time, duration, requests, snapshots, created, updated, proposals opened, errors and warnings; a "replay" badge for runs with `params.replay`. Row click opens the run.
  - While a listed run is running, the list refetches every 3 s.
- **RunDetailPage:**
  - header: collector label (link to its source page), status badge, started and finished times, duration, last heartbeat (running), trigger, mode, parameters, `code_version`, complete listing (yes/no); actions **Cancel** (running) and **Run again** (same mode and parameters);
  - the fatal `error` of a failed run in an alert (e.g. "thedigital.gov.ua: blocked", which is how a blocked source is reported);
  - stats grid with every `stats` key (labelled; `extra` keys as given);
  - tabs: **Messages** (filter by level, with counts per level; time, level icon, code, message, URL, snapshot link, subject link), **Fetch log** (filter by outcome; time, method, URL, status, outcome badge, bytes, duration, attempt, snapshot link, error), **Changes** (the Recent changes feed with `run_id`, reusing its table, and a link "Open in Recent changes"), and a link "Proposals of this run" (`/review?run_id=<id>&state=all`); the status badges sit in a group labelled "Status" and the counters in `dt`/`dd` pairs;
  - refetches every 3 s while running; when the status changes to finished it invalidates the data queries (§8.8).

### 8.4 Sources (`/sources`, `/sources/$collector`)

- **SourcesPage:** one card per collector: label and source ID, enabled and available (with the reason), a "needs checks from the target server" notice, hosts with their intervals and the excluded hosts, licence code and statement, last run (status, time, link) and a running indicator, observation counts (present, missing; each a link to the detail page filtered), open proposals (link to `/review?collector=<name>`), and **Run now** (the start modal with the collector preselected).
- **SourceDetailPage:** the collector's details including its declaration (per entity type: creates or proposes new records, writable fields, propose-only fields, possibly discontinued), the recent runs, and the **observations** table: key, label, URL, the bound record (link) or "unbound", present (or "missing since <time>, n runs"), first seen, last seen; filters present, bound and text. Observations are read-only.

### 8.5 Import (`/import`)

- **One page, the mapping in component state** (nothing is stored before the run, API §7.9): a file input (CSV or XLSX) → `POST /api/uploads` (raw body, §8.6) → entity type (the five table types) and, for an XLSX file with several sheets, the sheet → `POST /api/imports/preview`.
- **Mapping** table: each column with its header and three sample values from the preview, and a select (the importable fields, "id (key only)", "— ignore —"), prefilled from `suggested_mapping`; a field can be chosen only once; the key select offers `key_fields` and "none" (key fields that no column maps to are disabled; the default is `id` if a column maps to it, else the type's natural key, `slug` or `url`, if a column maps to it, else none); an optional note.
- **Dry run** (`POST /api/imports/dry-run`) shows the plan: count tiles (rows, create, update, unchanged, conflicts, errors) and the row table (row number, action badge, record link, changes as "field: current → new", conflicts with their reason, errors).
- **Run import** is enabled after a dry run with the current mapping and asks for confirmation with the counts; `POST /api/imports` then writes, and the result replaces the plan, with a link "Show changes" (`/changes?batch_id=<import id>`).
- **History** below: the past imports (file, type, status, created, counts); a row expands to its stored errors and conflicts (`GET /api/imports/{id}`) and links to its changes.

### 8.6 Adding documents

- The Documents table toolbar has **"+ Add document"** next to "+ New"; it opens a modal with the tabs **Upload file** and **From URL**. Both first store the file and then show the server's suggested values as editable defaults; only what the person submits is written (DATA_MODEL §17.2).
- **Upload file:** a file input (text is extracted from PDF, DOCX, HTML and TXT; other files are stored without text); choosing a file uploads it (`fetch` with the `File` as body and `filename` in the query, `api/uploads.ts`) and fills the form from `suggested`: title, language, publisher, and the warnings (e.g. "the PDF has no text layer"); further fields: source URL with "retrieved at" (default now; required with a URL), document type, published with its basis (required with a date) and verbatim text, licence, note. **Create** sends `POST /api/documents/manual` with the snapshot's ID.
- **From URL:** URL → **Fetch** (`POST /api/documents/fetch`) → the fetched response (final URL, status, content type, size; for a Wayback capture URL the original URL and the capture time) and the form filled from `suggested`; document type, language, published, licence, note → **Create**.
- Errors: `unique_violation` links to the existing document; `fetch_failed` shows the reason, and for `blocked`, `throttled`, `robots_disallowed` or `robots_unavailable` suggests uploading a saved copy or the URL of an archived copy; `collector_unavailable` explains that `CONTACT_EMAIL` must be set in `.env`.
- After success: a notice and the buttons **Open** and **Tag now** (`POST /api/runs {"collector": "tagger", "params": {"document_ids": [id]}}`, then a link to the run; `409 run_in_progress` says to tag later from the Runs page). The document's links panel offers **Tag now** too; both follow the tagger run until it finishes, so the suggested links appear.

### 8.7 Additions to detail pages

- **Header:** a badge "n open proposals" (`virtual.open_proposals`; project, service, event, document) linking to `/review?subject_id=<id>`. For a merged project or service, the deleted banner reads "Merged into <survivor>" with a link and an **Unmerge…** button (note; `POST …/unmerge`, then a notice listing any skipped references); Undelete is not offered for it. The Trash lists merged projects and services with "Merged into <survivor>" and **Unmerge…** instead of Undelete; its dialogs stay open with their result when the list changes.
- **Field rows:** next to the provenance badge, "1 proposal" (or n) when `virtual.open_proposals_by_field` lists the field, linking to `/review?subject_id=<id>&field=<field>`. The provenance of `collector:<name>@<run_id>` opens a popover on click (it holds links): the collector, a link to the run and the field's snapshots (`raw_snapshot_ids`) as downloads; the other provenance kinds keep the tooltip. Snapshot downloads go through `fetch` → Blob → `a[download]`, as exports do, so a refused download shows the server's message.
- **"Seen in sources" panel** (project, service, document; in the Sources & Evidence group): the observations from `item.observations` (collector with a link to its source page, key, label, URL, first and last seen, present or missing since, bound by).
- **Documents:** the text version's `raw_snapshot_id` renders as a "Snapshot" download link; `source_record_at` is shown in the Sources group. The **links panel** lists each link with origin, state, matched aliases, match count and snippet; suggested links have **Confirm** and **Reject**; automatic links cannot be removed (a rejected one stays, so its subject is not suggested again, DATA_MODEL §15.8), manual links have **Remove**; **Add link…** (a lookup of projects and services) adds a confirmed manual link. Each action sends `PATCH /api/entities/document/<id>` with the full `links` list in which only that link changed (channel `ui`).
- **Merge** (project, service): the header button "Merge…" (the page has no actions menu) opens a dialog: pick the other record (a lookup of the same type, excluding this one), then `GET …/merge-preview` shows each differing field with both values and a choice (survivor, merged, and union for lists), the references to be moved (counts; evidence and comments stay on the merged record) and any conflicts (merging is disabled while there are conflicts); a swap button exchanges survivor and merged record; a note; **Merge** sends `POST …/merge` and opens the survivor (after a swap, too) with a notice ("the other record is in the trash, marked as merged into this one; it can be unmerged there"). From the review inbox the dialog carries the proposal's ID.
- **History:** revisions on channel `collector` show the collector and link to the run (`run_id`); channel `import` links to the import's changes (`/changes?batch_id=<batch_id>`); revisions with a `proposal_id` show a "proposal" badge linking to `/review?proposal=<id>&state=all`; channel `merge` has its own badge (actions `merge` and `unmerge`).

### 8.8 Other additions, query keys and invalidation

- **Overview:** tiles for open proposals (link to `/review`, and to "New unverified records", `/review?tab=unverified`) and the last finished run (collector, status, time, link), plus a running-run indicator (`/api/stats.runs`).
- **Tables:** the new quick filters come from meta ("Open proposals", "Collected"; API §3.1); the Columns menu offers the new fields (`open_proposals`, `source_record_at`).
- **Query keys:** `['collectors']`, `['collector', name]`, `['runs', qs]`, `['run', id]`, `['run-fetches', id, qs]`, `['run-messages', id, qs]`, `['proposals', qs]`, `['proposal', id]`, `['proposals-summary']`, `['observations', qs]`, `['imports', qs]`, `['import', id]`, `['merge-preview', type, id, mergedId]`.
- **Invalidation:**
  - after accepting, rejecting or bulk-deciding proposals: `['proposals']`, `['proposals-summary']`, `['stats']`, `['changes']`, and the items, lists and facets of the subject's type (for `create_event` also all project and service items, lists and facets, as after any event write, §6);
  - after starting or cancelling a run: `['runs']`, `['collectors']`, `['stats']`; when a polled run turns finished: all lists, items and facets, `['proposals']`, `['proposals-summary']`, `['observations']`, `['stats']` and `['changes']` (a run changes data);
  - after an import run: the lists, items and facets of its type, `['imports']`, `['changes']`, `['stats']`; after a merge or unmerge: all lists, items and facets; after adding a document: the document lists and facets, `['stats']`;
  - additionally: every rule adds `['lookup']` and the revisions of the touched types; a decision adds `['proposal']` and `['observations']` (an accepted `create_entity` binds its observation) and, for a duplicate of projects or services, all data; start and cancel add `['run', id]` and `['collector']`, and the start seeds `['run', id]` with the answer (the run still running), so a page that follows a short run (the tagger, a replayed run) sees it running first and refreshes the data when it finishes; a finished run adds `['runs']`, `['collectors']`, `['run-fetches', id]` and `['run-messages', id]`, also when it finishes on the runs list; merge and unmerge add the proposal keys. Merge previews are never invalidated (an open dialog's preview of a merged pair would be refetched and refused); they have `staleTime` 0, so each dialog fetches a fresh one;
  - as in §6, invalidation never changes the values of an open edit form.

### 8.9 Tests

- **Vitest:** proposal value rendering (word diff for text, added and removed list items, add-only URL additions); each edit-and-accept form sends only the changed `values`, and a project's `create_entity` form requires the scope; run polling stops when the run is finished, and a run started in the app that finished before its first poll still refreshes the data; the mapping editor applies suggestions and refuses a field twice; the merge dialog builds `fields`; uploads send the raw file with `filename` in the query; confirming or rejecting a document link sends the full `links` list with only that link changed, and an automatic link offers no Remove.
- **Playwright E2E** (setup as in §7): the Phase 2 scenarios run in a separate Playwright project `collectors` with **its own server instance and database** (a second `webServer` entry on another free port, `e2e/start-server.mjs` with the extra settings below), in one file run serially (`e2e/collectors.spec.ts`, `test.describe.configure({ mode: 'serial' })`, in the order listed), because collector runs touch many records and would disturb the parallel Phase 1 scenarios and each other. That server sets `COLLECTOR_REPLAY_DIR` to `backend/tests/fixtures/ministry_projects` (the replay transport serves those fixtures by URL, `docs/COLLECTORS.md` §4.10; no request leaves the machine, so the `CONTACT_EMAIL` rule does not apply). Wiring: `e2e/start-server.mjs <port> [collectors]` starts either server (both pin `SOURCES_FILE` and `COLLECTOR_RUN_INLINE=false`; the Phase 1 server pins `COLLECTOR_REPLAY_DIR` empty), and `playwright.config.ts` passes the free ports `MDT_E2E_PORT` and `MDT_E2E_COLLECTORS_PORT`; `make e2e` (and `npm run e2e`) therefore start two servers. Values that are not in the fixtures are synthetic (§7). Scenarios ((k), a vocabulary-term proposal, was dropped with term proposals):
  - (i) **DoD 3:** Runs → Start run `ministry_projects` → wait until finished (status `partial`, because detail pages without fixtures are refused) → the stats show records updated, proposals opened (the official URLs linked from the Brave1 and Дія.Цифрова громада pages) and new observations; the Messages tab lists the errors and the `unknown_code` warning for `how-tos`, and the Fetch log shows the refused URLs; start the same run again → finished; its stats show 0 records created, 0 revisions and 0 proposals opened (proposals seen again > 0); the Runs list shows both runs; Recent changes filtered by the second run's ID is empty.
  - (j) **DoD 5**, each branch on its own seed project, because an accepted value is never proposed again: the `description_uk` of `brave1`, `diia-city` and `virtual-assets` shows the collector badge; edit all three with a note (manual, locked) → run `ministry_projects` again → `brave1`'s page still shows the manual value with the manual badge and "1 proposal", and the review inbox shows the three proposals with current (manual) against proposed (collector); **Accept** on `brave1` → the field shows the collector value with the collector badge and the lock, and the history shows the revision with the "proposal" badge; **Edit & accept** on `diia-city` → the edited value with the manual badge, state "accepted with changes"; **Reject** with a note on `virtual-assets` → the value stays manual; a further run opens no new proposal for the three.
  - (l) **Manual document:** upload a small synthetic HTML file that mentions a seeded alias → the form shows the suggested title → Create → the document page shows the extracted text → "Tag now" → after the tagger run the links panel shows a suggested link → Confirm.
  - (m) **Import:** upload a synthetic CSV (`slug,notes` with a seeded project slug and a synthetic note) → mapping (key `slug`) → dry run shows 1 update → run → "Show changes" lists the import revision; a second CSV that sets a field the user edited manually shows a conflict in the dry run.
  - (n) **Merge and unmerge:** two synthetic services of one seeded project created through the API → merge one into the other in the UI → the survivor shows the chosen values; the merged record is in the trash with "Merged into" → Unmerge → both services are live again and the survivor shows its former values.
