# Frontend (UI)

> **Status:** v1 contract for Phase 1, revised 2026-10-28 after a five-lens contract review.
> **Stack:** React + TypeScript (strict) + Vite (base `/`), Mantine, TanStack Router, Query and Table, jsdiff, DOMPurify, dayjs, @tabler/icons-react.
> **Character:** English UI, sober, information-dense and readable; it is a research tool.
> **Related:** `docs/API.md` (all data comes from there), `PLAN.md` §7 (wireframes).

## 1. Principles

### 1.1 Driven by metadata

Tables, filters, forms and detail pages are generated from `GET /api/meta` (field specs, groups, quick filters, default sorts). There are no hard-coded field lists, except for layout preferences such as the order of groups.

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
- **Canonical query string:** saved views store the sorted query string without `?`, and are applied by navigating with `Object.fromEntries(new URLSearchParams(view.query))`.
- **Quick filters:** a chip or toggle is active if its parsed key/value pairs are present in the decoded search.
- **Query keys:**
  - the list key uses the canonical string without `cols` and without detail-page parameters;
  - facet keys also omit `f.<field>`, `page`, `page_size` and `sort`.

### 1.3 No silent overwrite

Every write sends `expected_version`. Edit forms work against a frozen base (§4.1). A 409 never leads to an automatic retry.

### 1.4 Safe rendering

- Document texts and all field values are rendered as text.
- URLs are rendered as links only if their scheme is `http` or `https` (anything else is shown as plain text), with `rel="noopener noreferrer"` and `target="_blank"`.
- The only HTML injected is the server-sanitised comment `body_html`, passed through DOMPurify again (`dangerouslySetInnerHTML` only in `CommentBody`).
- Search highlights and snippets are React elements.
- `index.html` has no inline scripts; the colour scheme is fixed to light (no `ColorSchemeScript`).

### 1.5 Attribution, not authentication

- On first visit an author modal asks for a name: a quick pick from `meta.team_members` or free text, with recently used names remembered. Reserved names are refused client-side as well (API §1.1).
- The name is stored in `localStorage["mdt.author"]` and sent on every write as `X-Author: encodeURIComponent(name)`.
- Write buttons stay disabled until a name is set.
- The header shows the name; clicking it changes the name.

### 1.6 Development

The Vite dev server proxies `/api` to `http://127.0.0.1:8000` with `changeOrigin: false`, so the backend's same-origin check passes.

## 2. Routes

| Route | Page |
|---|---|
| `/` | **Overview:** counts per entity type from `/api/stats` (total, unverified), open comments, links. The dashboard proper comes in Phase 3. |
| `/projects`, `/services`, `/events`, `/documents`, `/organizations` | `EntityTablePage` |
| `/projects/$id` (likewise for the other four) | `EntityDetailPage`; search params `tab=details\|history`, `comments=open`, `thread=<id>`, `edit=1` |
| `/changes` | `RecentChangesPage` |
| `/comments` | `CommentsPage` |
| `/trash` | `TrashPage` (`type=` tab param) |
| `/codebook` | `CodebookPage` (`vocabulary=` and `term=` params) |

Review inbox, collector runs, timeline, dashboard and releases come in later phases. They are **not** shown in the navigation before then.

**Header:**
- app name "MDT Portfolio";
- navigation (Overview, Projects, Services, Events, Documents, Organizations, Changes, Comments, Codebook, Trash);
- global search box: a popover with the first 5 hits per table type (`GET /api/entities/{type}?q=…&page_size=5`) and "show all" links to `/<type>s?q=…`;
- author menu.

## 3. EntityTablePage

**Toolbar:**
- title with total count;
- search input (`q`, debounced 300 ms);
- quick filters from `meta.quick_filters`:
  - `toggle` → a chip that adds or removes its query pair;
  - `chips` (period) → a segmented multi-select over the period codes, writing `f.period=in:…`;
  - `preset` (events, documents) → mutually exclusive date presets;
