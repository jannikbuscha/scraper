# Frontend (UI)

> **Status:** v1 contract for Phase 1 (2026-10-28). **Stack:** React + TypeScript (strict) + Vite, Mantine, TanStack Router, Query and Table, jsdiff, DOMPurify, dayjs, @tabler/icons-react. The UI is in English, sober, information-dense and readable; it is a research tool.
> **Related:** `docs/API.md` (all data comes from there), `PLAN.md` §7 (wireframes).

## 1. Principles

- **Driven by metadata.** Tables, filters, forms and detail pages are generated from `GET /api/meta` (field specs, groups, quick filters). There are no hard-coded field lists, except for layout preferences such as the order of groups.
- **URL holds the state.** The table's query string *is* the API query string (`f.*`, `q`, `sort`, `page`, `page_size`, `deleted`, `cols`), so links can be shared. TanStack Router is configured with plain-string search serialisation:
  - `parseSearch = s => Object.fromEntries(new URLSearchParams(s))`;
  - `stringifySearch` builds the query with `URLSearchParams`, omitting empty values.
- **No silent overwrite.** Every write sends `expected_version`. A 409 opens the conflict dialog.
- **Safe rendering.**
  - Document texts and all field values are rendered as text.
  - The only HTML injected is the server-sanitised comment `body_html`, passed through DOMPurify again (`dangerouslySetInnerHTML` only in `CommentBody`).
  - Search highlights are React elements.
- **Attribution, not authentication.** On first visit an author modal asks for a name: a quick pick from `meta.team_members` or free text, with recently used names remembered. It is stored in `localStorage["mdt.author"]` and sent on every write as `X-Author: encodeURIComponent(name)`. Write buttons stay disabled until a name is set. The header shows the name; clicking it changes the name.

## 2. Routes

| Route | Page |
|---|---|
| `/` | **Overview:** counts per entity type from `/api/stats` (total, unverified), open comments, links. The dashboard proper comes in Phase 3. |
| `/projects`, `/services`, `/events`, `/documents`, `/organizations` | `EntityTablePage` |
| `/projects/$id` (likewise for the other four) | `EntityDetailPage`; search params `tab=details\|history`, `comments=open`, `thread=<id>`, `edit=1` |
| `/changes` | `RecentChangesPage` |
| `/comments` | `CommentsPage` |
| `/trash` | `TrashPage` (`type=` tab param) |
| `/codebook` | `CodebookPage` (`vocabulary=` param) |

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
- quick-filter chips from `meta.quick_filters`; a chip is active if its `f.` parameter is in the URL, and toggling it adds or removes that parameter;
- period presets as a segmented control where defined;
- **Saved views** menu:
  - list of `saved_view` entities with `f.entity_type=in:<type>`, applied by navigating to `?<query>`;
  - "Save current view…" → `POST` with name and description;
  - delete with confirmation (soft delete);
