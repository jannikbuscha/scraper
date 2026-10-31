# Frontend (UI)

> **Status:** v1 contract for Phase 1, revised 2026-10-28 after a five-lens contract review, updated the same day with the decisions of the Phase 1 build and integration, and simplified on 2026-10-29 for a single user (decision D-15, `PLAN.md` §12). **Extended on 2026-10-30 with the Phase 2 pages** (§8: review inbox, runs, sources, import, adding documents, merge and unmerge, and the additions to detail pages) and the marked additions in §2–§7; revised the same day after a four-lens review. **Extended on 2026-10-31 with the Phase 3 pages** (§9: navigation, the document view with evidence capture and screening, analysis records, timeline, dashboard, exports) and the additions marked "Phase 3" in §2–§8; revised the same day after a four-lens review.
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
- **Links:** the `ExternalLink` component turns stored URLs (validated as `http`/`https` by the server, DATA_MODEL §1.2) into `<a href target="_blank" rel="noopener noreferrer">` and shows `URL.host` (punycode) next to the text. Outside tables a long text is cut off with an ellipsis; in the cells of the Phase 2 tables (run messages, fetch log, observations, §8.3, §8.4, §8.7) its `wrap` variant breaks the text at any character, in lines of at most 32em, with the host below when it does not fit beside it, so the whole URL stays readable and a long URL never widens the table or pushes other columns off-screen. The short values of those tables (times, levels, codes, methods, numbers, snapshot links, badges) stay on one line, and their badges are never cut short.
- **Dialogs:** the header close button of every dialog is named "Close dialog" (a theme default for Mantine's icon-only button), distinct from the "Close" button some dialogs have in their footer.
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

Phase 2 adds `/review`, `/runs`, `/runs/$id`, `/sources`, `/sources/$collector` and `/import` (§8.1). Phase 3 replaces the Overview at `/` with the dashboard and adds `/timeline`, `/exports`, the tables and detail pages of components, participations, relations, indicators and evidence, and the document view (tab `read` of `/documents/$id`) (§9.1). Releases come in Phase 4 and are **not** shown in the navigation before then.

**Header:**
- app name "MDT Portfolio";
- navigation (Overview, Projects, Services, Events, Documents, Organizations, Review (n), Changes, Comments, Runs, Sources, Import, Codebook, Trash; the Phase 2 items are described in §8.1; Phase 3 groups the items into menus, §9.1);
- global search box: `GET /api/lookup?types=project,service,event,document,organization&q=…&limit=25` from two characters (debounced 250 ms), grouped by type, with "show all" links to `/<type>s?q=…&sort=relevance`.

## 3. EntityTablePage

**Toolbar:**
- title with total count;
- search input (`q`, debounced 300 ms; with `q` set, a "relevance" sort option appears);
- **quick filters** from `meta.quick_filters`:
  - `toggle` → a chip that is active only if the URL contains exactly its key/value pair; activating it replaces any filter on that field; deactivating it removes the parameter;
  - `chips` (period; Phase 3 also the evidence dimensions) → a chip group (multi-select) over the codes of the field's vocabulary, writing `f.<field>=in:…` with the codes in vocabulary order (no chip selected removes the parameter);
  - `preset` (events, documents) → one group of mutually exclusive date presets, from the quick filter's `presets` list (API §3.1); without such a list the UI builds the three `within` presets from `meta.parameters`;
- **Active filters** (Phase 3): a line below the toolbar describes every `f.*` filter whose field is not a visible column (`lib/filter-describe.ts`, labels via lookup), filter-only fields such as the reason fields included, each with a remove button, plus **Clear filters**, so a table opened from a dashboard link (§9.5) shows why it holds these rows;
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

Phase 3 extends the panels (participations, relations, indicators and evidence with their own "+ Add" forms, organisation and component panels, the document view) as described in §9.3.

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

- **Lists with footer pagination** (Recent changes, Comments, the Trash tabs, and the Phase 2 lists of §8: review inbox, runs, a run's messages, fetch log and changes, observations, import history): page numbers with first and last, page size 25 / 50 / 100 / 200 and the row range, kept in the URL (`page`, `page_size`). As in tables (§3), a page past the end of a list that has entries (after its last entries were decided, undeleted or deleted, or from an old link) has its own empty state: "This page is past the end of the list", the total and the last page, and **Go to the last page**. The list's own empty state ("No changes recorded yet", "No open proposals", "No runs yet", …) appears only when the list has no entries at all, and past the end the footer keeps its page links, with no page marked current.
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
  (Phase 3)   pages/ Dashboard, Timeline, Exports (Overview is removed); components/reading/ (document view: ReadingPane, segments,
              SelectionBar, CapturePanel, NewCodeForm, ScreeningPanel, DocumentEvidencePanel, DocumentProposalsPanel, QueueBar, DateDocumentForm),
              analysis/ (ParticipationForm, RelationForm, IndicatorForm, EvidenceSourceInputs, DimensionEvidenceList), timeline/ (TimelineChart,
              TimelineFilters, export), dashboard/ (tiles, PeriodBar, CrosstabTable, CrosstabBuilder, CoveragePanel, ScreeningPanel, ChecksPanel),
              exports/ (export cards); lib/ text-offsets.ts, segments.ts, timeline-layout.ts, chart-style.ts, csv.ts; hooks/useDocumentShortcuts.ts;
              api/analysis-types.ts (the types of API §8), api/reading.ts, evidence.ts, timeline.ts, crosstab.ts, exports.ts
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
  - the URL input rules and `ExternalLink` (new tab, host shown, the wrapping variant for table cells);
  - the named close button of dialogs; the past-the-end state of the lists with footer pagination (§5), which keeps the page links.
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

Apart from the page-state parameters `tab`, `proposal`, `level`/`outcome` (passed on to the fetch and message lists) and `page`, the query strings are the API's list parameters, as for tables (§1.2). A filter change returns to page 1; `proposal` is not a filter, so expanding or collapsing a proposal card keeps the page.

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
  - **actions** (open proposals only): **Accept**, **Edit & accept…**, **Reject…**; `create_entity` adds **Link to existing…** (a lookup select restricted to the proposal's type); `possible_duplicate` offers **Mark as duplicate…** (documents: choose which of the two is the duplicate; each option is chosen by its label, and each document opens from its own link next to it, in a new tab, so the dialog stays) or **Merge…** (services and projects: opens the merge dialog of §8.7 with this proposal), and **Not duplicates…** (reject with note).
- **Edit & accept** opens a modal with the editable values, prefilled from the proposal, using the field inputs of §4.1: the one field (`update_field`); the create form of the type with its `in_create` fields and constraints (`create_entity`: a project needs `in_paper_scope` and a `scope_note`, which the proposal never contains, and an optional slug, empty = generated from the site's slug); the event form (subject, event type, date, date basis, date text, descriptions) (`create_event`); a `status` select (`possibly_discontinued`). It sends the values that differ from the proposal and the person's additions (API §7.4). **Accept** on a project's `create_entity` proposal opens the same form, because the scope is the person's decision.
- **Reject** asks for a note (required).
- **Bulk:** checkboxes and a bar "Accept selected" (a confirmation lists the count; the summary reports proposals that need values (new projects, duplicates) and stale ones (the field changed since the proposal was raised) as left open, to decide one by one) and "Reject selected…" (note); the result is summarised like bulk edits (§3).
- After a decision: an inline notice with a link to the written record (`result_id`; router links cannot render in toasts) and the list refetches. The notice says what happened: "Accepted the proposal.", "Accepted the new record." (a created record), "Linked the source entry to an existing record; nothing else was written." (Link to existing, which only binds the observation, DATA_MODEL §16.4), "Rejected the proposal.", "Marked as not duplicates.", or, when nothing was left to write, that the proposal is closed as superseded. Empty state: "No open proposals" with a link to Runs, only when there are none; a page past the end (e.g. after the last cards of the last page were decided) has its own state (§5).
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
  - tabs: **Messages** (filter by level, with counts per level; time, level icon, code, message, URL, snapshot link, subject link), **Fetch log** (filter by outcome; time, method, URL, status, outcome badge, bytes, duration, attempt, snapshot link, error), **Changes** (the Recent changes feed with `run_id`, reusing its table, and a link "Open in Recent changes"), and a link "Proposals of this run" (`/review?run_id=<id>&state=all`); the status badges sit in a group labelled "Status" and the counters in `dt`/`dd` pairs; in the Messages and Fetch log tables URLs wrap and the short values stay on one line (§1.4), so every column, the message and the error included, stays readable without scrolling sideways at the E2E viewport (1440 px);
  - refetches every 3 s while running; when the status changes to finished it invalidates the data queries (§8.8).

### 8.4 Sources (`/sources`, `/sources/$collector`)

- **SourcesPage:** one card per collector: label and source ID, enabled and available (with the reason), a "needs checks from the target server" notice, hosts with their intervals and the excluded hosts, licence code and statement, last run (status, time, link) and a running indicator, observation counts (present, missing; each a link to the detail page filtered), open proposals (link to `/review?collector=<name>`), and **Run now** (the start modal with the collector preselected).
- **SourceDetailPage:** the collector's details including its declaration (per entity type: creates or proposes new records, writable fields, propose-only fields, possibly discontinued), the recent runs, and the **observations** table: key, label, URL, the bound record (link) or "unbound", present (or "missing since <time>, n runs"), first seen, last seen; filters present, bound and text; URLs wrap (§1.4). Observations are read-only.

### 8.5 Import (`/import`)

- **One page, the mapping in component state** (nothing is stored before the run, API §7.9): a file input (CSV or XLSX) → `POST /api/uploads` (raw body, §8.6) → entity type (the five table types) and, for an XLSX file with several sheets, the sheet → `POST /api/imports/preview`.
- **Mapping** table: each column with its header and three sample values from the preview, and a select (the importable fields, "id (key only)", "— ignore —"), prefilled from `suggested_mapping`; a field can be chosen only once; the key select offers `key_fields` and "none" (key fields that no column maps to are disabled; the default is `id` if a column maps to it, else the type's natural key, `slug` or `url`, if a column maps to it, else none); an optional note.
- **Dry run** (`POST /api/imports/dry-run`) shows the plan: count tiles (rows, create, update, unchanged, conflicts, errors) and the row table (row number, action badge, record link labelled from the lookup (`GET /api/lookup?ids=…`, at most 100 IDs per request, because the plan names records by ID only), changes as "field: current → new", conflicts with their reason, errors).
- **Run import** is enabled after a dry run with the current mapping and asks for confirmation with the counts; `POST /api/imports` then writes, and the result replaces the plan, with a link "Show changes" (`/changes?batch_id=<import id>`).
- **History** below: the past imports (file, type, status, created, counts); a row expands to its stored errors and conflicts (`GET /api/imports/{id}`) and links to its changes.

### 8.6 Adding documents

- The Documents table toolbar has **"+ Add document"** next to "+ New"; it opens a modal with the tabs **Upload file** and **From URL**. Both first store the file and then show the server's suggested values as editable defaults; only what the person submits is written (DATA_MODEL §17.2).
- **Upload file:** a file input (text is extracted from PDF, DOCX, HTML and TXT; other files are stored without text); choosing a file uploads it (`fetch` with the `File` as body and `filename` in the query, `api/uploads.ts`) and fills the form from `suggested`: title, language, publisher, and the warnings (e.g. "the PDF has no text layer"); further fields: source URL with "retrieved at" (default now; required with a URL), document type, published with its basis (required with a date) and verbatim text, licence, note. **Create** sends `POST /api/documents/manual` with the snapshot's ID.
- **From URL:** URL → **Fetch** (`POST /api/documents/fetch`) → the fetched response (final URL, status, content type, size; for a Wayback capture URL the original URL and the capture time) and the form filled from `suggested`; document type, language, published, licence, note → **Create**.
- Errors: the URL field checks the URL rule of DATA_MODEL §1.2 as the server does, and **Fetch** stays disabled until the URL is valid; a `validation_error` the server still returns (`docs/API.md` §7.8, e.g. a Wayback capture URL whose original lacks `http(s)://`) shows its message, one line per field as in the other forms; `unique_violation` links to the existing document; `fetch_failed` shows the reason, and for `blocked`, `throttled`, `robots_disallowed` or `robots_unavailable` suggests uploading a saved copy or the URL of an archived copy; `collector_unavailable` explains that `CONTACT_EMAIL` must be set in `.env`.
- After success: a notice and the buttons **Open** and **Tag now** (`POST /api/runs {"collector": "tagger", "params": {"document_ids": [id]}}`, then a link to the run; `409 run_in_progress` says to tag later from the Runs page). The document's links panel offers **Tag now** too; both follow the tagger run until it finishes, so the suggested links appear.

### 8.7 Additions to detail pages

- **Header:** a badge "n open proposals" (`virtual.open_proposals`; project, service, event, document) linking to `/review?subject_id=<id>`. For a merged project or service, the deleted banner reads "Merged into <survivor>" with a link and an **Unmerge…** button (note; `POST …/unmerge`, then a notice listing any skipped references: each record, and the record a skipped reference now points to, as a link labelled from the lookup); Undelete is not offered for it. The Trash lists merged projects and services with "Merged into <survivor>" (the survivor's label from the lookup, as in the banner; the list carries only its ID) and **Unmerge…** instead of Undelete; its dialogs stay open with their result when the list changes.
- **Field rows:** next to the provenance badge, "1 proposal" (or n) when `virtual.open_proposals_by_field` lists the field, linking to `/review?subject_id=<id>&field=<field>`. The provenance of `collector:<name>@<run_id>` opens a popover on click or Enter (it holds links): the collector, a link to the run and the field's snapshots (`raw_snapshot_ids`) as downloads. The popover is portaled, so focus moves into it when it opens: Tab moves between its links, and Escape (or a click outside) closes it and returns focus to the badge. The other provenance kinds keep the tooltip. Snapshot downloads go through `fetch` → Blob → `a[download]`, as exports do, so a refused download shows the server's message.
- **"Seen in sources" panel** (project, service, document; in the Sources & Evidence group): the observations from `item.observations` (collector with a link to its source page, key, label, URL, first and last seen, present or missing since, bound by), in the observations table of §8.4 (URLs wrap, §1.4).
- **Documents:** the text version's `raw_snapshot_id` renders as a "Snapshot" download link; `source_record_at` is shown in the Sources group. The **links panel** lists each link with origin, state, matched aliases, match count and snippet; suggested links have **Confirm** and **Reject**; automatic links cannot be removed (a rejected one stays, so its subject is not suggested again, DATA_MODEL §15.8), manual links have **Remove**; **Add link…** (a lookup of projects and services) adds a confirmed manual link. Each action sends `PATCH /api/entities/document/<id>` with the full `links` list in which only that link changed (channel `ui`).
- **Merge** (project, service): the header button "Merge…" (the page has no actions menu) opens a dialog: pick the other record (a lookup of the same type, excluding this one), then `GET …/merge-preview` shows each differing field with both values and a choice (survivor, merged, and union for lists), the references to be moved (counts; evidence and comments stay on the merged record) and any conflicts (merging is disabled while there are conflicts); a swap button exchanges survivor and merged record; a note; **Merge** sends `POST …/merge` and opens the survivor (after a swap, too) with a notice ("the other record is in the trash, marked as merged into this one; it can be unmerged there"). From the review inbox the dialog carries the proposal's ID.
- **History:** revisions on channel `collector` show the collector and link to the run (`run_id`); channel `import` links to the import's changes (`/changes?batch_id=<batch_id>`); revisions with a `proposal_id` show a "proposal" badge linking to `/review?proposal=<id>&state=all`; channel `merge` has its own badge (actions `merge` and `unmerge`), and the diff names the survivor (`merged_into`) by its label from the lookup.

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

- **Vitest:** proposal value rendering (word diff for text, added and removed list items, add-only URL additions); each edit-and-accept form sends only the changed `values`, and a project's `create_entity` form requires the scope; run polling stops when the run is finished, and a run started in the app that finished before its first poll still refreshes the data; the mapping editor applies suggestions and refuses a field twice; the merge dialog builds `fields`; uploads send the raw file with `filename` in the query; a URL that only the server refuses (`400 validation_error` of a fetch) shows the server's message, one line per field; confirming or rejecting a document link sends the full `links` list with only that link changed, and an automatic link offers no Remove; expanding or collapsing a proposal card keeps the page; a page of the inbox emptied by a decision shows the past-the-end state, not "No open proposals"; Link to existing is reported as linking; the duplicate document is chosen by its label without leaving the inbox; the collector provenance popover moves focus into itself and returns it on Escape; the import plan, the Trash's "Merged into" and the unmerge result label records from the lookup, and the lookup asks for at most 100 IDs per request.
- **Playwright E2E** (setup as in §7): the Phase 2 scenarios run in a separate Playwright project `collectors` with **its own server instance and database** (a second `webServer` entry on another free port, `e2e/start-server.mjs` with the extra settings below), in one file run serially (`e2e/collectors.spec.ts`, `test.describe.configure({ mode: 'serial' })`, in the order listed), because collector runs touch many records and would disturb the parallel Phase 1 scenarios and each other. That server sets `COLLECTOR_REPLAY_DIR` to `backend/tests/fixtures/ministry_projects` (the replay transport serves those fixtures by URL, `docs/COLLECTORS.md` §4.10; no request leaves the machine, so the `CONTACT_EMAIL` rule does not apply). Wiring: `e2e/start-server.mjs <port> [collectors]` starts either server (both pin `SOURCES_FILE` and `COLLECTOR_RUN_INLINE=false`; the Phase 1 server pins `COLLECTOR_REPLAY_DIR` empty), and `playwright.config.ts` passes the free ports `MDT_E2E_PORT` and `MDT_E2E_COLLECTORS_PORT`; `make e2e` (and `npm run e2e`) therefore start two servers. Values that are not in the fixtures are synthetic (§7). Scenarios ((k), a vocabulary-term proposal, was dropped with term proposals):
  - (i) **DoD 3:** Runs → Start run `ministry_projects` → wait until finished (status `partial`, because detail pages without fixtures are refused) → the stats show records updated, proposals opened (the official URLs linked from the Brave1 and Дія.Цифрова громада pages) and new observations; the Messages tab lists the errors and the `unknown_code` warning for `how-tos`, and the Fetch log shows the refused URLs; start the same run again → finished; its stats show 0 records created, 0 revisions and 0 proposals opened (proposals seen again > 0); the Runs list shows both runs; Recent changes filtered by the second run's ID is empty.
  - (j) **DoD 5**, each branch on its own seed project, because an accepted value is never proposed again: the `description_uk` of `brave1`, `diia-city` and `virtual-assets` shows the collector badge; edit all three with a note (manual, locked) → run `ministry_projects` again → `brave1`'s page still shows the manual value with the manual badge and "1 proposal", and the review inbox shows the three proposals with current (manual) against proposed (collector); **Accept** on `brave1` → the field shows the collector value with the collector badge and the lock, and the history shows the revision with the "proposal" badge; **Edit & accept** on `diia-city` → the edited value with the manual badge, state "accepted with changes"; **Reject** with a note on `virtual-assets` → the value stays manual; a further run opens no new proposal for the three.
  - (l) **Manual document:** upload a small synthetic HTML file that mentions a seeded alias → the form shows the suggested title → Create → the document page shows the extracted text → "Tag now" → after the tagger run the links panel shows a suggested link → Confirm.
  - (m) **Import:** upload a synthetic CSV (`slug,notes` with a seeded project slug and a synthetic note) → mapping (key `slug`) → dry run shows 1 update → run → "Show changes" lists the import revision; a second CSV that sets a field the user edited manually shows a conflict in the dry run.
  - (n) **Merge and unmerge:** two synthetic services of one seeded project created through the API → merge one into the other in the UI → the survivor shows the chosen values; the merged record is in the trash with "Merged into" and the survivor's label → Unmerge (the dialog's header close button is named "Close dialog", its footer button "Close") → both services are live again and the survivor shows its former values.
  - (o) **Long URLs:** the latest run's messages and fetch log, the collector's observations and a seeded project's "Seen in sources" panel, each with a synthetic URL of about 250 characters without a break opportunity put into the server's answer (`page.route`): at 1440 px every column header ends inside the viewport, no badge is cut short and no time breaks over lines.
  - (p) **Keyboard:** on a seeded project whose description the collector wrote, Enter on the provenance badge opens the popover with focus on its first link; Tab reaches the run link and the snapshot download; Escape closes it and focus is back on the badge.

## 9. Phase 3 pages and components (analysis)

All data comes from `docs/API.md` §8 and the generic endpoints. Document texts are rendered as plain text (§1.4): no stored HTML is ever rendered, and no `dangerouslySetInnerHTML` is used for data. The data rules are DATA_MODEL §19–§23.

### 9.1 Navigation and routes

- **Header navigation** (grouped, so the list stays short): **Dashboard** · **Data ▾** (Projects, Services, Events, Documents, Organizations, Components, Participations, Relations, Indicators, Evidence) · **Timeline** · **Review (n)** · **Exports** · **Activity ▾** (Changes, Comments, Runs, Sources, Import, Trash) · **Codebook**. The two menus are Mantine `Menu`s of links (keyboard operable); the button of the group that holds the current route is marked active; the run spinner of §8.1 sits on "Activity ▾"; "Review (n)" is unchanged. A small "Unscreened (n)" badge (`/api/stats.documents.unscreened`) on Documents in the Data menu.
- **Banner:** while `/api/stats.derived_current` is false, every page shows "Derived values are out of date: run mdt recompute" (API §8.7; exports are refused until then).

| Route | Page | Search params |
|---|---|---|
| `/` | `DashboardPage` (§9.5); the Overview is removed and its tiles move here | `entity_type=project\|service` (default `project`), `basis=launch\|portfolio_entry` (default `launch`), `scope=in_paper_scope\|all` (default `in_paper_scope`), `row`, `col` (the crosstab builder) |
| `/timeline` | `TimelinePage` (§9.4) | the parameters of API §8.5 |
| `/exports` | `ExportsPage` (§9.6) | — |
| `/components`, `/participations`, `/relations`, `/indicators`, `/evidence` | `EntityTablePage` (§3) | as §1.2 |
| `/components/$id` (likewise for the other four) | `EntityDetailPage` (§4) | as §4 |
| `/documents/$id` | `EntityDetailPage` with the tabs **Read** (the document view, §9.2, default) · Details · History | `tab=read\|details\|history`, `queue`, `evidence`, and the params of §4 |

- `/records/$id` redirects IDs of the new table types to their pages (as for the Phase 1 table types, §2); only saved views keep the record page.
- `queue` holds a documents list query string (URL-encoded, canonical, without `page`, `page_size` and `cols`); `evidence` an evidence ID to show.

### 9.2 Document view (tab `read`)

**Layout:** a header, the queue bar, then two columns from 1 200 px: the **reading pane** (about 60 %) and the **side column** (about 40 %), each scrolling on its own; below 1 200 px the side column follows the pane.

**Header:** title (and `title_en` below it); badges: doc type, language, published (canonical with precision), computed period (DATA_MODEL §8.4), licence, screening status, "cited n×" (`citation_count`), verification dot; actions: **Original ↗** (`url`), **Archive ↗** (first `archive_urls` entry), **Snapshot** (download of `raw_snapshot_id`, §8.7), Copy link, Comments toggle, and a **Keyboard** popover listing the shortcuts below.

**Queue bar** (from `GET /api/documents/{id}/neighbours?<queue>`): "‹ Previous · 12 of 340 (120 unscreened) · Next › · Next unscreened ⏭ · Back to list", with the queue's filters described in words (`lib/filter-describe.ts`). When the document no longer matches its queue: "No longer in this queue (e.g. screened)", with the neighbours still offered. Without `queue`: "Not opened from a list", with a link to the documents table. Moving to another document keeps `queue` and drops `evidence`. The documents table opens rows with `queue` = its own canonical query, and its toolbar gets **Start screening**: it opens the first unscreened document of the current query (`GET /api/entities/document?<query>&f.screening_status=in:unscreened&page_size=1`, replacing any `f.screening_status` filter of the query) with `queue` = the current query unchanged, so Previous and Next walk the whole list and Next unscreened skips the screened documents. Coding works through a queue too (DATA_MODEL §21): the quick filters "Not coded" and screening status included give the queue of included documents without a dimension citation.

**Reading pane:**
- **Text:** one element, a region named "Extracted text", with `white-space: pre-wrap`, `overflow-wrap: anywhere`, a measure of about 75 characters, and `lang` from the document's language. It is split into **segments** at every boundary of a mark or a highlighted alias (`lib/segments.ts`), never at the selection; each segment is a `<span data-o="<code-point offset>">` holding exactly its substring as one text node, so the pane's text content equals the stored text. Marks (API §8.2), all also announced in the tooltip and never by colour alone: evidence = an underline (solid for record evidence, double for field evidence, thick for dimension evidence; a small legend above the text explains the styles); proposal = dotted outline; a highlighted alias (**Show in text** of a link) = light background. The app's selection (below) is drawn without touching the segments, through the CSS Custom Highlight API (a `Highlight` over a `Range` of the segments' text nodes, styled by `::highlight(mdt-selection)` with a blue background), so it stays visible when the browser's own selection is gone (e.g. while the capture panel has the focus); where the API is missing, the selection bar alone shows it. Hovering or focusing a mark shows its label; clicking an evidence mark selects its row in the evidence panel (`evidence=<id>`), and `evidence` in the URL scrolls to and highlights it.
- **Selection** (`selectionchange`, `mouseup`, `keyup` while the browser selection lies in the pane): both ends of the browser selection are mapped to code points (DATA_MODEL §20.1): the nearest ancestor `span[data-o]` gives the segment's offset, and the offset inside its text node, counted in UTF-16 units, is converted with `lib/text-offsets.ts` (`codePointCount(text.slice(0, utf16))`; the inverse `utf16Offset(text, codePoints)` places marks and the highlight). The ends are ordered, clamped to the pane, and leading and trailing whitespace is trimmed. The result only updates the app's selection (offsets and quote, shown by the selection bar and the highlight) and never re-renders the text, so a selection that is still being dragged or extended with the keyboard keeps its place. An empty result inside the pane (e.g. a click into the text) clears the app's selection; a browser selection outside the pane (e.g. in an input of the capture panel) leaves it unchanged. The **selection bar** above the text shows the quote (its first 200 characters, then "…"), its length ("123 characters"; over 1 000 in red with "Select at most 1 000 characters" and capture disabled), the offsets, **Cite…** and **Clear**. Keyboard users select with the browser's own find (closing it leaves the found text selected in Chromium and Firefox) or caret browsing; there is no find bar of the app's own.
- **No text:** "This document has no extracted text (extraction method: <method>)." with **Cite whole document…** (the capture panel without a passage; a quote typed verbatim from the original is optional) and the original's link.

**Capture panel** (`CapturePanel`, opened by **Cite…** or `e`; it takes the top of the side column, so the text stays visible):
- the exact quote (scrollable) with its offsets;
- **Cite for:** chips of the document's confirmed links; suggested links as chips marked "suggested" that cannot be chosen before their **Confirm** button is used ("Confirm the link first": capture never changes links, DATA_MODEL §20.2); **This document** (the document itself, e.g. for its publication date); and **Other record…** (a lookup over project, service, organization, component, event, participation, relation, indicator, document). Likewise, when the case of the citation (DATA_MODEL §20.5) is a project or service that the document does not link as confirmed, e.g. chosen through Other record… or as the subject of a record created from the passage, the panel shows "Not linked to this document" with **Add link** (a confirmed manual link, its own PATCH of the document's `links`, §8.7) and enables Save after it, so codings and the document's links agree;
- **Supports:** a segmented control **Record** (`target = entity`) · **Field** (a select of the subject type's tracked, non-system, editable fields grouped by `meta.groups`; the chosen field's input of §4.1 appears, prefilled with its current value, together with the fields a rule requires with it: a date's basis and verbatim text, `scope_note` with `in_paper_scope`; a changed value is sent as `values`, so the field is coded from the passage in one step, API §8.3; `target = field:<name>`) · **Dimension** (D1–D4 as radio cards with the labels and definitions of the `dimension` vocabulary; `target = dimension:Dn`) with **Codes** (a multi-select of the active `analysis_code` terms whose `attributes.dimension` is the chosen `dn`, with **New code…**: code, English label, definition (required), include and exclude notes, the dimension preset; it creates the term through `POST /api/entities/vocabulary_term` and selects it; empty state "No analysis codes for D1 yet");
- with a field target, **Mark the field verified with this quote** (disabled, with the reason, while the field and its new value are empty);
- **Locator** (e.g. "p. 4") and **Note** (the evidence's `description`);
- **Save evidence** → `POST /api/evidence/capture` with `document_id`, the current `text_hash`, the offsets, the displayed `quote` and, when the field input changed, `values` (API §8.3);
- **Create from this passage ▾** (Event · Participation · Relation · Indicator · Component · Organization): the panel switches to that type's create form (the `in_create` fields with the inputs of §4.1; defaults: the chosen chip as `subject_id` (event, participation, indicator) or `from_id` (relation); **no default date basis**: the basis select appears with its date and must be chosen, with CODEBOOK §2.6 as help ("an announcement date is inferred"); "+ New organization…" inside the participation form as in §9.3); nothing is parsed from the passage, but **Use selection** fills a verbatim text field (`date_text`, `period_text`, `value_text`) with the quote when it fits its length; saving sends one request with `record` (API §8.3);
- **Errors:** validation messages at their inputs (`record.data.<field>` maps to the create form, `values.<field>` to the field input); `409 invalid_state` with `text_changed`: the notice "The text of this document changed while you were reading. The new text is loaded; select the passage again." The text and marks are refetched, the selection is cleared, and the panel keeps its other inputs; `409 reference_deleted` and `unique_violation` with links, as in §4.1;
- **After saving:** a notice "Evidence saved" with links to the evidence (and the new record); **the selection stays** until **Clear** or a new selection, so the same passage can be cited again for another subject, field or dimension; the marks and the evidence panel refetch; the panel keeps its subject and target.

**Side column** (collapsible sections, in this order):
1. **Screening:** the status (and reason); **Include** (`i`), **Exclude…** (`x`: reason from `exclusion_reason`, required, and note), **Mark unscreened** (`u`); the screening note editable in place. Each decision is `PATCH /api/entities/document/{id}` with `screening_status`, `screening_reason` (null unless excluded) and `screening_note` when changed (DATA_MODEL §21). The switch **Next unscreened after a decision** (default on, kept in `localStorage` under `mdt.screening.advance`) then opens `next_unscreened_id` of the queue, if any.
2. **Links:** the links panel of §8.7 (the region "Document links": Confirm, Reject, Remove for manual links, Add link…, Tag now); each link has **Show in text**: it highlights the link's `matched_aliases` in the text by a case-insensitive substring match in the browser, as the review inbox does (§8.2), and scrolls to the first; the highlight is a reading aid, not the tagger's match.
3. **Evidence:** the evidence rows that cite the document (`GET /api/entities/evidence?f.document_id=in:<id>&page_size=500`), grouped into **This text version** (sorted by `char_start`), **Earlier text versions** (their `text_hash` differs from the document's; labelled "earlier text version: capture the passage again to cite the current text", DATA_MODEL §20.4) and **Whole document**; each row: target (field label, or the dimension's label with its codes, or "Record"), subject link, quote (two lines, expandable), locator, verification dot, **Show in text** (current version) and **Open**. **Cite whole document…** opens the capture panel without a passage; on a document with text, a typed quote must occur in it exactly once and is then stored as that passage, otherwise the server's message asks to select the passage.
4. **Proposals:** the open proposals concerning the document (`GET /api/proposals?document_id=<id>`), shown with the review inbox's cards and actions (§8.2: Accept, Edit & accept…, Reject…, Mark as duplicate…, Not duplicates…); a `create_event` card adds **Show in text** (selects its sentence).
5. **Metadata:** publisher, published (basis and verbatim text), retrieved at, source and external ID, extraction method, licence, archive URLs, `source_record_at` (labelled "site timestamp, not a publication date"), and a link to the Details tab ("Seen in sources", all fields). **Date this document…** (offered prominently while `published` is empty): published, its basis (`stated_in_source` · `inferred`, no default) and the verbatim text with **Use selection**; with a selection, saving sends a capture with the document as subject, target `field:published` and `values` (API §8.3), so the date is born with its evidence; without one, a PATCH.

**Keyboard shortcuts** (`hooks/useDocumentShortcuts.ts`; only when the focus is not in an input, textarea, select or editable element and no dialog is open): `j` next and `k` previous in the queue, `n` next unscreened, `i` include, `x` exclude…, `u` mark unscreened, `e` cite the selection, `Escape` clear the selection.

**Deleted document:** read-only (no capture, screening or link actions), with the deleted banner of §4.

### 9.3 Analysis records (D2–D4)

- **Tables** for components, participations, relations, indicators and evidence: `EntityTablePage` from meta (default columns `in_list`, quick filters of API §3.1, saved views, bulk edit, view exports). Their rows open their own detail pages. **"+ New"** is offered for components only (the generic create modal of §3 with the evidence inputs below, optional, DATA_MODEL §22.3); participations, relations, indicators and evidence are created on their subjects' pages and in the document view, where they get their subject and, for indicators, their required evidence.
- **Create forms on detail pages** (the related panels of §4.1); each stays on the page and refetches its panel after saving:

  | Page | Panel and action | Form |
  |---|---|---|
  | project, service, component | Participations · **+ Add participation** | `ParticipationForm`: organisation (lookup of organisations, with **New organization…**: `name_en`, `name_uk`, `org_type`, `country`, `urls`, created by `POST /api/entities/organization` and then selected), role (with the codebook definition as help), start and start basis, end and end basis (the basis select appears with its date, offers `stated_in_source` and `inferred` and has no default), period text, description, optional evidence |
  | organization | Participations · **+ Add participation** | the same form with a subject lookup (project, service, component) instead of the organisation |
  | project, service, component | Relations · **+ Add relation** | `RelationForm`: direction (**This record → other** or **Other → this record**), relation type (each option reads as a sentence with the two labels, e.g. "Diia builds on …", with the codebook definition as help), the other end (lookup over project, service, component, with **New component…**: `name_en`, `name_uk`, `component_type`, `description`, `urls`), description, optional evidence |
  | project, service, component, organization | Indicators · **+ Add indicator** | `IndicatorForm`: metric (autocomplete from `GET /api/indicators/metrics`), value, **value text** (verbatim, e.g. with "more than"), unit (autocomplete from that metric's units), as of and its basis (no default), description, **evidence required** |
  | project, service, component, organization | Events · + Add event | the Phase 1 form with the evidence inputs open; saving without evidence needs the tick **No source to cite yet** |
  | every evidence-subject type | Evidence · **Add evidence…** | the Phase 1 add-evidence form (§4.1), now sent through `POST /api/evidence/capture` (URL or document source), with the target choice of §9.2 (record, field, dimension and codes) |

- **Evidence inputs** (`EvidenceSourceInputs`, shared): source **URL** (URL, retrieved at with default now, archive URL, quote) or **Document** (a document lookup, a typed quote, locator; the retrieval time comes from the document), with the hint "On a document with text the quote must occur in it exactly once; passages are best captured in the document view", and the link rule of §9.2 (Add link when the document does not link the record's case as confirmed). A form with evidence sends `POST /api/evidence/capture` with `record` (one write unit); without, `POST /api/entities/{type}`.
- **Project and service pages:** the Framework D1–D4 group lists, under the d1–d4 fields, the record's **dimension evidence** per dimension ("D1 · 3 passages", expandable: quote, codes, document link opening the document view at the passage), from `GET /api/entities/evidence?f.subject_current_id=in:<id>&f.dimension=empty:false&page_size=500` (so evidence of records merged into this one is included); the Wartime group shows `entry_period` (with its reason and the portfolio entry's basis) next to `portfolio_entry`, `existed_before_invasion`, a flag "rests on a date without evidence" when `derived_unevidenced` or `entry_unevidenced` is true, and on project pages the note "Derived from the project's own events. Its services: n new in war, m adapted in war" (`services_new_in_war`, `services_adapted_in_war`, each linking to the services table filtered by project and trajectory; decision D-16).
- **Related panels** (extending §4.1): project and service: Participations, Relations and Indicators get their "+ Add" actions; component: Relations, Participations, Events, Indicators, Evidence; organization: Participations, Events (institutional context events, "+ Add event"), Indicators, **Published documents** (`f.publisher_org_id=in:<id>`), Evidence. Evidence panels list `f.subject_current_id=in:<id>`.
- **Header:** an "n evidence" badge (`virtual.evidence_count`) linking to the evidence table filtered by `f.subject_current_id=in:<id>`.
- **Participation page:** when the organisation is the focal organisation and the role is a portfolio role (`attributes.portfolio_role`), the notice "This participation can decide the portfolio entry of <subject>".
- **Evidence page:** anchored evidence shows its quote with 200 characters of context on each side from its own text version (`GET /api/documents/{id}/text?text_hash=`), labelled "current text version" or "earlier text version", and **Open in document view** (`/documents/<id>?tab=read&evidence=<evidence id>`); the edit form shows the anchor fields read-only (DATA_MODEL §20.3). Field evidence whose `value_snapshot` differs from the current value of the field on the record named by `subject_current_id` (the survivor, for evidence of a merged record, DATA_MODEL §18) says "Supports an earlier value: <value_snapshot>"; evidence panels mark such rows the same way.
- **Codebook page:** the vocabulary `dimension` (fixed) shows its four terms; the Add and Edit forms of `analysis_code` terms have a required **Dimension** select writing `attributes.dimension` (disabled, with the reason, while `usage_count` > 0; a code used only by deleted evidence is frozen too, DATA_MODEL §7, and the server's 400 message then appears at the select), and its terms table shows the dimension; `participation_role` terms get a switch for `attributes.portfolio_role` with the warning that derived values will be recomputed (as for `counts_as_modification`, §5).

### 9.4 Timeline

**TimelinePage** (`/timeline`):
- **Filters** (one row above the chart; all in the URL as API §8.5 parameters): subject type (Projects · Services), cluster (projects: multi-select writing `f.paper_cluster=in:`), in paper scope (switch: `f.in_paper_scope=eq:true`, services `f.project_in_paper_scope=eq:true`), subjects (lookup → `ids`), event types (multi-select; modification types marked), include services (projects), group by, window from–to, show disputed, **only events with evidence** (`evidence=with`). The projects and services tables get a **Timeline** toolbar button that opens the page with their `f.*`, `q` and `sort`; the Events panel of project and service pages links **Open in Timeline** with `ids=<id>` (projects also `include_services=true`).
- **Chart:** `TimelineChart` renders SVG with React from `layoutTimeline(data, options)` (`lib/timeline-layout.ts`), a pure function: no text measurement, no current date, no randomness, so the same data and options give the same layout. A **table view** toggle lists the shown events (lane, type, date with precision and basis, date text, description, evidence count), the accessible alternative to the chart.
- **Layout rules** (options: `width`, default the container width, 1 600 px for exports):
  - columns: lane labels 260 px, the plot, the undated column 56 px; a header of 48 px (period labels and the year axis) and a footer (legend and caption);
  - `x(d) = plot_left + (day(d) − day(domain.start)) / (day(domain.end) + 1 − day(domain.start)) × plot_width`, rounded to 0.1 px; an interval [s, e] spans `x(s)` to `x(e + 1 day)`;
  - **period bands:** one background rectangle per period clipped to the domain (`periods` from the API), labelled at the top with the `period` vocabulary's labels; **cut-off lines** at `x(ministry_founded)` and `x(full_scale_invasion)`, dashed, labelled with the dates (`DD.MM.YYYY`, from `parameters`);
  - year ticks on every 1 January with labels; quarter ticks where a year is wider than 160 px;
  - lanes in API order under group header rows (24 px); within a lane, events in API order go greedily into the first sub-row whose last occupied end plus 6 px lies before the event's start, where an event occupies [x(s) − 5, max(x(e + 1 day), x(s) + 5) + 5] and an archive bound [x(e) − 24, x(e) + 5]; a lane is 8 px plus 16 px per sub-row, plus 6 px when it has a portfolio band;
  - **portfolio band:** below a lane's marks, each `portfolio` participation (API §8.5) as a 3 px band from `x(start_start)` to `x(end_end + 1 day)` (open-ended: to the plot's end, with an arrow) with a tick at its start labelled "entry", so the launch and the entry into the ministry's portfolio can be compared (D-10);
  - **marks:** precision `day` → a circle (radius 4.5); `month`, `quarter` and `year` → a bar 7 px high from `x(s)` to `x(e + 1 day)` with 9 px end caps, so imprecision shows as length; basis `inferred` → the outline only, a bar with 45° hatching; `archive_upper_bound` → a hollow downward triangle at `x(e)` with a dashed line 24 px to the left ("≤", existed by); an event **without evidence** (`evidence_count = 0`) gets a dashed outline (dash 2 2) on top of its shape; a service's event in its project's lane (`service_id` set) is drawn at 70 % size, its service named in the tooltip; disputed events (when shown) → muted with a strike line; a mark that leaves the window is clipped with an arrow;
  - **lane labels:** the subject label cut to 34 characters with "…" (the full label in `<title>`) and a second line with the derived period and trajectory labels;
  - the undated column shows "+n undated" per lane (a tooltip lists them);
  - **legend** (mark shapes, colours, "├─┤ date range (precision)", "▽ ≤ archive upper bound", "hollow = inferred date", "dashed outline = no evidence recorded", "band = in the ministry's portfolio") and **caption**: "MDT Portfolio · <subject type> timeline · events: n (<period label> a · … · undated or straddling d; without evidence w) · lane periods and trajectories derived on the launch basis (projects from their own events) · filters: <description> · data revision <data_revision> (<data_as_of>) · app <version>".
- **Colours** (`lib/chart-style.ts`, the only place that defines chart colours; light mode only, §1.4): surface `#fcfcfb`; ink `#0b0b0b`, secondary ink `#52514e`, muted `#898781`, gridline `#e1e0d9`, axis `#c3c2b7`. Event colours by category: **introduction** (`launch`, `beta_launch`) `#2a78d6`; **modification** (every type with `attributes.counts_as_modification = true`, so decision D-2 shows directly) `#eb6834`; **discontinuation** `#1baf7a`; **other dated events** (e.g. `announced`, `legal_basis_adopted`) secondary ink `#52514e`; **first archived** muted `#898781` (always with its own triangle shape); portfolio bands secondary ink `#52514e`. The three hues were checked with the colour validator of the dataviz method for all pairs (colour-vision-deficiency ΔE ≥ 9.2, normal vision ΔE ≥ 24); the aqua is below 3:1 against the surface, so the legend, the tooltips and the table view carry its meaning too. **Period band tints:** before the ministry `#f0efec`, ministry before the invasion `#fcfcfb`, full-scale war `#e9e7e1`; their labels and the dashed cut-off lines identify them, never the tint alone.
- **Interaction:** marks are focusable (`tabIndex=0`, `role="link"`, an `aria-label` with type, date, subject and "no evidence" where it applies); hover or focus shows a tooltip (event type, date with precision and basis, date text, description, subject or service, verification, evidence count); click or Enter opens the event page.
- **Export ▾ SVG · PNG:** SVG = `renderToStaticMarkup(<TimelineChart layout={…} static />)` (React DOM server, no new dependency) with `xmlns`, embedded styles and the font stack `system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif`, a white background and `data-event-id` on every mark; the only stamp in it is the data revision with `data_as_of`, so the same view of the same data state exports the same bytes; file `timeline-<YYYYMMDD-HHMMSS>.svg`. PNG = that SVG drawn on a canvas at scale 2 and `canvas.toBlob('image/png')`; file `timeline-<YYYYMMDD-HHMMSS>.png`. Both downloads go through Blob → `a[download]` (§1.6).
- **States:** loading; "No events match these filters"; the API's "narrow the filters" message for too many lanes or events.

### 9.5 Dashboard

**DashboardPage** (`/`) is composed of `GET /api/stats`, the crosstab and coverage endpoints (API §8.6), facets and list totals (`page_size=1`); it has no endpoint of its own, so every number is the count of a table query that its link opens, except coverage's verified, disputed and with-evidence counts, which no list filter expresses (API §8.6).
- **Controls** (segmented, in the URL; defaults first): Records **Projects** · **Services** (`entity_type`); Basis **Launch** · **Portfolio entry** (help: decision D-10; the portfolio entry is the ministry's earliest participation in a portfolio role, recorded per project or service, so services often have none); Scope **In paper scope** · **All**. "Data revision n (<data_as_of>)" from `/api/stats` and a refresh button. When a crosstab or coverage response carries another `data_revision` than `/api/stats`, the header says "The data changed while the dashboard loaded" next to Refresh; while a collector run is running (`/api/stats.runs.running`) it says that the numbers may change. Numbers for the paper are taken with a dataset bundle of the same data revision, whose files recompute every dashboard number (`PLAN.md` N11). The **period field** is `period` for the launch basis and `entry_period` for the portfolio-entry basis. The **scope filter** (with "In paper scope") is `f.in_paper_scope=eq:true` for projects, `f.project_in_paper_scope=eq:true` for services and `f.subject_in_paper_scope=eq:true` for events; it joins every request of the selected type and of events; the evidence, participation, relation and document panels are not scoped.
- **Tiles** (from `/api/stats`): live counts per type (each a link to its table), open proposals (→ `/review`, and "New unverified records" → `/review?tab=unverified`), open comments, unscreened documents with **Start screening** (the first unscreened document, opened with the queue `f.screening_status=in:unscreened&sort=-published`), and the Phase 2 run tiles (last finished run, running run, `/api/stats.runs`).
- **Periods:** the crosstab `row=<period field>` × `col=period_unevidenced` (launch basis) or `col=entry_unevidenced` (portfolio entry), drawn as one horizontal bar per period (≤ 24 px thick, 4 px rounded data end), split into "deciding date has evidence" and "without evidence" (hatched), with counts and percentages as direct labels; the bars in `#2a78d6` and `unknown` in muted `#898781`, with its reasons as sub-rows (facet of `period_reason` or `entry_period_reason` with `f.<period field>=in:unknown`); each bar segment links to the table filtered accordingly. Under the bars: each period's span and length in months, the open war period ending at the `data_as_of` date ("full-scale war: 24.02.2022 – <date>, n months"), and the count per year next to each count, so the unequal and open-ended periods are visible; and "shown to exist before the invasion: n (period unknown: m)" (list totals with `f.existed_before_invasion=eq:true`, and with `f.period=in:unknown` added).
- **War trajectory:** the same form for `war_trajectory` × `derived_unevidenced` (the launch, archive or trajectory event without evidence), with reasons from `trajectory_reason` and the note "always on the launch basis; project values from the project's own events (D-16)".
- **Crosstabs** (in this order; the column is the period field unless stated): projects: `paper_cluster` × period, `unit_type` × period, `status` × period, `paper_cluster` × `war_trajectory`, `development_mode` × `war_trajectory`, `period` × `entry_period` (launch against portfolio entry, D-10); services: `project_id` × period, `kind` × period, `status` × period, `development_mode` × `war_trajectory`, `period` × `entry_period`; then the **crosstab builder**: row and column selects over the fields the crosstab endpoint accepts for the selected type (kept in the URL as `row` and `col`). Each crosstab is a table heatmap: every count printed; cells shaded by count / table maximum with the blue sequential ramp (`#cde2fb`, `#b7d3f6`, `#9ec5f4`, `#86b6ef`, `#6da7ec`, `#5598e7`, `#3987e5`, `#2a78d6`, `#256abf`, `#1c5cab`, `#184f95`; zero unshaded; text white from `#2a78d6` on); row and column totals; the `(empty)` row in italics; the note "A record counts once per value" for multi-valued rows; every non-zero cell links to the table of its type with the request's query plus the row and column filter (API §8.6, cell links). **CSV** per crosstab, generated in the browser with the CSV rules of API §5 (UTF-8 BOM, `QUOTE_ALL`; `lib/csv.ts`): the leading columns `data_revision`, `data_as_of`, `app_version`, `entity_type`, `basis`, `scope`, `ministry_founded`, `full_scale_invasion`, then the row code and label and one column per column value, and the file name `crosstab-<type>-<row>-<col>-<basis>-<scope>-r<data_revision>.csv`.
- **Events by period:** the events crosstab `event_type` × `period`, modification types marked "(modification)".
- **Coverage:** record verification (facet of `verification_status`); records with and without evidence (list totals `f.evidence_count=range:1..` and `eq:0`); the **field grid** (`GET /api/entities/{type}/coverage`: rows = fields grouped by `meta.groups`; columns filled, verified, disputed, with evidence, empty, each a number with a thin bar; "empty" links to `f.<field>=empty:true` where the field's filter has `empty`); **dimension evidence** (the evidence crosstabs `dimension` × `document_period` and `dimension` × `case_period` with `f.dimension=empty:false`, so the codings compare across the periods by the documents' dates and by the cases' periods; the second is labelled "cases' launch period", because `case_period` stays on the launch basis whatever the Basis control says, DATA_MODEL §8.4); participations (`role` × `period` of participations; portfolio entry known: list total `f.portfolio_entry=empty:false`); relations by type (facet of `relation_type`); indicators (total, without evidence → link).
- **Screening:** document facets of `screening_status` and of `screening_reason` (excluded documents); the crosstabs `source_id` × `screening_status` and `screening_status` × `period`; included documents and of them coded (list total `f.screening_status=in:included&f.dimension_citation_count=range:1..`, DATA_MODEL §21); each number links to the documents table filtered accordingly.
- **Data-quality checks:** one line per check with its count (a list total) and a link to the table: verified without evidence (`f.verification_status=in:verified&f.evidence_count=eq:0`, the selected type); derived from unsourced dates (`f.derived_unevidenced=eq:true`); conflicting dates (`f.trajectory_reason=in:conflicting_dates`); adaptation without a relation or a rationale (`f.development_mode=in:adaptation_of_existing&f.adaptation_relation=eq:false&f.development_rationale=empty:true`, CODEBOOK §2.5); projects in scope without cluster (`f.in_paper_scope=eq:true&f.paper_cluster=empty:true`) or without portfolio entry (`f.in_paper_scope=eq:true&f.portfolio_entry=empty:true`); projects unchanged in war with wartime services (`f.war_trajectory=in:prewar_unchanged,unknown&f.services_new_in_war=range:1..`, and the same with `services_adapted_in_war`; D-16); events and indicators without evidence; included documents that are undated (`f.screening_status=in:included&f.published=empty:true`) or not coded (`f.screening_status=in:included&f.dimension_citation_count=eq:0`).
- **Proposals:** the open proposals by kind (`/api/proposals/summary`), linking to the review inbox.
- **Accessibility:** every bar chart has a "Show table" toggle; colours come from `lib/chart-style.ts` (§9.4).

### 9.6 Exports (`/exports`)

- Three cards, each with what it holds and a download button that shows a spinner while the server builds the file (the request builds it, API §8.8.1):
  - **Dataset bundle:** what it holds and leaves out (DATA_MODEL §23.2, D-5) → `GET /api/exports/dataset`;
  - **QDA corpus:** the included documents with their texts of every licence, with the notice "Internal working corpus: contains full texts of sources that are not openly licensed; do not publish or share it" → `GET /api/exports/qda`;
  - **Codebook:** **Markdown** and **CSV** (`GET /api/codebook/export?format=…`).
- After a download: the file name and size, and the hint "Keep this file to cite its data revision (Phase 4 releases make it permanent)" (`PLAN.md` N11). Errors: `privacy_check_failed` names the file and links the record (`record_id`); `derived_out_of_date` says to run `mdt recompute`; while `/api/stats.derived_current` is false the buttons are disabled with that reason.

### 9.7 Other additions, query keys and invalidation

- **Query keys:** `['document-text', id, textHash | 'current']`, `['neighbours', id, queueQs]`, `['timeline', qs]`, `['crosstab', type, qs]`, `['coverage', type, qs]`, `['indicator-metrics', q]`; the dashboard's facets and list totals use the keys of §6 (`['facets', …]`, `['list', …]`).
- **Invalidation:**
  - after a capture: `['document-text', documentId]`, the evidence lists, facets and items, the subject's item (and, after `values`, the lists and facets of its type), the lists of a created record's type, `['crosstab']`, `['coverage']` and, when an event, participation or relation was created or a subject's values were written, `['timeline']` and the project and service items, lists and facets (§6);
  - after a screening decision or a link change: the document item, the document lists and facets, `['neighbours']`, `['crosstab']`, `['stats']`;
  - after a proposal decision in the document view: §8.8 plus `['document-text', documentId]`;
  - after any write to events, participations, relations, indicators or evidence: also `['timeline']`, `['crosstab']` and `['coverage']`;
  - after **New code…** in the capture panel: as after a vocabulary-term write (§6).

### 9.8 Tests

- **Vitest:**
  - `lib/text-offsets.ts`: UTF-16 and code-point offsets on a text with Cyrillic and an emoji, in both directions; a selection across several segments maps to the right offsets; leading and trailing whitespace is trimmed; more than 1 000 characters disables capture; a selection change updates the selection bar without re-rendering the segments, and the highlight covers the stored offsets (`CSS.highlights` mocked);
  - `lib/segments.ts`: overlapping marks give the right boundaries and classes, and the concatenated segments equal the text;
  - capture panel: sends the passage with `text_hash` and the displayed quote, and `values` only when the field input changed; codes only for a dimension target and only that dimension's codes; New code… creates the term with the dimension preset and selects it; a suggested link must be confirmed before it can be chosen, and a case the document does not link needs Add link before Save; `text_changed` reloads the text and keeps the inputs; Create from this passage sends `record` and needs a chosen date basis; the selection stays after saving;
  - Show in text highlights a link's matched aliases case-insensitively;
  - screening: Include, Exclude (reason required) and Mark unscreened send the right PATCH (reason null unless excluded) and move to `next_unscreened_id`; shortcuts do nothing while focus is in an input;
  - `layoutTimeline`: the same input gives the same layout and the same SVG string; sub-row packing; circle, bar and triangle by precision and basis; the dashed outline of events without evidence; smaller service marks; the portfolio band and its open end; clipping at the window; band edges at the cut-off dates; the static SVG contains both cut-off dates, the data revision and every `data-event-id`; the PNG export draws at scale 2 (canvas mocked);
  - dashboard: a cell link joins the request's query with the row and column filters (`in:`, `any:`, `eq:`, `empty:true`, replacing a filter on the same field); the multi-valued note; the CSV of a crosstab (BOM, quoting, leading columns, file name);
  - exports page: Download uses fetch → Blob; `privacy_check_failed` shows the file and the record link; the buttons are disabled while derived values are out of date;
  - participation, relation and indicator forms: New organization and New component inline; evidence required for indicators; Use selection fills `value_text`; Add event needs evidence or the tick "No source to cite yet"; a form with evidence sends `POST /api/evidence/capture` with `record`.
- **Playwright E2E** (setup of §7 and §8.9; values not in the seed are synthetic). The Phase 1 project `chromium` ignores `collectors.spec.ts` and `analysis.spec.ts` (`testIgnore`); Phase 2's scenario (l) keeps working because the Read tab names its text region "Extracted text" and its links section "Document links".
  - in the Phase 1 project, in a file of its own (`e2e/document-view.spec.ts`; the project's scenarios run in parallel, so it uses its own records):
    - (q) **Document view:** two synthetic manual documents created through the API (uploaded TXT files sharing a synthetic token; the first names a seed project's alias in a sentence with a launch phrase of `codebook/event_patterns.yaml` and has an emoji before that sentence; the second names nothing); the tagger run for both through the API and awaited; the documents table filtered by `q=<token>` → open the first (so `queue` is set) → the Read tab shows the text in the region "Extracted text" and the links panel a suggested link → **Show in text** highlights the alias → **Confirm**; drag a selection over a few words with `page.mouse` (down, several moves, up) → the selection bar's quote equals the dragged words, so the selection survived the drag; select a phrase (a DOM Range set through `page.evaluate`) → **Cite…** → the linked project's chip → **Dimension** D1 → **Save evidence** → the evidence panel lists it, its mark appears, the selection stays, and the stored row (API) has offsets whose code-point slice of the stored text equals its `quote` (the emoji makes UTF-16 and code-point offsets differ); **Accept** the event proposal in the Proposals panel → the event exists with anchored evidence; **Include** → the next unscreened document opens and the queue bar counts one unscreened less; **Exclude…** with a reason → the status shows excluded with that reason.
  - in a new Playwright project **`analysis`** with its own server and database (a third `webServer` entry; `e2e/start-server.mjs <port> analysis`; `playwright.config.ts` passes `MDT_E2E_ANALYSIS_PORT`; `make e2e` starts three servers), in one file run serially (`e2e/analysis.spec.ts`, in this order), because these scenarios assert global counts:
    - (r) **Analysis records:** on an in-scope seed project A, **+ Add participation** of the focal organisation as operator from `2023-01` (stated in source) with URL evidence → the Wartime group shows portfolio entry 2023-01 and entry period "Full-scale war"; **+ Add relation** "builds on" with **New component…** → the component's page lists the relation; **+ Add indicator** with a value text and URL evidence → listed; **+ Add event** (an expansion `2024-05`, stated in source) without evidence cannot be saved until "No source to cite yet" is ticked; then it is saved and listed.
    - (s) **Timeline (DoD 7):** synthetic events through the API on seed projects of two clusters: a launch `2020-06` (stated in source, with URL evidence through `POST /api/evidence/capture`), a launch `2022` on another project (straddles the invasion), an expansion `2023-03-15`, a `first_archived` `2021-05-14` → `/timeline` draws the three period bands with their labels and the cut-off labels 29.08.2019 and 24.02.2022; the `2020-06` launch is a bar, the expansion a circle, the archive event a triangle; project A's lane shows the portfolio band of (r); the `2020-06` launch has no dashed outline while the events without evidence have one, and the caption's "without evidence" count equals their number; the event-type filter `launch` hides the expansion; **Export SVG** → the file contains both cut-off dates, the band labels, the data revision and the `data-event-id` of every shown event, and a second export of the same view is byte-identical; **Export PNG** → a PNG whose width is twice the SVG's.
    - (t) **Dashboard (DoD 7):** with the data of (r) and (s) and the default controls (projects, launch basis, in paper scope): the periods panel counts the `2020-06` project under "Ministry, before the full-scale invasion" and the `2022` project under "Unknown" with the reason "imprecise date"; the basis **Portfolio entry** moves project A to "Full-scale war"; a project crosstab cell and an events crosstab cell each open their table with exactly that many rows; the events-by-period crosstab counts the two expansions of (r) and (s) under "Full-scale war"; the check "events without evidence" opens the events table with exactly as many rows as it counts.
    - (u) **Exports (DoD 7):** the dataset download is a ZIP whose files all match `SHA256SUMS` (hashes computed in the test), whose manifest shows 20 projects and the data revision of `/api/stats`, and whose `dataset.json` holds no document text; after including one synthetic document with an anchored evidence row, the QDA download holds its text file and a `codings.csv` row whose offsets slice that file (after the BOM) to the quote; the codebook Markdown contains the heading of every vocabulary (e.g. "Paper cluster") and the CSV starts with its header row.