- **Saved views** menu:
  - list of `saved_view` entities with `f.entity_type=in:<type>`, applied by navigation (§1.2);
  - "Save current view…" with name and description;
  - delete with confirmation (soft delete);
- **Columns** menu (checkboxes over the type's fields; stored in `cols`; default = `in_list` fields);
- **Export** menu (CSV, XLSX → `/api/entities/{type}/export?format=…&<current query>`);
- "+ New" opens a create modal (required fields + common optional ones; a project needs a `scope_note`; services and events can be created with a pre-filled parent or subject);
- link to the trash.

**Table:**
- TanStack Table in manual mode: sorting, pagination and filtering are server-side. Sticky header, compact rows (`size="xs"`), row click opens the detail page, middle-click or ctrl-click opens a new tab.
- **Header cell:**
  - label with help tooltip;
  - sort indicator for sortable fields: click cycles asc → desc → none; shift-click adds a secondary sort (max 3);
  - filter button with an active-state dot.
- **Filter popover by filter kind:**
  - `text`: operator (contains, equals, empty or not empty) and input;
  - `multiselect`: checkbox list of values with counts from `/facets` (loaded when opened), including "(empty)"; operators in / not in for single values, any / all / none for list fields;
  - `date_range`: from and to (`YYYY-MM-DD`), mode overlaps or within, "empty" toggle;
  - `bool`: segmented yes, no, any;
  - `number_range`: min and max;
  - `ref`: async search select of the referenced type(s) (multi).
- **Cells by type:**
  - `vocab`: label as a small badge (code in tooltip);
  - `vocab_list`: badges, at most 3 plus "+n";
  - `ref`: link with label, struck through if deleted;
  - `partial_date`: canonical string plus precision hint (`2020-06 · month`);
  - derived values: italic with a "derived" tooltip showing basis, reason and the deciding event; `existed_by` shown as `≤ 2021-05-14`;
  - `bool`: check icon;
  - `url_list`: count plus the first host;
  - `verification_status`: coloured dot (grey unverified, green verified, red disputed);
  - `open_comments`: speech-bubble icon with count;
  - documents with `q`: the `search_snippet` under the title.
- **Selection:**
  - checkbox column and select-all on the page;
  - **Bulk edit** (modal: field from `bulk_editable` fields, operation set / add / remove for lists, value, note; a scope change asks for a `scope_note`; setting verified or disputed asks for a note) → `POST bulk` → summary per status (updated, unchanged, conflict, deleted, error) with links to the failed rows, then refetch;
  - **Mark verified** (bulk set of `verification_status`, note required).
- **Footer:** pagination (page numbers, first and last), page size 25 / 50 / 100 / 200, total.
- **Empty states** explain the active filters and offer "Clear filters".

## 4. EntityDetailPage

**Header:**
- breadcrumb (type → label);
- badges: `verification_status`, project cluster, `in_paper_scope`, "deleted", version `vN`;
- actions:
  - **Edit**;
  - **Delete** (confirm with note; on `409 has_dependents`, ask about cascade);
  - **Undelete** (offers cascade when the deletion was a cascade);
  - **Copy link**.
- A deleted entity is shown read-only with a banner and an Undelete button.

**Tabs:**

### 4.1 Details

Field groups in the order `meta.groups` (Basics · Classification · Wartime · Framework D1–D4 · Sources & Evidence; System collapsed).

**Field row:**
- label with help tooltip;
- value;
- **provenance badge** (`seed` / `manual` / `import` / `collector`; tooltip shows `src`, `by`, `at` and, if present, `restored_from_version`);
- **lock icon** if `locked`;
- **verification dot**, with a menu:
  - **Verified:** choose one of the field's evidence rows (`GET /api/entities/evidence?f.subject_id=in:<id>&f.target=eq:field:<name>`), or "Add evidence…" first;
  - **Disputed:** note required;
  - **Unverified.**
  The choice is sent as `POST verify-field`.
- **"Add evidence…"** opens a small form that posts to `/api/entities/evidence`: URL, retrieved at (default now), verbatim quote, locator, note. It sets `subject_id` and `target = field:<name>`.
- **comment-on-field** icon with the number of open field comments.

**Derived values** appear in the Wartime group with an explanation: basis, reason code in words, and links to the deciding event or participation.

**Edit mode** (`edit=1`):
- **Frozen base:** entering edit mode freezes `base = structuredClone(item.fields)` and `baseVersion = item.version`, outside the query cache. The diff and `expected_version` always use this base, never newer query data. If a refetch shows a newer version, a banner says "Changed by <updated_by> at <updated_at> since you started editing".
- **Inline form** for all editable fields:

| Field type | Input |
|---|---|
| `string` | TextInput |
| `text` | autosize Textarea |
| `slug` | TextInput with pattern hint |
| `vocab` | searchable Select (label + code; inactive codes hidden unless current) |
| `vocab_list` | MultiSelect that keeps the order; the first value is marked "main" |
| `bool` | Switch |
| `url_list`, `string_list` | TagsInput or one item per line |
| `alias_list` | small table editor: text, language, case-sensitive, kind, exclude patterns |
| `partial_date` | TextInput with live validation and the hint "YYYY · YYYY-Qn · YYYY-MM · YYYY-MM-DD" |
| `ref` | async search select |
| `number` | NumberInput |
| `datetime` (editable ones only) | date-time input in UTC |

- **Sticky save bar:** optional change note (required where a rule demands it: changing `in_paper_scope` asks for a new `scope_note`; setting `verification_status` to verified or disputed asks for a note) and Save / Cancel. Only fields that differ from the base are sent. Unsaved changes trigger a prompt when leaving the page.

**Conflict dialog** (on `409 conflict` with `action = patch` on a live row): a table of fields:
- **Conflicting fields:** columns *Base*, *Theirs (current)*, *Yours*, with a mandatory radio choice per field: keep theirs or apply yours.
- **Fields only you changed:** listed as "will be applied".
- **Fields only they changed:** listed as information.
- **Actions:**
  - **Apply:** set base := current and baseVersion := `current_version`, then re-PATCH with the chosen values; a further conflict shows the dialog again;
  - **Discard my changes:** reload.
- Nothing is saved without a choice.

**Other 409s** (`entity_deleted`, `invalid_state`, conflicts of delete, undelete, verify, restore, bulk or comment actions) show a dialog "Changed by <updated_by> at <updated_at>" listing `changed_since_base` where available, with **Reload** and **Cancel**. `reference_deleted` offers to open the deleted row. `unique_violation` highlights the field.

**Related panels:**

| Type | Panels |
|---|---|
| project | Services (name, kind, channels, status, launch; "+ Add service"), Events (sorted by date: type, date, basis, description; "+ Add event"), linked Documents, Participations, Relations, Indicators, Evidence (read-only lists with empty states, e.g. "Documents arrive with the collectors in Phase 2") |
| service | project, parent service and child services, Events, linked Documents (`f.links=in:<id>`), Participations, Relations, Indicators, Evidence |
| event | subject, Evidence |
| document | metadata, extracted text as plain text, links (subjects with origin and state), Evidence that cites it |
| organization | Participations |

### 4.2 History

**Revision list:** version, time, author, channel badge, note, changed-field chips.

**Diff view:**
- selecting a revision shows its diff against the previous version (`from=0` for the creation);
- "Compare" mode picks any two versions (`/diff?from=&to=`);
- old → new per field; long texts get word-level diffs (jsdiff); `meta` and `state` changes are shown separately; fields that are not recorded in an older snapshot are marked as such.

**Restore this version:**
- a confirmation modal with note → `POST restore` with `expected_version` = the current version;
- then refetch, and a success notice with the new version, any `warnings` and `skipped_fields`.

### 4.3 Comments panel

A collapsible right-hand panel that can be opened via URL `comments=open`.

**Filters:** open, resolved or all; field; "show deleted".

**Thread display:** root comment with field chip, status and author/time, replies below.

**Actions:**
- reply (not on deleted roots);
- edit; the "edited" label opens the comment's revision list with word diffs;
- resolve or reopen (root);
- delete; undelete (with "show deleted");
- a 409 on edit opens a two-way dialog (theirs vs yours, word diff) and resubmits with the current version only after confirmation.

**Composer:** Markdown textarea (max length shown) with an optional field selector. There is no client-side Markdown preview; the server returns `body_html`.

## 5. Other pages

- **RecentChangesPage:**
  - filters: author (multi, from `/api/revisions/authors`), entity type (incl. comment, vocabulary term, saved view), channel, date range, batch;
  - rows grouped by day: time, author, channel badge, entity link (type + label; comments link to their subject with `comments=open&thread=<id>`), version, changed fields, note;
  - expanding a row shows the diff (`/diff?from=v-1&to=v`, with `from=0` for creations; comment revisions use the comment diff endpoint).
- **CommentsPage:**
  - filters: status, entity type, author, text, deleted;
  - one row per thread: subject link, field, last activity, number of replies;
  - clicking opens the subject page with `comments=open&thread=<id>` (vocabulary terms open the Codebook page).
- **TrashPage:**
  - tabs for every soft-deletable type: the five table types, participation, component, relation, indicator, evidence, saved view, and comments (vocabulary terms are deactivated, not deleted);
  - deleted items with label, `deleted_at` and `deleted_by`;
  - **Undelete** with a note (and cascade where applicable).
- **CodebookPage:**
  - vocabulary list (label, number of terms, "fixed" badge);
  - terms table: code, labels, definition, active, `usage_count`, sort order, attributes such as `candidate`;
  - **Edit** (modal, generic PATCH of `vocabulary_term`; code and vocabulary read-only);
  - **Add term** and **Deactivate**, both disabled for fixed vocabularies and fixed codes;
  - **History** (revision list and diff);
  - **comments panel** per term.

## 6. Code structure

```
frontend/src/
  main.tsx  router.tsx  theme.ts
  api/        client.ts (fetch wrapper, ApiError, ConflictError), types.ts, queries.ts (TanStack Query hooks + keys)
  lib/        query-string.ts (filter grammar helpers), partial-date.ts, format.ts, diff.ts, author.ts, urls.ts (safe link schemes)
  components/ layout/, table/, fields/ (display + input per type), detail/, history/, comments/, conflict/, evidence/
  pages/      Overview, EntityTable, EntityDetail, RecentChanges, Comments, Trash, Codebook
```

- **Query keys:** `['meta']`, `['vocab']`, `['stats']`, `['list', type, canonicalQs]`, `['facets', type, field, facetQs]`, `['item', type, id]`, `['revisions', type, id]`, `['comments', subjectId]`, `['changes', qs]`.
- **Invalidation after a write:** item, list of the type, revisions, stats, changes (and comments where relevant). Invalidation never touches an open edit form's frozen base.

## 7. Tests

- **Vitest:**
  - round-trip of filter grammar and URL (incl. Cyrillic values, commas in text values, canonical sorting);
  - validation and formatting of partial dates;
  - building the conflict-resolution payload;
  - diff helpers;
  - author header encoding and reserved names;
  - safe link schemes.
- **Playwright E2E:**
  - **setup:** the backend serves the built frontend on a temporary database created with `mdt db upgrade` + `mdt seed`; `@playwright/test` is pinned to the preinstalled Playwright version, and Chromium comes from `/opt/pw-browsers` when present;
  - **scenarios:**
    - (a) the projects table shows 20 rows;
    - (b) filter by `paper_cluster` and sort by name and by `policy_domains` (asc and desc); the URL updates and a reload keeps the state;
    - (c) edit a field with a note → history shows author and note;
    - (d) diff and restore;
    - (e) two browser contexts edit the same field → the second sees the conflict dialog and resolves it;
    - (f) frozen base: A enters edit mode, B saves field X, A's page refetches, A saves field Y → A sees the conflict dialog and X keeps B's value;
    - (g) comment thread create, reply, resolve, delete and undelete; the "open comments" quick filter.