- **Columns** menu (checkboxes over the type's fields; stored in `cols`; default = `in_list` fields);
- **Export** menu (CSV, XLSX → `/api/entities/{type}/export?format=…&<current query>`);
- "+ New" opens a create modal (required fields + common optional ones; for services and events a pre-filled parent or subject is possible);
- link to the trash.

**Table:**
- TanStack Table in manual mode: sorting, pagination and filtering are server-side. Sticky header, compact rows (`size="xs"`), row click opens the detail page, middle-click or ctrl-click opens a new tab.
- **Header cell:**
  - label with help tooltip;
  - sort indicator: click cycles asc → desc → none; shift-click adds a secondary sort (max 3);
  - filter button with an active-state dot.
- **Filter popover by filter kind:**
  - `text`: operator (contains, equals, empty or not empty) and input;
  - `multiselect`: checkbox list of values with counts from `/facets` (loaded when opened), including "(empty)"; for list fields an extra operator switch any, all, none;
  - `date_range`: from and to (`YYYY-MM-DD`), mode overlaps or within, "empty" toggle, period presets (before 29 Aug 2019; 29 Aug 2019 – 23 Feb 2022; from 24 Feb 2022) as shortcuts;
  - `bool`: segmented yes, no, any;
  - `number_range`: min and max;
  - `ref`: async search select of the referenced type(s) (multi).
- **Cells by type:**
  - `vocab`: label as a small badge (code in tooltip);
  - `vocab_list`: badges, at most 3 plus "+n";
  - `ref`: link with label, struck through if deleted;
  - `partial_date`: canonical string plus precision hint (`2020-06 · month`);
  - derived values: italic with a "derived" tooltip showing basis and reason; `existed_by` shown as `≤ 2021-05-14`;
  - `bool`: check icon;
  - `url_list`: count plus the first host;
  - `verification_status`: coloured dot (grey unverified, green verified, red disputed);
  - `open_comments`: speech-bubble icon with count.
- **Selection:**
  - checkbox column and select-all on the page;
  - toolbar with **Bulk edit** (modal: field from `bulk_editable` fields, operation set / add / remove for lists, value, note) → `POST bulk` → summary of updated, unchanged, conflict and error, then refetch;
  - **Mark verified** (bulk set of `verification_status`).
- **Footer:** pagination (page numbers, first and last), page size 25 / 50 / 100 / 200, total.
- **Empty states** explain the active filters and offer "Clear filters".

## 4. EntityDetailPage

**Header:**
- breadcrumb (type → label);
- badges: `verification_status`, project cluster, `in_paper_scope`, "deleted", version `vN`;
- actions: **Edit**, **Delete** (confirm with note; for projects with services, ask about cascade on `409 has_dependents`), **Undelete**, **Copy link**.

**Tabs:**

### 4.1 Details

Field groups in the order `meta.groups` (Basics · Classification · Wartime · Framework D1–D4 · Sources & Evidence; System collapsed).

**Field row:**
- label with help tooltip;
- value;
- **provenance badge** (`seed` / `manual` / `import` / `collector`; tooltip shows `src`, `by`, `at` and, if present, `restored_from_version`);
- **lock icon** if `locked`;
- **verification dot**; clicking it opens a menu (verified, disputed, unverified, optional note) → `POST verify-field`;
- **comment-on-field** icon with the number of open field comments.

**Derived values** appear in the Wartime group with an explanation: basis, reason code in words, and a link to the source event.

**Edit mode** (`edit=1`): inline form for all editable fields.

| Field type | Input |
|---|---|
| `string` | TextInput |
| `text` | autosize Textarea |
| `slug` | TextInput with pattern hint |
| `vocab` | searchable Select (label + code; inactive codes hidden unless current) |
| `vocab_list` | MultiSelect |
| `bool` | Switch |
| `url_list`, `string_list` | TagsInput or one item per line |
| `alias_list` | small table editor: text, language, case-sensitive, kind, exclude patterns |
| `partial_date` | TextInput with live validation and the hint "YYYY · YYYY-Qn · YYYY-MM · YYYY-MM-DD" |
| `ref` | async search select |
| `number` | NumberInput |

A sticky **save bar** has an optional change note and Save / Cancel. Only changed fields are sent (diff against the loaded item). Unsaved changes trigger a prompt when leaving the page.

**Conflict dialog** (on `409 conflict`): a table of fields:
- **Conflicting fields:** columns *Base*, *Theirs (current)*, *Yours*, with a mandatory radio choice per field: keep theirs or apply yours.
- **Fields only you changed:** listed as "will be applied".
- **Fields only they changed:** listed as information.
- Actions: **Apply** (re-PATCH with `expected_version = current_version` and the chosen values; if another conflict arises, the dialog is shown again) and **Discard my changes** (reload).
- Nothing is saved without a choice.

**Related panels:**

| Type | Panels |
|---|---|
| project | Services (name, kind, channels, status, launch; "+ Add service"), Events (sorted by date: type, date, basis, description; "+ Add event"), linked Documents, Participations, Relations, Indicators, Evidence (read-only lists with empty states, e.g. "Documents arrive with the collectors in Phase 2") |
| service | project, parent service and child services, events, evidence |
| event | subject, evidence |
| document | metadata, extracted text as plain text, links (subjects with origin and state) |
| organization | participations |

### 4.2 History

**Revision list:** version, time, author, channel badge, note, changed-field chips.

**Diff view:**
- selecting a revision shows its diff against the previous version;
- "Compare" mode picks any two versions (`/diff?from=&to=`);
- old → new per field; long texts get word-level diffs (jsdiff); `meta` and `state` changes are shown separately.

**Restore this version:** a confirmation modal with note → `POST restore` with `expected_version` = current version → refetch, and a success notice with the new version.

### 4.3 Comments panel

A collapsible right-hand panel that can be opened via URL `comments=open`.

**Filters:** open, resolved or all; field.

**Thread display:** root comment with field chip, status and author/time, replies below.

**Actions:** reply, edit (shows "edited"), resolve or reopen (root), delete.

**Composer:** Markdown textarea (max length shown) with an optional field selector. There is no client-side Markdown preview; the server returns `body_html`.

## 5. Other pages

- **RecentChangesPage:**
  - filters: author (multi, from `/api/revisions/authors`), entity type, channel, date range;
  - rows grouped by day: time, author, channel badge, entity link (type + label), version, changed fields, note;
  - expanding a row shows the diff (`/diff?from=v-1&to=v`).
- **CommentsPage:**
  - filters: status, entity type, author, text;
  - one row per thread: subject link, field, last activity, number of replies;
  - clicking opens the detail page with `comments=open&thread=<id>`.
- **TrashPage:**
  - tabs per type;
  - deleted items with label, `deleted_at` and `deleted_by`;
  - **Undelete** with a note.
- **CodebookPage:**
  - vocabulary list (label, number of terms);
  - terms table: code, labels, definition, active, `usage_count`, sort order;
  - **Edit** (modal, generic PATCH of `vocabulary_term`; code and vocabulary read-only), **Add term**, **Deactivate**, **History** (revision list and diff).

## 6. Code structure

```
frontend/src/
  main.tsx  router.tsx  theme.ts
  api/        client.ts (fetch wrapper, ApiError, ConflictError), types.ts, queries.ts (TanStack Query hooks + keys)
  lib/        query-string.ts (filter grammar helpers), partial-date.ts, format.ts, diff.ts, author.ts
  components/ layout/, table/, fields/ (display + input per type), detail/, history/, comments/, conflict/
  pages/      Overview, EntityTable, EntityDetail, RecentChanges, Comments, Trash, Codebook
```

- **Query keys:** `['meta']`, `['vocab']`, `['stats']`, `['list', type, qs]`, `['facets', type, field, qs]`, `['item', type, id]`, `['revisions', type, id]`, `['comments', subjectId]`, `['changes', qs]`.
- **Invalidation after a write:** item, list of the type, revisions, stats, changes (and comments where relevant).

## 7. Tests

- **Vitest:** round-trip of filter grammar and URL; validation and formatting of partial dates; building the conflict-resolution payload; diff helpers; author header encoding.
- **Playwright E2E:**
  - setup: the backend serves the built frontend on a temporary, seeded SQLite database; `@playwright/test` is pinned to the preinstalled Playwright version, and the Chromium path is taken from `/opt/pw-browsers` when present;
  - scenario: projects table shows 20 rows;
  - scenario: filter by `paper_cluster` and sort by name;
  - scenario: edit a field with a note → history shows author and note;
  - scenario: diff and restore;
  - scenario: two browser contexts edit the same field → the second sees the conflict dialog;
  - scenario: comment thread create, reply, resolve; the "open comments" quick filter.
