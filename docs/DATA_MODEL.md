# Data model

> **Status:** v1 contract for Phase 1, revised 2026-10-28 after a five-lens contract review, updated the same day with the clarifications of the Phase 1 build and integration, and simplified on 2026-10-29 for a single user without concurrent editing (decision D-15, `PLAN.md` §12). **Extended on 2026-10-30 with the Phase 2 contract** (data acquisition): §14 system tables, §15 reconciliation, §16 proposals, §17 imports and manual documents, §18 merging, plus the marked additions in §1–§13; revised the same day after a four-lens review. **Extended on 2026-10-31 with the Phase 3 contract** (analysis): §19 migration `0003` and the new fields, §20 evidence anchored in document texts, §21 reading, screening and coding documents, §22 analysis records (organisations, participations, components, relations, indicators), §23 exports, §24 the required backend tests, plus the additions marked "Phase 3" in §1–§18; revised the same day after a four-lens review. Implementations must follow this document. Deviations must be agreed and the document updated in the same change.
> **Related:** `PLAN.md` §4 and §6 (rationale), `docs/API.md` (HTTP interface, including the export formats of §8.8), `docs/UI.md` (frontend), `docs/CODEBOOK.md` (vocabularies and coding rules), `docs/COLLECTORS.md` (collector framework, the collectors, importer and manual documents).

## 1. Conventions

### 1.1 Identifiers, time and dates

| Topic | Rule |
|---|---|
| **IDs** | Prefixed ULIDs as text primary keys: `<prefix>_<26-char ULID>`, e.g. `prj_01JBX3…`. The prefix determines the entity type (§3). IDs are never reused or regenerated. The Phase 2 system tables use `run_` (collector run), `raw_` (raw snapshot), `prp_` (proposal), `imp_` (import run) and `mrg_` (merge log); fetch-log, run-message and observation rows have integer keys (§14). Phase 3 export bundles carry an ID `exp_<ULID>` in their manifest; no table stores them (§23.4). |
| **Timestamps** | UTC. Every timestamp comes from one helper, `utc_now()`, which writes `datetime.now(UTC)` as `YYYY-MM-DDTHH:MM:SS.ffffffZ` (the year always with four digits), and is stored as TEXT through a `UtcTimestamp` type that accepts only aware UTC datetimes or exactly this pattern. There is no `server_default` and no SQLite date function. One write unit uses a single timestamp for `updated_at`, every `field_meta[*].at` and `revision.at`. "Newest first" for revisions means `ORDER BY revision.id DESC`. |
| **Calendar dates** (type `date`) | TEXT `YYYY-MM-DD`. Publication dates are calendar dates in Europe/Kyiv. |
| **Partial dates** (type `partial_date`) | Canonical strings only: `YYYY`, `YYYY-Qn` (uppercase `Q`, n = 1–4), `YYYY-MM`, `YYYY-MM-DD`; years 1900–2100. Anything else, e.g. `2022-q1` or `2022-02-30`, is rejected. Storage: three columns `<name>_start`, `<name>_end` (inclusive, `YYYY-MM-DD`) and `<name>_precision` (`day`, `month`, `quarter`, `year`), all derived from the string. Exception: the derived `launch` keeps the launch interval over all candidates in `launch_start`/`launch_end` next to the displayed candidate (§4, §8.3). |
| **Booleans** | SQLite integer 0/1, API `true`/`false`. |
| **Soft delete** | `deleted_at`/`deleted_by` set, row kept. Default queries exclude deleted rows. |
| **Versions** | `version` starts at 1 on creation and increases by exactly 1 per revision of the row. |

### 1.2 Normalisation

These rules apply to every channel, before validation, comparison (no-op detection) and storage:

| Type | Rule |
|---|---|
| `string`, `slug` | NFC; trim; `''` → null; any C0 control character or unpaired surrogate → 400. |
| `url` | Trim; `''` → null; any whitespace, C0/C1 control character or unpaired surrogate → 400; scheme `http` or `https` (case-insensitive, stored lowercase); non-empty host; **no userinfo** (`https://a@b/` → 400); host stored IDNA-encoded (punycode: non-ASCII labels are encoded, ASCII labels keep their case; `canonical_url` lower-cases the whole host, so duplicate detection is case-insensitive); ≤ 2 000 characters. Phase 3: the query parameters `fbclid`, `gclid`, `dclid`, `msclkid`, `yclid`, `igshid` and `mc_eid` are removed (click identifiers, which can identify the person who followed a link; CLAUDE.md, collection rules). The same rule applies to URLs inside `json` fields (e.g. `source_categories[].url`) and on every channel. |
| `text` | NFC; CRLF and CR → LF; trim; `''` → null; C0 control characters other than tab and newline, and unpaired surrogates, → 400. |
| `bool`, `int`, `number` | JSON booleans only (null → 400); JSON integers within the signed 64-bit range (booleans refused); finite JSON numbers, stored as REAL. |
| `vocab`, `ref` | Trim; `''` → null. A `ref` must be a well-formed ID whose prefix is one of the field's `ref_types`. |
| `date` | Trim; `''` → null; a real calendar date written `YYYY-MM-DD`. |
| `datetime` | Trim; `''` → null; an ISO 8601 timestamp with an explicit offset (`Z` or `±HH:MM`; `T` or a space before the time; seconds and up to 9 fractional digits optional), converted to UTC and stored in the format of §1.1. Naive timestamps → 400. |
| `url_list`, `string_list`, `vocab_list` | Column `NOT NULL DEFAULT '[]'`; API null → `[]`. Elements are normalised like their scalar type; empty elements are dropped; duplicates are removed, keeping the first occurrence. **Order is significant**: the first element is the main value (CODEBOOK §2.3), and a reorder is a change. |
| `alias_list` | Items become full objects `{text, lang, case_sensitive, kind, exclude_patterns}` with defaults (`case_sensitive: true`, `kind: "name"`, `exclude_patterns: []`, normalised like `string_list`); `kind` is `name`, `inflection`, `abbreviation` or `domain`; `lang` has at most 20 characters; other keys → 400; items with an empty `text` are dropped. Duplicates are items with the same (`text`, `lang`); the first is kept. `exclude_patterns` are **literal phrases** (never regular expressions), matched on normalised text. |
| `doc_links` | Items `{subject_id, origin, state}`: `subject_id` is a project or service ID (required); `state` is `suggested`, `confirmed` or `rejected` (required); other keys than these and the read-only ones → 400. Sorted by `subject_id`; at most one link per subject. `origin` is provenance and read-only for clients: on channel `ui` a new link gets `manual` and a stored link keeps its origin, whatever the input says; `match_count`, `matched_aliases` and `snippet` from the input are ignored. Collectors create `auto` links; the seed and imports may state the origin of new links (default `manual`). A restore brings the links back exactly as recorded in the snapshot (origin and match details included). |
| `json` | Only JSON values (finite numbers, string keys; no unpaired surrogate in a key or string); compared by canonical serialisation (sorted keys); stored as given. `service.source_categories` must be a list of `{source, label, url}` objects. |

- **Unpaired surrogates** (U+D800–U+DFFF, category Cs) are not Unicode characters: JSON can encode them (`"\ud800"`), but they cannot be stored as UTF-8. Every channel refuses them in the field types above.
- **Empty** means null or `[]`; `false` and `0` are values.
- Required fields and the "at least one name" rule are checked after normalisation.
- Diffs compare normalised API values as Python objects, never as JSON text.

### 1.3 Limits

Limits are configurable, with these defaults; violations → 400 `validation_error`.
- **Lists:** list fields ≤ 200 items; `alias_list` ≤ 100 items; `exclude_patterns` ≤ 20 items of ≤ 200 characters.
- **JSON:** `json` values ≤ 64 KiB serialised, nesting depth ≤ 10.
- **Text:** comment body ≤ `MAX_COMMENT_CHARS` (10 000); revision notes ≤ 2 000 characters.
- **Requests:** request limits are in `docs/API.md` §1.4.

## 2. Entity registry

A single registry module describes every entity type and its fields. Validation, revisions, the API (filters, sorting, exports) and the frontend (via `GET /api/meta`) are all driven by it.

### 2.1 Field types

| Type | API value | Storage | Notes |
|---|---|---|---|
| `string` | string or null | TEXT | single line, max 500 characters |
| `text` | string or null | TEXT | multi-line, max 20 000 characters |
| `slug` | string or null | TEXT | `^[a-z0-9]+(-[a-z0-9]+)*$`, max 100 characters |
| `bool` | boolean | INTEGER | |
| `int` | integer or null | INTEGER | |
| `number` | number or null | REAL | |
| `url` | string or null | TEXT | absolute URL, scheme `http` or `https` only, max 2 000 characters |
| `url_list` | string[] | JSON | each element a valid `url` |
| `string_list` | string[] | JSON | each element a valid `string` |
| `vocab` | code or null | TEXT | the `vocabulary` attribute names the vocabulary |
| `vocab_list` | code[] | JSON | |
| `ref` | ID or null | TEXT | `ref_types` lists the allowed entity types (checked by ID prefix) |
| `date` | `YYYY-MM-DD` or null | TEXT | in date-range filters it acts as the interval [d, d] |
| `partial_date` | canonical string or null | 3 columns (§1.1) | the registry names the three columns |
| `datetime` | timestamp or null | TEXT (§1.1) | date-range filters compare the UTC calendar date |
| `alias_list` | object[] | JSON | §1.2 |
| `json` | any JSON | JSON | collector-filled structures |
| `doc_links` | object[] | table `document_link` | items `{subject_id, origin: "auto"\|"manual", state: "suggested"\|"confirmed"\|"rejected"}` plus read-only `matched_aliases`, `match_count`, `snippet` |

### 2.2 Field attributes

Every field in the registry has these attributes:
- `name`, `label` (English), `type`;
- `vocabulary` (for `vocab`/`vocab_list`), `ref_types` (for `ref`);
- `group`: `basics` · `classification` · `wartime` · `framework` · `sources` · `system`;
- `required`;
- `editable` (settable on channel `ui`);
- `create_only` (settable on create, rejected on PATCH and bulk, skipped by restore);
- `system` (set only by the domain layer, never by any client);
- `tracked` (part of snapshots, diffs and `field_meta`);
- `derived`, `virtual` (both read-only, computed);
- `filter`: `text` · `multiselect` · `date_range` · `bool` · `number_range` · `ref` · none;
- `sortable`, `in_list` (default table column), `bulk_editable`, `exportable` (can be a table column and an export column: every field except the virtual fields without a value per list row, i.e. the detail-only document `text` and the filter-only relation `endpoint`, and the filter-only Phase 3 reason fields `period_reason`, `trajectory_reason` and `entry_period_reason`, whose values are exported as extra columns of their derived value, `docs/API.md` §5), `help` (tooltip text from the codebook).

Meta also exposes `default` (e.g. `in_paper_scope: false`, `verification_status: "unverified"`, `screening_status: "unscreened"`, `active: true`) and `in_create` (offered in the create form). Each type lists its constraints, e.g. `{"one_of_required": ["name_en", "name_uk"]}`.

- **All stored fields are tracked**, including read-only system fields, except `seed_key`.
- **Rule:** every field with filter `multiselect` is sortable; a backend test asserts this for the whole registry.

### 2.3 Common columns of curated entities

Every curated entity table (all tables in §3) has these columns:

| Column | Type | Tracked | Notes |
|---|---|---|---|
| `id` | TEXT PK | — | prefixed ULID |
| `version` | INTEGER NOT NULL | — | the version of the latest revision (§1.1) |
| `created_at`, `created_by` | TEXT | — | `created_by` = `user` (written in the app), `seed`, `import:<file>` or `collector:<name>` |
| `updated_at`, `updated_by` | TEXT | — | |
| `deleted_at`, `deleted_by` | TEXT NULL | state | soft delete |
| `merged_into` | TEXT NULL | state | ID of the surviving entity after a merge (Phase 2, projects and services); a merge always also sets `deleted_at`, and only an unmerge clears both (§18) |
| `verification_status` | TEXT NOT NULL DEFAULT `unverified` | ✓ | record-level review status (§7); vocabulary `verification_status`; group `basics`; filter multiselect; sortable; in list |
| `notes` | TEXT NULL | ✓ | internal notes; group `sources` |
| `field_meta` | JSON NOT NULL DEFAULT `{}` | — | provenance per field (§5) |

The system columns are also registry fields (read-only, group `system`), so tables can sort, filter, show and export them (e.g. "changed since Monday", "created by the seed", trash sorted by deletion time):
- `created_at`, `updated_at`, `deleted_at`: datetime, filter `date_range`, sortable;
- `created_by`, `updated_by`, `deleted_by`: string, filter `text`, sortable;
- `version`: int, sortable.

### 2.4 Common virtual fields

Every curated type has these virtual fields. They are computed by correlated subqueries and are filterable, sortable and exportable like stored fields; `GET /api/meta` describes them like stored fields.
- **`open_comments`** (int): the number of non-deleted root comments with status `open` on the entity, field-level threads included. Filter `number_range`; sortable; in list for the five table types.
- **`comment_count`** (int): the visible comments on the entity, replies included: non-deleted comments outside deleted threads (the replies of a deleted root are hidden with their thread and not counted). Filter `number_range`; sortable.
- **`open_proposals`** (int, Phase 2; project, service, event and document only, the types proposals concern): the open proposals (§16) whose `subject_id` or `related_id` is the entity. Filter `number_range`; sortable; not in list.
- **`evidence_count`** (int, Phase 3; every curated type that can be an evidence subject, i.e. all except `evidence`, `vocabulary_term` and `saved_view`): the non-deleted evidence rows whose `subject_id` is the entity or a record merged into it (following `merged_into` repeatedly, §18; evidence stays on a merged record), whatever their target. Filter `number_range`; sortable; exportable; in list for participation, relation and indicator. It lets tables and the dashboard find records without evidence (`f.evidence_count=eq:0`).

Source observations (§14.5) are not fields: crawl times are not dates of a project, so they appear in the detail panel "Seen in sources" and on the source pages (`docs/UI.md` §8), never in tables or view exports. The dataset bundle lists them in a file of their own, marked as crawl times (Phase 3, §23.2).

## 3. Curated entities

**Legend:** **R** required · **E** editable on channel `ui` · **F** filter · **S** sortable · **L** default list column. Groups: B basics, C classification, W wartime, Fw framework, So sources. Fields marked "system" are read-only and set by the domain layer; "create-only" fields can be set on create only.

### 3.1 `project` (prefix `prj_`)

| Field | Type | Vocab / ref | R | E | Group | F | S | L |
|---|---|---|---|---|---|---|---|---|
| `slug` | slug (UNIQUE incl. deleted) | | ✓ | ✓ | B | text | ✓ | ✓ |
| `seed_key` | slug (UNIQUE, system, **untracked**; set once by the seed) | | | | system | | | |
| `name_en` | string | | ✱ | ✓ | B | text | ✓ | ✓ |
| `name_uk` | string | | ✱ | ✓ | B | text | ✓ | ✓ |
| `aliases` | alias_list | | | ✓ | B | text | | |
| `description_en`, `description_uk` | text | | | ✓ | B | text | | |
| `official_urls`, `ministry_urls` | url_list | | | ✓ | B | text | | |
| `in_paper_scope` | bool (default false) | | ✓ | ✓ | B | bool | ✓ | ✓ |
| `scope_note` | text (§7 scope rule) | | | ✓ | B | text | | |
| `status` | vocab | `status` | | ✓ | B | multiselect | ✓ | ✓ |
| `paper_cluster` | vocab | `paper_cluster` | | ✓ | C | multiselect | ✓ | ✓ |
| `unit_type` | vocab | `unit_type` | | ✓ | C | multiselect | ✓ | |
| `ministry_categories` | vocab_list | `ministry_category` | | ✓ | C | multiselect | ✓ | ✓ |
| `primary_objectives` | text | | | ✓ | C | text | | |
| `policy_domains` | vocab_list | `policy_domain` | | ✓ | C | multiselect | ✓ | ✓ |
| `beneficiaries` | vocab_list | `beneficiary` | | ✓ | C | multiselect | ✓ | |
| `development_mode` | vocab | `development_mode` | | ✓ | C | multiselect | ✓ | |
| `development_rationale` | text | | | ✓ | C | text | | |
| `wartime_relevance` | vocab | `wartime_relevance` | | ✓ | W | multiselect | ✓ | ✓ |
| `wartime_rationale` | text | | | ✓ | W | text | | |
| `d1_need`, `d1_affected_groups`, `d1_priority_link` | text | | | ✓ | Fw | text | | |
| `d2_summary`, `d3_summary`, `d4_summary` | text | | | ✓ | Fw | text | | |
| derived: `launch` | partial_date | | | | W | date_range (+ empty) | ✓ | ✓ |
| derived: `existed_by` | date | | | | W | date_range (+ empty) | ✓ | |
| derived: `period` | vocab | `period` | | | W | multiselect | ✓ | ✓ |
| derived: `war_trajectory` | vocab | `war_trajectory` | | | W | multiselect | ✓ | |
| derived: `portfolio_entry` | partial_date | | | | W | date_range (+ empty) | ✓ | |
| derived: `entry_period` (Phase 3) | vocab | `period` | | | W | multiselect | ✓ | |
| derived: `existed_before_invasion` (Phase 3; label "Shown to exist before the invasion") | bool (§8.3 item 4): true when a dated record shows that the item existed before the invasion; false means *not shown* (new in war, an imprecise date or none), never "did not exist" | | | | W | bool | ✓ | |
| derived: `period_reason`, `trajectory_reason`, `entry_period_reason` (Phase 3; filter only, not `exportable`) | vocab | `derived_reason` | | | W | multiselect | ✓ | |
| virtual: `period_unevidenced` (Phase 3) | bool: the event that decides the period, the one named by `launch_event_id` or, without a launch, by `existed_by_event_id`, has no live evidence | | | | W | bool | ✓ | |
| virtual: `derived_unevidenced` (Phase 3) | bool: a record named by the derived row's `launch_event_id`, `existed_by_event_id` or `trajectory_event_id` has no live evidence | | | | W | bool | ✓ | |
| virtual: `entry_unevidenced` (Phase 3) | bool: the participation named by `portfolio_entry_participation_id` has no live evidence | | | | W | bool | ✓ | |
| virtual: `services_new_in_war`, `services_adapted_in_war` (Phase 3) | int: the project's live services whose `war_trajectory` is `new_in_war` or `adapted_in_war` | | | | W | number_range | ✓ | |
| virtual: `adaptation_relation` (Phase 3) | bool: a live relation from the record of type `extends`, `builds_on` or `successor_of`, the structural sign of adaptation (CODEBOOK §2.5) | | | | C | bool | ✓ | |

✱ at least one of `name_en`/`name_uk` is required (after normalisation). There is no machine translation; a missing English name stays empty.

`entry_period` is the period of the portfolio entry, the alternative basis of decision D-10 (§8.3 item 7); `period` stays the default basis. The reason fields expose the derived reasons (§8.3) to filters, facets and crosstabs (e.g. `f.trajectory_reason=in:conflicting_dates`); their values are exported as `derived_period_reason`, `derived_war_trajectory_reason` and `derived_entry_period_reason` (`docs/API.md` §5). `period_unevidenced` (the period), `derived_unevidenced` (period and war trajectory) and `entry_unevidenced` (the portfolio entry) show which derived values rest on dates without a source ("traceability before completeness"); each is false when the derived row names no such record. Project values use the project's own events only (§8.2); `services_new_in_war` and `services_adapted_in_war` show wartime activity recorded on its services (decision D-16, `PLAN.md` §12).

### 3.2 `service` (prefix `svc_`)

| Field | Type | Vocab / ref | R | E | Group | F | S | L |
|---|---|---|---|---|---|---|---|---|
| `project_id` | ref (FK, ON DELETE RESTRICT) | project | ✓ | ✓ | B | ref | ✓ (label) | ✓ |
| `parent_service_id` | ref (FK) | service | | ✓ | B | ref | ✓ (label) | |
| `name_en`, `name_uk` | string | | ✱ | ✓ | B | text | ✓ | ✓ |
| `aliases` | alias_list | | | ✓ | B | text | | |
| `description_en`, `description_uk` | text | | | ✓ | B | text | | |
| `urls` | url_list | | | ✓ | B | text | | |
| `status` | vocab | `status` | | ✓ | B | multiselect | ✓ | ✓ |
| `kind` | vocab | `service_kind` | | ✓ | C | multiselect | ✓ | ✓ |
| `channels` | vocab_list | `channel` | | ✓ | C | multiselect | ✓ | ✓ |
| `source_categories` | json `[{source, label, url}]` | | | system | So | | | |
| `source_audiences` | string_list | | | ✓ | So | text | | |
| `policy_domains` | vocab_list | `policy_domain` | | ✓ | C | multiselect | ✓ | |
| `beneficiaries` | vocab_list | `beneficiary` | | ✓ | C | multiselect | ✓ | ✓ |
| `development_mode`, `development_rationale` | vocab / text | `development_mode` | | ✓ | C | multiselect / text | ✓ / — | |
| `wartime_relevance`, `wartime_rationale` | vocab / text | `wartime_relevance` | | ✓ | W | multiselect / text | ✓ / — | ✓ / — |
| `d1_need` … `d4_summary` | text | | | ✓ | Fw | text | | |
| derived: `launch`, `existed_by`, `period`, `war_trajectory`, `portfolio_entry`; Phase 3: `entry_period`, `existed_before_invasion`, the reason fields | as for project | | | | W | as for project | ✓ | `launch`, `period` |
| virtual: `project_in_paper_scope` | bool (the project's value) | | | | B | bool | ✓ | |
| virtual: `period_unevidenced`, `derived_unevidenced`, `entry_unevidenced`, `adaptation_relation` (Phase 3) | as for project | | | | W, C | bool | ✓ | |

Constraints: `parent_service_id` must belong to the same project and must not create a cycle. A service that has non-deleted child services cannot change its `project_id` (400 `validation_error` on `project_id`).

The virtual `*_in_paper_scope` fields (here and in §3.3, §3.4) use the `in_paper_scope` value of the project or service whatever its deletion state.

### 3.3 `event` (prefix `evt_`)

| Field | Type | Vocab / ref | R | E | Group | F | S | L |
|---|---|---|---|---|---|---|---|---|
| `subject_id` | ref | project, service, component, organization | ✓ | ✓ | B | ref | ✓ (label) | ✓ |
| `event_type` | vocab | `event_type` | ✓ | ✓ | B | multiselect | ✓ | ✓ |
| `date` | partial_date | | | ✓ | B | date_range (+ empty) | ✓ | ✓ |
| `date_basis` | vocab (required if `date` is set; §7) | `date_basis` | | ✓ | B | multiselect | ✓ | ✓ |
| `date_text` | string (verbatim from the source) | | | ✓ | So | text | | |
| `description_en`, `description_uk` | text | | | ✓ | B | text | | `description_en` |
| virtual: `subject_in_paper_scope` | bool: the subject is an in-scope project or a service of one | | | | B | bool | ✓ | |
| derived: `period` (Phase 3, computed, §8.4) | vocab: the period of the event's `date` | `period` | | | B | multiselect | ✓ | |

### 3.4 `document` (prefix `doc_`)

| Field | Type | Vocab / ref | R | E | Group | F | S | L |
|---|---|---|---|---|---|---|---|---|
| `title` | string (max 1 000) | | ✓ | ✓ | B | text | ✓ | ✓ |
| `title_en` | string | | | ✓ | B | text | ✓ | |
| `url` | url | | | ✓ | So | text | | |
| `canonical_url` | url (system; recomputed from `url` in the same revision; unique among non-deleted) | | | system | So | text | | |
| `publisher` | string | | | ✓ | B | text | ✓ | ✓ |
| `publisher_org_id` | ref | organization | | ✓ | B | ref | ✓ (label) | |
| `doc_type` | vocab | `doc_type` | | ✓ | B | multiselect | ✓ | ✓ |
| `language` | vocab | `language` | | ✓ | B | multiselect | ✓ | ✓ |
| `published` | partial_date | | | ✓ | B | date_range (+ empty) | ✓ | ✓ |
| `published_basis` | vocab (required if `published` is set) | `date_basis` | | ✓ | B | multiselect | ✓ | |
| `published_text` | string (verbatim) | | | ✓ | So | text | | |
| `published_at_utc` | datetime | | | system | So | date_range | ✓ | |
| `retrieved_at` | datetime: retrieval time of the current content version (required with `url` on channel ui) | | | ✓ | So | date_range | ✓ | |
| `source_record_at` | datetime (Phase 2): the timestamp a source attaches to its record of the document when that is not a publication date (thedigital.gov.ua documents: the site's `publishedAt`, `docs/COLLECTORS.md` §8.4); never copied into `published` | | | system | So | date_range | ✓ | |
| `source_id` | string: the collector key, or `manual` (Phase 3: filter multiselect over its values, labelled with the collector labels of `sources.yaml`, sortable) | | | system | So | multiselect | ✓ | |
| `external_id`, `raw_snapshot_id`, `text_hash`, `extraction_method` | string | | | system | So | | | |
| `archive_urls` | url_list | | | ✓ | So | | | |
| `license` | vocab | `license` | | ✓ | So | multiselect | ✓ | |
| `screening_status` | vocab (default `unscreened`) | `screening_status` | ✓ | ✓ | B | multiselect | ✓ | ✓ |
| `screening_reason` | vocab | `exclusion_reason` | | ✓ | B | multiselect | ✓ | |
| `screening_note` | text | | | ✓ | B | text | | |
| `links` | doc_links | | | ✓ | So | ref (by `subject_id`) | | |
| virtual: `linked_in_paper_scope` | bool: a confirmed link to an in-scope project or one of its services | | | | B | bool | ✓ | |
| virtual: `text` | text from `document_text` | | | detail only | So | full-text only | | |
| derived: `period` (Phase 3, computed, §8.4) | vocab: the period of the document's `published` date | `period` | | | B | multiselect | ✓ | |
| virtual: `citation_count` (Phase 3) | int: the live evidence rows that cite the document (`document_id`), whatever their subject and target | | | | So | number_range | ✓ | |
| virtual: `dimension_citation_count` (Phase 3) | int: those of them with a `dimension:` target, the coded passages of the document analysis; 0 = not coded yet (§21) | | | | So | number_range | ✓ | |

Normalisation of `canonical_url`: lowercase scheme and host; remove a trailing dot from the host, default ports, the fragment, `utm_*` parameters and the trailing slash (except the root path).

### 3.5 Other curated entities

**`organization`** (prefix `org_`) has a table view in Phase 1:

| Field | Type | Vocab / ref | R | E | Group | F | S | L |
|---|---|---|---|---|---|---|---|---|
| `slug` | slug (UNIQUE incl. deleted; NULLs allowed) | | | ✓ | B | text | ✓ | ✓ |
| `seed_key` | slug (UNIQUE, system, untracked) | | | | system | | | |
| `name_en`, `name_uk` | string | | ✱ | ✓ | B | text | ✓ | ✓ |
| `aliases` | alias_list | | | ✓ | B | text | | |
| `org_type` | vocab | `org_type` | | ✓ | C | multiselect | ✓ | ✓ |
| `country` | string (ISO 3166-1 alpha-2, uppercase) | | | ✓ | B | text | ✓ | ✓ |
| `urls` | url_list | | | ✓ | B | text | | |
| `description` | text | | | ✓ | B | text | | |

The focal organisation is the row whose `seed_key` equals `FOCAL_ORG_SEED_KEY` (default `ministry-of-digital-transformation`); renaming its slug does not change that.

**The other types** have the generic API only in Phase 1. F, S and L follow the field types: string and text fields text/S (except `saved_view.query`: text, not sortable); URLs text; vocab multiselect/S; refs ref/S (label); partial dates and datetimes date_range/S; ints and numbers number_range/S; bools bool/S; json none.

| Table (prefix) | Fields (type) | Notes |
|---|---|---|
| `participation` (`par_`) | `organization_id` (ref organization, R, L), `subject_id` (ref project/service/component, R, L), `role` (vocab `participation_role`, R, L), `start`, `end` (partial_date, L; `end` ≥ `start`), Phase 3: `start_basis`, `end_basis` (vocab `date_basis`, required when the date is set, never `archive_upper_bound`), `period_text` (string, verbatim from the source), derived `period` (computed from `start`, §8.4), `description` (text) | for D3 (§22.2) |
| `component` (`cmp_`) | `name_en`/`name_uk` (✱, L), `aliases`, `component_type` (vocab `component_type`, L), `description` (text), `urls` (url_list) | for D2 (§22.3) |
| `relation` (`rel_`) | `from_id`, `to_id` (ref project/service/component, R, L, distinct), `relation_type` (vocab `relation_type`, R, L), `description` (text), virtual `endpoint` (ref, filter only: matches `from_id` OR `to_id`) | read as "from — type — to" |
| `indicator` (`ind_`) | `subject_id` (ref project/service/component/organization, R, L), `metric` (string, R, L), `value` (number, R, L), `unit` (string, L), `as_of` (partial_date, L), Phase 3: `as_of_basis` (vocab `date_basis`, required when `as_of` is set, never `archive_upper_bound`), `value_text` (string, the value verbatim as the source states it, e.g. with a qualifier such as "more than N"), `description` (text) | §22.5 |
| `evidence` (`evd_`) | `subject_id` (ref project, service, event, document, organization, participation, component, relation or indicator, R, **create-only**, L; until Phase 3 any curated type except evidence, §2.4), `target` (string, R, create-only, L: `entity` \| `field:<field name of the subject type>` \| `dimension:D1`…`D4`), `document_id` (ref document, L), `url`, `archive_url` (url), `retrieved_at` (datetime; required when `document_id` is null; editable; a URL citation without it gets the current time on channel ui; **Phase 3:** a document citation takes it, and `raw_snapshot_id`, from the document's current text version at creation, on every channel, and a given value → 400, §7), `raw_snapshot_id`, `text_hash` (string, system), `char_start`, `char_end` (int ≥ 0; `char_end` ≥ `char_start`; **system from Phase 3**: set only with an anchor, by capture, a document citation whose quote is found once, restore or an accepted proposal, §20), `quote` (text ≤ 1 000), `locator` (string), `description` (text), Phase 3: `codes` (vocab_list `analysis_code`, group framework, multiselect; only with a `dimension:` target, §20.5), `value_snapshot` (json, system: the target field's value when the evidence was created; null unless `target` names a stored field); Phase 3 read-only fields: virtual `subject_current_id` (ref, filter ref: the subject, followed along `merged_into` to its survivor, §18), virtual `dimension` (vocab `dimension`, multiselect: `dn` for a `dimension:Dn` target, else empty), virtual `case_id` (ref project/service, filter ref: the case the evidence concerns, §20.5), derived `document_period` and `case_period` (vocab `period`, multiselect, §8.4) | `document_id` or `url` is required; evidence with a `text_hash` is **anchored** in a document text version (§20) |
| `vocabulary_term` (`voc_`) | `vocabulary` (string, R, **create-only**), `code` (`^[a-z0-9_]+$`, at most 100 characters, R, **create-only**), `label_en` (string, R), `label_uk` (string), `definition`, `include_note`, `exclude_note`, `examples` (text), `sort_order` (int), `active` (bool, default true), `replaced_by` (string code; §7), `attributes` (json object) | UNIQUE (`vocabulary`, `code`); the vocabulary must exist; terms are never deleted (§7) |
| `saved_view` (`view_`) | `name` (string, R), `entity_type` (string, R, one of the table entity types), `query` (string ≤ 8 192 characters, R; canonical URL query string without `?`, a leading `?` → 400), `description` (text) | offered in the Saved views menu of its table (UI §3) |

The UI tables in Phase 1 cover project, service, event, document and organization. Vocabulary terms are edited on the Codebook page. The other types already have the generic API, and each record of them has the generic record page (`/records/<id>`, UI §2): its fields, edit, delete and undelete, history with compare and restore, and comments, so evidence created in the UI can be corrected or withdrawn there; tables and create forms for them come in Phase 3.

**Phase 3:** component, participation, relation, indicator and evidence become **table types** too (ten table types in all; `TABLE_TYPES` in the registry, UI §9.1), with tables, saved views, bulk edits and view exports; only saved views remain on the generic record page. The importer stays limited to the five Phase 1 table types (§17.1), and the default `types` of `GET /api/lookup` become those five plus `component` (API §3.1).

## 4. System tables

| Table | Columns | Rules |
|---|---|---|
| `vocabulary` | `name` PK, `label`, `description`, `multi`, `fixed_codes` (bool), `source_file` | Metadata loaded from `codebook/*.yaml` by the seed. It changes only through the YAML files, which are versioned in git; the terms themselves are revisioned in the database. |
| `revision` | `id` INTEGER PK AUTOINCREMENT, `entity_type`, `entity_id`, `version`, `at`, `author`, `channel` (`seed`, `ui`, `collector`, `import`, `restore`, `merge`, `system`), `action` (`create`, `update`, `verify`, `delete`, `undelete`, `restore`, `merge`, `unmerge`, `resolve`, `reopen`), `note` (≤ 2 000), `run_id`, `proposal_id`, `restored_from` (revision id), `restored_from_version`, `batch_id`, `schema_revision` (Alembic head at write time), `snapshot` (JSON), `diff` (JSON) | UNIQUE (`entity_id`, `version`). **Append-only:** SQLite triggers abort every UPDATE and DELETE (`RAISE(ABORT, 'revision is append-only')`); see §11 for migrations. |
| `comment` (`cmt_`) | `id`, `subject_id`, `field`, `parent_id`, `body_md`, `status`, `resolved_by`, `resolved_at`, `version`, `created_*`, `updated_*`, `deleted_*` | rules in §6.6 |
| `document_text` | `text_hash` PK (sha256 of the normalised text), `text`, `char_count`, `created_at` | immutable |
| `document_link` | `id`, `document_id` FK, `subject_id`, `origin`, `state`, `matched_aliases` (JSON), `match_count`, `snippet` | UNIQUE (`document_id`, `subject_id`); managed through the document's `links` field and part of its snapshot |
| `derived` | `entity_id` PK, `launch_start`, `launch_end` (the launch interval, §8), `launch_value`, `launch_precision`, `launch_basis`, `launch_event_id` (the displayed candidate), `existed_by`, `existed_by_event_id`, `existed_before_invasion` (bool), `period`, `period_reason`, `war_trajectory`, `trajectory_reason`, `trajectory_event_id`, `portfolio_entry_start`, `portfolio_entry_end`, `portfolio_entry_value`, `portfolio_entry_precision`, `portfolio_entry_participation_id`, Phase 3: `portfolio_entry_basis`, `entry_period` (NOT NULL, default `unknown`), `entry_period_reason` (default `no_date`); `computed_at` | one row per project and service, deleted or not; never edited directly (§8) |
| `search_key` | `rowid` INTEGER PK, `entity_id` TEXT NOT NULL UNIQUE, `entity_type` TEXT NOT NULL | stable integer keys for the FTS tables |
| `fts_entity` | FTS5 (`body`), `rowid` = `search_key.rowid`, `tokenize = "unicode61 remove_diacritics 2"`, `prefix = '2 3 4'` | maintained by the domain layer (§10) |
| `fts_document` | FTS5 (`title`, `body`), `rowid` = `search_key.rowid`, same tokenizer | |
| `app_state` | `key` PK, `value` | e.g. the hash of `codebook/parameters.yaml` and of the modification event types, used to trigger recomputes (§8) |

Phase 2 adds `raw_snapshot`, `collector_run`, `fetch_log`, `run_message`, `source_observation`, `proposal`, `merge_log` and `import_run` (§14) in migration `0002` (§11); Phase 3 adds no system table (exports are built on request, §23.4); Phase 4 adds `release`.

## 5. Field provenance (`field_meta`)

`field_meta` is a JSON object keyed by field name. There is one entry per tracked field that has ever been set:

```json
{"name_en": {"src": "seed", "by": "seed", "at": "2026-10-28T17:00:00.000000Z", "locked": true, "verified": "unverified", "evidence_id": null, "restored_from_version": null, "raw_snapshot_ids": null}}
```

| Channel | `src` | `by` | `locked` |
|---|---|---|---|
| `ui` | `manual` | `user` | true |
| `ui`, accepting a proposal (Phase 2, §16.4) | `collector:<name>@<run_id>` of the proposal for values observed in a source and taken unchanged; `manual` for edited values, add-only list results, values the person adds and suggested interpretations | `user` | true |
| `seed` | `seed` | `seed` | true |
| `import` (Phase 2, §17.1) | `import:<file>` | `import:<file>` | true |
| `collector` (Phase 2, §15) | `collector:<name>@<run_id>` | `collector:<name>` | false. `apply_change` refuses a change to a locked field (`LockedFieldError`), except system fields (§15.5) and appending suggested links (§15.8); the reconciler decides before it writes, so runs never hit the error (§15.11) |
| `restore` | `src` of the restored snapshot's entry, or `manual` if it has none | `user` | true |
| `merge` (Phase 2, §18) | `manual` (a value the person chose from the merged record; entries are never copied) | `user` | true |
| `system` | mirrors the source field (e.g. `canonical_url` mirrors `url`) | as the source field | as the source field |

- **One user (D-15):** every write through the app is recorded with `by = user`; entries written before that decision may still read `src = manual:<name>` and count as `manual`.
- **`raw_snapshot_ids`** (Phase 2): the raw snapshots (§14.1) the value was parsed from, so every collected value can be traced to a URL and a retrieval time. Set on channel `collector` from the candidate (§15.1) and, when a proposal's observed value is accepted, from the proposal (§16.4); null on every other channel and in entries written before Phase 2. Like every key except `at` it appears in meta diffs (§6.3).
- **Entries are never removed.** Clearing a field (setting it to empty) writes an entry like any other change, so a cleared value stays protected.
- **Exception on create:** fields that are empty on create get no entry.
- **Value changes** set `verified = "unverified"`, `evidence_id = null`, `restored_from_version = null` (a restore then sets it) and `raw_snapshot_ids` as stated above.
- **Restore** sets `verified = "unverified"`, `evidence_id = null`, `restored_from_version = <version>`. A restored value must be verified again.
- **Field verification** (§6.4) sets `verified` and, for `verified`, `evidence_id`; it also sets `locked = true`.
- **`evidence_id` write path:** it is written only by field verification. The evidence rows that target a field (`target = field:<name>`) are its full evidence list.
- **Invariant:** a `verified` entry always names a non-deleted evidence row of the same record with `target = field:<name>` and a verbatim `quote`. Verification checks it (§6.4), deleting that evidence row or clearing its quote is refused (§6.4 soft delete, §7 evidence), and `mdt check` reports violations (§13).

## 6. Writes

### 6.1 Transactions and connections

1. **Driver mode:** the SQLite driver never begins transactions implicitly. The connect hook sets `isolation_level = None`, executes `PRAGMA foreign_keys=ON; PRAGMA busy_timeout=10000; PRAGMA synchronous=NORMAL`, and registers the SQL functions `mdt_fold` and `mdt_sortkey` (§10). File databases are switched to `journal_mode=WAL` on every connection (the mode is persistent; `mdt db upgrade` sets it first) and use SQLAlchemy's default connection pool. A write unit that still finds the database locked after `busy_timeout` (e.g. while a long CLI command holds the lock) is rolled back and fails with `500 internal_error`; long maintenance work therefore commits in small batches (`mdt reindex`, §10).
2. **Write transactions:** every write unit starts with `BEGIN IMMEDIATE` before it reads the row. Write units are: `apply_change`, delete, undelete, restore, field verification, each bulk item, each comment action, each seeded entity. Inside the transaction it re-reads the row and runs the lock and validation checks on it. Read-only requests use plain `BEGIN`. Write units do not nest: opening one inside another raises an error instead of committing the outer unit early.
3. **Version counter:** the row update sets `version` to the version read inside the write unit plus 1, and the revision gets the same number (`UNIQUE (entity_id, version)`, §4). There is no version check against the client (§6.5).
4. **JSON columns are never modified in place.** The write path builds a new value (deep copy, change, assign) or calls `flag_modified`. JSON is serialised with `ensure_ascii=False`; nullable JSON columns use `none_as_null=True`.
5. **FastAPI handlers that use the database are plain `def`** (thread pool), never `async def` with a synchronous session.
6. **Required tests:**
   - two writes to the same row at the same time are serialised: both succeed, one after the other, with consecutive versions;
   - after every write action, reloading the row in a new session gives fields and `field_meta` equal to the latest revision snapshot.

### 6.2 One write path

**Channels:**
- Every HTTP write uses channel `ui`; the restore endpoints use channel `restore` and the merge and unmerge endpoints channel `merge` (Phase 2, §18). All three record the fixed actor name `user` (`USER_NAME` in `mdt.domain.actor`): the app has one user and asks for no name (D-15). No header, query parameter or body field can select a channel, an author or a `src`.
- The channels `seed`, `collector`, `import` and `system` are reachable only from the CLI and in-process jobs: collector runs (also those started from the UI, which run in the server's background worker, `docs/COLLECTORS.md` §6) and imports (started from the UI, executed by the server on channel `import`, §17.1).
- **Revision links (Phase 2):** a write on channel `collector` sets `revision.run_id`; a write that accepts a proposal sets `revision.proposal_id` (§16.4); imports set `revision.batch_id` to the import run's ID; merges share one `batch_id` (§18).

Every create or update of a curated entity (including comments, vocabulary terms and saved views) goes through `apply_change`; the other actions of §6.4 (and the seed) use the same machinery of `mdt.domain.writes`: write unit, normalisation and validation, the `version` bump, `field_meta`, a revision with a full snapshot, FTS and derived refresh.

`apply_change(session, entity_type, entity_id | None, changes, actor, *, note=None, batch_id=None, field_snapshots=None) -> ChangeResult`

`field_snapshots` (Phase 2) maps fields to the raw snapshots their values were parsed from; it fills `field_meta[*].raw_snapshot_ids` (§5) on channel `collector` and for observed values accepted from a proposal.

The channel, the collector run and the import file travel in the actor: `Actor(name, channel, run_id=None, file=None, proposal_id=None, proposal_src=None)`, built with `Actor.ui()`, `Actor.restore()`, `Actor.seed()`, `Actor.importer(file)`, `Actor.collector(name, run_id)`, `Actor.system()` and, in Phase 2, `Actor.accept(proposal_id, proposal_src)` (channel `ui`; values listed as taken unchanged get `src = proposal_src`, §16.4) and `Actor.merge()` (channel `merge`, for merge and unmerge). The name is `user` for `ui`, `restore` and `merge`, otherwise `seed`, `import:<file>`, `collector:<name>` or `system`. `insert_revision` writes `actor.run_id` and `actor.proposal_id` into the revision.

1. **Normalise and validate** (§1.2, §7):
   - field names must exist and be writable on this channel: `editable` for `ui`; `create_only` fields only on create; `system` fields never from clients;
   - types, vocabulary codes, references, uniqueness and entity-specific rules.
2. **Create** (`entity_id` is None):
   - new ID, `version = 1`, `created_*` and `updated_*` set;
   - a `field_meta` entry for every provided non-empty tracked field (and for non-empty values the domain layer sets on create, e.g. an evidence row's `value_snapshot`);
   - system fields computed (e.g. `canonical_url`);
   - for project and service, the `derived` row is inserted;
   - revision version 1 with `diff = {"fields": {f: [null, value]}}` for the non-empty fields.
3. **Update:**
   - **Deleted rows:** a deleted row → 409 `entity_deleted`.
   - **Diff:** compare normalised values per field against the row as read inside the write unit. If nothing differs → **no-op**: no revision, no version bump, `changed = false`.
   - **Write:** apply the values, recompute dependent system fields in the same revision (`canonical_url` follows `url`; its `field_meta` mirrors `url`'s entry), bump `version` (§6.1), set `updated_*`, update `field_meta` (§5), write the revision.
4. **In the same transaction:** refresh the FTS rows (§10) and recompute derived values where §8 requires it.

### 6.3 Snapshot and diff format

Revision `snapshot` (the full state after the change):

```json
{
  "fields": {"slug": "diia", "name_en": "Diia"},
  "field_meta": {"name_en": {"src": "seed", "...": "..."}},
  "state": {"deleted_at": null, "deleted_by": null, "merged_into": null}
}
```

`fields` contains every tracked field in API representation (partial dates as canonical strings, lists as arrays, `links` as an array of objects). Revision `diff`:

```json
{
  "fields": {"name_en": ["Old", "New"]},
  "meta": {"name_en": {"verified": ["unverified", "verified"]}},
  "state": {"deleted_at": [null, "2026-10-28T17:00:00.000000Z"]}
}
```

- Empty sections are omitted. `meta` lists, per field, the changed keys of its `field_meta` entry except `at` (which changes with every write).
- The diff between any two versions is computed from their snapshots. A field missing from one of the snapshots (older schema) is shown as *not recorded*, not as null.
- Version 0 denotes the empty state before creation. A diff from version 0 has no `meta` section (so the diff 0 → 1 equals the stored create diff), but it has a `state` section, so comparing 0 with a deleted version shows the deletion.
- `changed_fields` of a revision = keys of `diff.fields` ∪ keys of `diff.meta` ∪ `deleted` if `diff.state` changes.

### 6.4 Other write actions

All of these run as write units (§6.1) and create a revision, except no-ops: a field verification that sets the status (and evidence) already recorded and a restore whose fields all equal the current values write nothing (`changed = false`; the API returns `revision_id: null`), and resolve/reopen are idempotent (§6.6). This keeps empty revisions out of the history.

| Action | Semantics |
|---|---|
| **Field verification** | `set_field_verification(entity, field, status, actor, note, evidence_id)`. The field must be tracked, non-system and non-empty (`verification_status` itself cannot be field-verified). `verified` requires `evidence_id` of a non-deleted evidence row with the same `subject_id` and `target = field:<name>` that quotes the source verbatim (non-empty `quote`, CODEBOOK §2.3), else 400 `evidence_required`. `disputed` requires a note. Sets `locked = true`. The revision has a `meta` diff only. A field that has no `field_meta` entry yet (e.g. a default value) gets one with `src = manual`. |
| **Soft delete** | `soft_delete(entity, actor, note, cascade=False)`. A project with non-deleted services, or a service with non-deleted descendant services (child services at any depth), raises `HasDependentsError` (counts `{"service": n}`) unless `cascade=True`. An evidence row that a field verification rests on (its subject's `field_meta[<target field>]` has `verified = "verified"` and this `evidence_id`, whatever the subject's deletion state) raises `HasDependentsError` (`{"field_verification": 1}`) **also with `cascade=True`**: withdraw the verification (`unverified` or `disputed`) or verify the field with other evidence first, so a verified field never rests on evidence in the trash (§5). Every delete gets a new `batch_id`; a cascade deletes the dependents with the same `batch_id`, in **one transaction** (all or nothing). Events, comments and evidence are not deleted. Deleting a deleted row → 409 `invalid_state`. Vocabulary terms cannot be deleted (409 `not_deletable`; deactivate instead). |
| **Undelete** | Clears `deleted_*`. It re-validates uniqueness (409 `unique_violation`) and required references (409 `reference_deleted` {field, id, type, label}; comment subjects and parents may stay deleted). With `cascade=True` it also undeletes the rows whose latest revision is the delete revision with this row's delete `batch_id`, in one transaction. The undelete revisions share a new `batch_id`. Undeleting a live row → 409 `invalid_state`. A merged record (`merged_into` set, Phase 2) is not undeleted but unmerged (409 `invalid_state` `{state: "merged"}`, §18). |
| **Restore version** | `restore_version(entity, version, actor, note, fields=None, dry_run=False)`, all or nothing. Applies the tracked, editable, non-create-only fields present in that version's snapshot whose value differs, optionally limited to `fields`. `dry_run` returns `{field: [current, restored]}` without writing; the UI uses it as a preview. Fields missing from an old snapshot are left unchanged; `state` is never restored; dependent system fields are recomputed. On channel `restore`, inactive vocabulary codes are accepted and reported back in `warnings`. The scope rule (§7) applies: restoring `in_paper_scope` submits the snapshot's `scope_note` along (if it equals the current note, the current note is submitted); a `fields` list that restores `in_paper_scope` but leaves out a differing `scope_note` → 400. `skipped_fields` lists what is not restored: requested fields that are untracked or missing from the snapshot, and non-restorable fields (system, create-only or not editable) that differ or were requested. Errors: a requested name that is not a field of the type → 400; an unknown version → 404; 409 `unique_violation` {field, existing}; 409 `reference_deleted` {field, id, type, label}; any other validation error → 400. Not allowed on a deleted entity (409 `entity_deleted`; undelete first). Phase 2, documents: the text version (§15.6) is one unit: restoring `retrieved_at` from a version with another `text_hash` also restores `text_hash`, `raw_snapshot_id` and `extraction_method` (listed in `changes`, not in `skipped_fields`), and they are never restored without it. Phase 3, anchored evidence: the anchor is one unit in the same way (§20.3). |
| **Accept / reject a proposal** (Phase 2) | §16.4: accepting writes through `apply_change` (or the create path) with `Actor.accept`; rejecting writes no curated data. |
| **Merge / unmerge** (Phase 2) | §18: one transaction, one `batch_id`, a revision per changed row, a `merge_log` row; unmerge reverses a merge the same way. |
| **Capture evidence** (Phase 3) | §20.2: one write unit with one `batch_id` that creates an optional record or writes optional values of the subject, then an evidence row (anchored in a text version, citing a whole document or a URL) and an optional field verification, each through the machinery above. |
| **Bulk edit** | The request names the records by `ids`; each record runs as its own write unit with a shared `batch_id`. Operations: `set` (field → value), `add` (append missing values at the end, in the given order) and `remove` (delete values) for list fields. The whole request is rejected with 400 if a field is not `bulk_editable` (except `scope_note` in `set` next to `in_paper_scope`, §7), a field appears in more than one operation, `add`/`remove` targets a non-list field, no operation is given, `ids` is empty, or an ID is duplicated. Per record, the result is `updated`, `unchanged` or `entity_deleted` (each with the record's `version`; a deleted record is not changed) or `error` (with the error object of `docs/API.md` §1.2, e.g. `not_found`). At most 500 records. |

### 6.5 Concurrency

The app has one user and does not detect conflicting edits (decision D-15): there is no optimistic locking, no `expected_version` and no conflict error.
- Write units are serialised by SQLite's write lock (`BEGIN IMMEDIATE`, §6.1). Each one applies its changes to the row as it reads it inside the unit, so of two overlapping edits of the same field the later one wins; both stay in the history and can be compared and restored.
- What protects data is not a version check but the field rules: automatic channels (seed, import, collector) never overwrite a locked field (§5, §9, §15.5, §17.1), collectors also leave records a person verified or disputed unchanged (§15.5), and every change is a revision. A collector reconciles each entity in one write unit that re-reads the row and its `field_meta` (§15.11), so a field a person locked a moment earlier becomes a proposal, never an overwrite.
- A PATCH carries only the fields the user changed (UI §4.1), so other fields written meanwhile, e.g. by a collector, are not reverted.

### 6.6 Comments

- **Written through the same write path** (`entity_type = comment`).
- **Fields:**
  - tracked: `body_md`, `status`, `resolved_by`, `resolved_at`;
  - create-only: `subject_id`, `field`, `parent_id`;
  - snapshots have `field_meta = {}` and `state = {deleted_at, deleted_by}`.
- **Subjects:** `subject_id` may reference any curated type of §3 (never a comment), deleted or not. `field` must be a registry field of the subject type other than `seed_key` (derived, virtual and system fields included).
- **Threads:** `parent_id` must be a root comment of the same subject. Replying to a deleted root → 400. A reply does not change the root's status. A reply takes the `field` of its root; a reply with a different `field` → 400.
- **Status:** roots start `open`; resolve and reopen apply to roots only (a reply → 400). Resolve sets `resolved_by`/`resolved_at`, reopen clears them. Replies have status null. Resolve and reopen are **idempotent**: if the target status is already set, they return without a revision (`changed = false`).
- **Deleting a root** hides the whole thread; the replies are not modified and reappear on undelete. Comments are undeletable and restorable to any version, like entities; a restore applies only `body_md` (the status fields are system fields).
- **`edited`** is true if any revision after version 1 changed `body_md`.
- **Body rendering:** `body_md` ≤ `MAX_COMMENT_CHARS` (default 10 000). `body_html` is rendered on every read (docs/API.md §3.3) and never stored.

## 7. Validation rules

- **Vocabulary codes:**
  - A code must exist in the field's vocabulary and be active.
  - An inactive code already stored in the field may be kept; adding an inactive code is rejected, except on channel `restore` (§6.4).
- **Fixed codes:**
  - The system vocabularies (`verification_status`, `screening_status`, `date_basis`, `date_precision`, `period`, `war_trajectory`, `derived_reason`; Phase 3 `dimension`) have `fixed_codes: true`. The `event_type` codes `launch`, `beta_launch` and `first_archived` carry `attributes.fixed = true`.
  - For these, adding or deactivating terms returns 409 `fixed_code`; labels and definitions stay editable. `attributes.fixed` itself can be changed only through the codebook files (channel `seed`); any other change of it → 409 `fixed_code`.
- **`replaced_by`:** must be an active code of the same vocabulary, different from the term's own code; allowed only when `active = false`.
- **References:** must point to an existing row of an allowed type (by ID prefix). When a value is set or changed, the row must not be deleted (otherwise 409 `reference_deleted`).
- **Events:**
  - `date_basis` is required when `date` is set;
  - `first_archived` requires `archive_upper_bound`;
  - `archive_upper_bound` is allowed only for `first_archived` (record an archive capture as a separate `first_archived` event, never as a launch);
  - documents: `published_basis` is required when `published` is set.
- **Screening** (CODEBOOK §2.8): `screening_status = excluded` requires a `screening_reason`, and a `screening_reason` is allowed only with `excluded` (400 `validation_error` on `screening_reason`). The rule is checked when either field is set or changed, on every channel; a change that moves an excluded document back to `included` or `unscreened` therefore has to clear the reason itself (nothing is cleared automatically). A bulk `set` of `screening_status = excluded` needs `screening_reason` in the same `set` (else the whole request is refused).
- **Scope:** creating a project, or changing `in_paper_scope`, requires a non-empty `scope_note` in the same change (single or bulk); otherwise 400 `validation_error`. The rule makes scope "a field of its own, with a reason" (assignment §3).
- **Record-level `verification_status`:** setting it to `verified` or `disputed` (single or bulk) requires a revision note.
- **Evidence:**
  - `target = field:<name>` must name a tracked, non-system field of the subject type;
  - `document_id` or `url` is required;
  - `retrieved_at` is required when `document_id` is null;
  - `char_start` and `char_end` must not be negative, and `char_end` ≥ `char_start`;
  - `value_snapshot` is copied from the subject at creation;
  - the `quote` of an evidence row that a field verification rests on cannot be cleared (400 `validation_error` on `quote`), so a verified field always has a verbatim quote (§6.4).
- **Other entity rules:** a relation's `from_id` and `to_id` differ; a vocabulary term's `attributes` is a JSON object; a saved view's `entity_type` is one of the table types (five in Phase 1 and 2, ten from Phase 3, §3.5); documents need `retrieved_at` whenever a `url` is set on channel `ui` (§3.4).
- **Phase 3:**
  - **Date bases of participations and indicators:** `start_basis` is required when `start` is set, `end_basis` when `end` is set, `as_of_basis` when `as_of` is set; a basis without its date → 400; `archive_upper_bound` is refused for all three (it belongs to `first_archived` events only, CODEBOOK §2.6). The rule is checked when the date or its basis is set or changed, on every channel, like the event rule above, so rows written before migration `0003` stay valid until one of the two fields is touched.
  - **Anchored evidence** (`text_hash` set): the anchoring rules of §20.1–§20.3 (offsets, quote, frozen anchor fields). Every write that sets an anchor (capture, a document citation with a quote found once, accepting a `create_event` proposal, a restore) takes `quote` from the stored text inside the write unit and checks, after normalisation, that `quote == text[char_start:char_end]` and that `text_hash` is a text version of the cited document (§21); otherwise 400. `char_start` and `char_end` are system fields, so the generic create and PATCH refuse them (they come with an anchor only).
  - **Relations:** no second live relation with the same (`from_id`, `to_id`, `relation_type`) (§22.4).
  - **Evidence codes:** `codes` is allowed only when `target` is `dimension:Dn`; the term of every code (active or not) must have `attributes.dimension = dn` (the lower-case form of the target's dimension); a code added must be active, while codes already stored may stay after their term is deactivated and a restore brings them back with the warning `inactive_code` (the general rule above); otherwise 400 `validation_error` on `codes` (§20.5).
  - **`analysis_code` terms:** `attributes.dimension` is required and must be an active code of the vocabulary `dimension`; once a term is used by an evidence row (live or deleted), its `attributes.dimension` cannot change (400 `validation_error` on `attributes`), so a coding never moves to another dimension silently and needs no separate check.
  - **Citing a document** (evidence with `document_id` and without an anchor, on every create path and channel): `retrieved_at` and `raw_snapshot_id` are taken from the document (a given `retrieved_at` → 400). If the document has a text and a `quote` is given, the quote (normalised as `text`, §1.2) must occur in the current text **exactly once**: the row is then stored as anchored evidence of that occurrence (§20.2); no occurrence or several → 400 `validation_error` on `quote` ("not found in the document text" or "occurs n times in the document text": capture the passage in the document view, or cite the URL with a locator). Afterwards, a PATCH that sets or changes the `quote` or `document_id` of unanchored evidence is refused (400) when the cited document has a text and the quote is not empty: capture the passage instead. Typed, unchecked quotes therefore exist only for documents without text and for URL citations.
  - **Client identifiers:** no value of any field on any channel may contain the configured `CONTACT_EMAIL` (case-insensitive; only when it is set and not blank), the User-Agent product token `MDT-Portfolio-Research` or the bot-manager token marker `__uzdbm` (400 `validation_error` on the field: "contains an identifier of this app's client"; collector writes report it as `write_error`), so no table, view export, figure or bundle can carry them (CLAUDE.md, collection rules; §23.3). Document texts are covered too: a text that contains one is never stored (creating a manual document from it → 400 on `snapshot_id`, `docs/API.md` §7.8; a collector candidate with it → `write_error`, nothing of it is written).
- **Partial dates and URLs:** as in §1 and §2.1. Participation `end` ≥ `start` (compared by `_start`).
- **Uniqueness:**
  - `project.slug`, `organization.slug`, `seed_key`, `vocabulary_term` (`vocabulary`, `code`) and `document_link` (`document_id`, `subject_id`) are unique including deleted rows;
  - `document.canonical_url` is unique among non-deleted rows (partial index);
  - collisions are reported as 409 `unique_violation` `{field, existing: {id, label, deleted}}` on create, PATCH, restore and undelete. They are checked explicitly inside the write transaction, with `IntegrityError` mapped to the same response as a fallback.
- **Reference errors:** `reference_deleted` details are `{field, id, type, label}`, so the UI can offer to undelete the referenced row first.
- **Lengths:** comment body ≤ `MAX_COMMENT_CHARS`; revision notes ≤ 2 000.

## 8. Derived fields

### 8.1 When derived values are computed

- **One row per entity:** every project and service has exactly one `derived` row, deleted or not, inserted when the entity is created. A new entity starts as: `period = unknown`, `period_reason = no_date`, `war_trajectory = unknown`, `trajectory_reason = no_date`, `existed_before_invasion = false` (Phase 3 also `entry_period = unknown`, `entry_period_reason = no_date`). A recompute rewrites a row, and sets `computed_at`, only when one of its values changes. The Phase 3 values follow the same triggers (a participation's `start_basis` is part of its write).
- **Recompute triggers:** the row is recomputed in the same transaction for:
  - every write to an event (create, update, delete, undelete, restore, verify, bulk), for the old and the new `subject_id`, whatever the event's state before or after;
  - every write to a participation whose old or new `organization_id` is the focal organisation (old and new subject);
  - every write to an `event_type` term, and (Phase 3) to a `participation_role` term (its `attributes.portfolio_role`, §8.3 item 6).
- **Full recomputes:** `mdt recompute` recomputes all rows. `mdt seed` and `mdt db upgrade` run it when the hash in `app_state` changes; the hash covers `codebook/parameters.yaml`, the focal organisation's ID, the set of modification event types and (Phase 3) the set of portfolio roles. Phase 3: exports refuse to run, and `GET /api/stats` reports `derived_current: false`, while the stored hash differs from the hash of the current inputs (e.g. after `parameters.yaml` was edited on a running server), because computed periods (§8.4) would then use other cut-off dates than the stored derived rows (§23.4).
- **Never dropped:** list, facet and sort queries LEFT JOIN `derived` and treat a missing row as `unknown`, so an entity never drops out of a table.

### 8.2 Inputs

- **Events:** the subject's non-deleted events whose `verification_status` is not `disputed`. A project's values use the project's own events only, not those of its services (proposed default of decision D-16, `PLAN.md` §12; the UI says so wherever it shows project values, and the project fields `services_new_in_war` and `services_adapted_in_war` show the services' trajectories, §3.1).
- **Participations:** non-deleted and not disputed.
- **Parameters:** `MINISTRY` = `ministry_founded` and `INVASION` = `full_scale_invasion` from `codebook/parameters.yaml`.
- **Archive dates:** a date with basis `archive_upper_bound` is treated as the interval [1900-01-01, date_end].

### 8.3 Rules

1. **Launch candidates:** the dated `launch` events, or, if there is none, the dated `beta_launch` events.
   - **Launch interval** = [min `date_start`, min `date_end`] over the candidates. The earliest launch provably lies in this interval.
   - **Displayed launch** (`launch_value`, `launch_precision`, `launch_basis`, `launch_event_id`) = the candidate with the smallest `date_end`; ties are broken by `date_start`, then `id`.
2. **`existed_by`:** = min `date_end` of the `first_archived` events. It is an upper bound and is displayed as "≤ date".
3. **`period`** (from the launch interval [s, e]):
   - e < MINISTRY → `pre_ministry`;
   - s ≥ MINISTRY and e < INVASION → `pre_invasion`;
   - s ≥ INVASION → `full_scale_war`;
   - otherwise `unknown` (`imprecise_date`).
   - **Without launch candidates:** `existed_by` < MINISTRY → `pre_ministry`; with only an archive bound otherwise → `unknown` (`archive_bound_only`); with no date at all → `unknown` (`no_date`).
4. **`existed_before_invasion`:** e < INVASION, or `existed_by` < INVASION.
5. **`war_trajectory`.** A modification event is an event whose type has `attributes.counts_as_modification = true`. The rules are applied in this order:
   1. s ≥ INVASION and `existed_before_invasion` → `unknown` (`conflicting_dates`; `trajectory_event_id` = the `first_archived` event that gives `existed_by`);
   2. s ≥ INVASION → `new_in_war` (`trajectory_event_id` = the launch event);
   3. `existed_before_invasion` and at least one modification event with `date_start` ≥ INVASION → `adapted_in_war` (`trajectory_event_id` = the earliest such event by `date_start`, then `id`);
   4. `existed_before_invasion` and every modification event is dated with `date_end` < INVASION, or there is none → `prewar_unchanged`, meaning "no modification on or after the invasion recorded up to the release";
   5. otherwise `unknown`, with reason `imprecise_modification_date` (an undated or straddling modification event; `trajectory_event_id` = the straddling one with the earliest `date_start`, else the undated one with the smallest `id`), `imprecise_date` (the launch interval straddles the invasion), `archive_bound_only` (the only date is an archive upper bound on or after the invasion, which does not tell new from old) or `no_date`.
6. **`portfolio_entry`:** the earliest `start` of a participation of the focal organisation in a **portfolio role**, with `portfolio_entry_participation_id`. Portfolio roles are the `participation_role` terms with `attributes.portfolio_role = true` (Phase 3; the codebook marks `initiator`, `owner` and `operator`, the rule of Phase 1 and 2; whether `coordinator` counts is part of decision D-10). Phase 3 also stores that participation's `start_basis` as `portfolio_entry_basis`. The **portfolio-entry interval** is the participation's start interval [`start_start`, `start_end`]. A service's portfolio entry comes from participations whose subject is the service; nothing is inherited from its project.
7. **`entry_period`** (Phase 3, the alternative basis of decision D-10): the period rules of item 3 applied to the portfolio-entry interval [s, e]: e < MINISTRY → `pre_ministry`; s ≥ MINISTRY and e < INVASION → `pre_invasion`; s ≥ INVASION → `full_scale_war`; otherwise `unknown` with `entry_period_reason = imprecise_date`; without a portfolio entry `unknown` with `no_date`. There is no archive fallback and no trajectory on this basis: `war_trajectory` describes how the initiative changed, which the portfolio entry does not tell (proposed default of D-10 as revised for Phase 3, `PLAN.md` §12).

The reason codes are those of the vocabulary `derived_reason` (CODEBOOK §3), including `conflicting_dates`.

### 8.4 Computed periods (Phase 3)

Events, documents and participations get a read-only field `period`, and evidence the fields `document_period` and `case_period` (registry: `derived: true`, vocabulary `period`, filter multiselect, sortable, exported with the `derived_` prefix and a `_label` column, API §5). They are **not stored**: the query layer computes them in SQL from date columns and the cut-off dates of `codebook/parameters.yaml` (bound as parameters, never interpolated), so they can never be stale (`case_period` excepted, below):
- the interval [s, e] is the event's `date` (`date_start`, `date_end`), the document's `published` or the participation's `start`; an event or document date with basis `archive_upper_bound` counts as [1900-01-01, its end], as in §8.2 (participations refuse that basis, §7);
- e < MINISTRY → `pre_ministry`; s ≥ MINISTRY and e < INVASION → `pre_invasion`; s ≥ INVASION → `full_scale_war`; an undated record or an interval that straddles a cut-off → `unknown`;
- evidence `document_period` is the `period` of the cited document (`unknown` without a document or a date); `case_period` reads the stored derived `period` (launch basis, §8.3) of the evidence's case (`case_id`, §20.5; `unknown` without a case), so it is as current as the derived values (§8.1).

They answer "in which period did this happen, appear or start", e.g. for the dashboard's crosstabs of events, participations and dimension evidence and for the QDA metadata (`docs/UI.md` §9.5, `docs/API.md` §8.8); they play no part in the derived values of projects and services. Item responses carry them in `derived` (API §2).

## 9. Seed and codebook files

**`codebook/<vocabulary>.yaml`** holds one vocabulary per file (format below). `codebook/parameters.yaml` and files without a `vocabulary` key are not vocabularies.

```yaml
vocabulary: paper_cluster
label: Paper cluster
description: Seven thematic clusters used in the paper.
multi: false
fixed_codes: false
terms:
  - code: digital_public_services_infrastructure
    label_en: "Digital public services & infrastructure"
    label_uk: null
    definition: "…"
    include_note: null
    exclude_note: null
    examples: null
    sort_order: 10
    active: true
    attributes: {}
```

**`codebook/parameters.yaml`:** `ministry_founded`, `full_scale_invasion`, `publication_timezone`, `storage_timezone`, plus a `sources` mapping. YAML dates may arrive as date objects; accept both dates and ISO strings.

**`seed/projects.yaml`:** the 19 projects of the paper plus European Integration (slug `european-integration`, `in_paper_scope: false`, no cluster; assignment §3), and the focal organisation (assignment §1).

**Rules:**
- **Only values from the assignment.**
  - Entry URLs on thedigital.gov.ua go into `ministry_urls`, external entry URLs into `official_urls`.
  - Aliases are exactly the given English and Ukrainian names (kind `name`); inflections and spellings are added later by a person (`PLAN.md` §5.3).
  - The focal organisation has only `name_en` and `name_uk`.
  - `ministry_categories` stays empty (collector C1 fills it with evidence). No Ukrainian name is invented where the assignment gives only one name.
  - The same rule applies to `codebook/*.yaml`: values marked [search] or [hypothesis] in the docs are not entered as labels.
- **`mdt seed` is idempotent and runs on every container start** (after `mdt db upgrade`). It loads vocabulary metadata and terms (matched by `vocabulary` + `code`), then the organisations and projects (matched by `seed_key`, set once from the YAML slug, including deleted rows):
  - **Missing rows** are created on channel `seed`; empty seed values are "not provided" and get no `field_meta` entry and no lock.
  - **Deleted rows** are skipped.
  - **Existing rows:** a field is updated only if the value differs and either the field has no `field_meta` entry, or its entry has `by == "seed"`, `verified == "unverified"` and `restored_from_version == null`. Otherwise the field is left as it is and reported as a *seed drift* line (entity, field, current value, seed value). Empty seed values never clear a field; a seeded change of `in_paper_scope` keeps the current `scope_note` unless the seed changes it too.
  - **Unchanged data** produces no revision; a second run creates 0 revisions. Project and organisation revisions carry the `provenance` string of `seed/projects.yaml` as their note, term revisions the note `Loaded from codebook/<file>`.
  - **Vocabulary metadata** (label, description, multi, fixed_codes, source file) is updated from YAML without revisions (it is versioned in git).
  - **Errors:** a malformed codebook or seed file stops the command with an `error:` line (exit 1); an entry that fails validation is reported, the other entries are still processed, and the command exits 1. `mdt seed --dry-run` reports what would change and writes nothing. After a real run the seed recomputes the derived values if their inputs changed (§8.1).

## 10. Full-text search, folding and sorting

- **`normalize_for_search(s)`:**
  - NFC;
  - apostrophe variants `'`, `’`, `‘`, `` ` ``, `´`, `ʹ`, `ʼ` → `ʼ` (U+02BC);
  - non-breaking and other Unicode spaces → space;
  - soft hyphen removed;
  - dash variants → `-`.
  The same function is applied to indexed text and to queries (`PLAN.md` §4.7 explains why).
- **`fold(s)`** = `normalize_for_search(s).casefold()`, registered on every connection as the deterministic SQL function `mdt_fold`. SQLite's own `lower`, `LIKE` and `NOCASE` do not fold Cyrillic.
- **`sortkey(s)`** = `fold(s)` with the 33 letters of the Ukrainian alphabet (а б в г ґ д е є ж з и і ї й к л м н о п р с т у ф х ц ч ш щ ь ю я) mapped to consecutive code points from U+E000. Registered as `mdt_sortkey`. Ukrainian text therefore sorts in alphabetical order, case-insensitively, after Latin text.
- **FTS tables:**
  - `search_key` gives every searchable entity a stable integer `rowid`; `fts_entity(body)` and `fts_document(title, body)` use that rowid and have no ID columns;
  - upsert with `INSERT OR REPLACE INTO fts_x(rowid, …)`; delete by rowid;
  - FTS rows are **kept for soft-deleted entities** (trash search works); the `deleted` parameter filters on the entity table.
- **`fts_entity.body`:** the normalised values of the entity's tracked `string`, `text`, `slug`, `string_list` and `url_list` fields and alias texts (scalar `url` fields are not indexed; for comments: `body_md`, `status` and `resolved_by`). For documents it excludes the full text.
- **`fts_document`:** `title` + `title_en` and the document text.
- **For documents, `q` matches** `fts_entity` OR `fts_document`, and list items get a `search_snippet`. It is built with FTS `snippet()` using the private-use markers U+E000/U+E001 internally, then returned as a list of segments `[{"text": "…", "hit": false}, …]`. No markup is ever sent, and Ukrainian «» quotation marks stay ordinary text.
- **Query building (`q`):**
  - normalise (`normalize_for_search`) and split into tokens (whitespace; `"…"` keeps phrases);
  - tokens without a letter or digit (e.g. `-`, `.`, `–`) are dropped; such tokens would otherwise make the whole AND expression match nothing;
  - escape double quotes;
  - every token becomes `"token"*` (prefix match), phrases stay exact;
  - tokens are joined with AND;
  - if no token remains, the query matches nothing and does not raise.
- **Ranking:** with `sort=relevance` the results are ordered by FTS5 `bm25`.
- **`mdt reindex`** rebuilds both FTS tables in batches of 200 records, each its own write unit, so the app stays usable during the rebuild: a batch holds the write lock for a fraction of a second, and concurrent writes go through (with 20 000 documents they took at most a few seconds while the index was rebuilt, instead of failing after the busy timeout). Every record's rows are replaced in place, so searches keep finding every record meanwhile; afterwards FTS rows and search keys that belong to no record are removed.

## 11. Migrations

1. **One initial revision** creates all tables, indexes, the append-only triggers and the FTS tables. Trigger and FTS DDL live as constants in `mdt/db/ddl.py`.
2. **`env.py`:**
   - `render_as_batch=True`;
   - `include_name` skips names matching `fts_%` and `sqlite_%`;
   - `PRAGMA foreign_keys=OFF` before `context.begin_transaction()` and `PRAGMA foreign_key_check` afterwards, failing on any row.
3. **Any migration that batch-alters `revision`** re-executes the trigger DDL (batch mode recreates the table and silently drops triggers).
4. **Foreign keys** are `ON DELETE RESTRICT`, never CASCADE (rows are only soft-deleted anyway).
5. **Test and E2E databases** are created with `alembic upgrade head`, never with `create_all`. A test asserts that both triggers exist and that UPDATE and DELETE on `revision` raise.
6. **Startup self-check:** `sqlite_version` ≥ 3.40 and FTS5 available (a temporary fts5 table can be created); otherwise exit with a clear message.
7. **Phase 2: revision `0002`** (`backend/migrations/versions/20261030_0002_data_acquisition.py`, `down_revision = "0001"`). Revision `0001` is never edited. `0002` creates the tables of §14 with their indexes and the append-only triggers of `raw_snapshot` (DDL constants in `mdt/db/ddl.py`, like the revision triggers; a later batch alteration of `raw_snapshot` re-executes them, as in item 3), adds the nullable column `document.source_record_at` with a plain `ALTER TABLE … ADD COLUMN` (`op.add_column` outside batch mode, so `document` and its partial unique index are not recreated), and creates the index `document(source_id, external_id)` (§12). It does not alter `revision`: `run_id` and `proposal_id` exist since `0001`. Its downgrade drops what it created. The startup check (API §6) then requires head `0002`; `mdt db upgrade` applies it.
8. **Phase 3: revision `0003`** (`backend/migrations/versions/20261031_0003_analysis.py`, `down_revision = "0002"`), specified in §19.1. Revisions `0001` and `0002` are never edited. The startup check then requires head `0003`.

## 12. Indexes

Unique constraints as in §7. In addition:
- `comment(subject_id, status)`, `comment(parent_id)`;
- `service(project_id)`, `service(parent_service_id)`;
- `event(subject_id)`, `event(date_start)`;
- `participation(organization_id)`, `participation(subject_id)`, `relation(from_id)`, `relation(to_id)`, `indicator(subject_id)`, `evidence(subject_id)`;
- `document(published_start)`, `document(retrieved_at)`, `document_link(subject_id, state, document_id)`;
- `revision(at)`, `revision(author)`, `revision(entity_type, id)`, `revision(batch_id)`;
- `<entity>(deleted_at)` for every curated table;
- `derived(period)`, `derived(war_trajectory)`.

`json_each` filters are acceptable because only project and service have list fields of noticeable size. List endpoints load refs, labels, derived rows and virtual counts per page in batches, never per row.

Phase 2: `document(source_id, external_id)` and the indexes of the §14 tables (listed with each table).

Phase 3: `evidence(document_id)` (the document view lists a document's evidence, and `citation_count` counts it) and `participation(role)`.

## 13. Integrity checks (`mdt check`)

The check reports, without changing anything, and exits non-zero if anything is found (at most 50 lines per kind of problem):
- polymorphic references to missing rows;
- missing append-only triggers on `revision`;
- FTS rows missing or orphaned;
- missing or out-of-date `derived` rows;
- entities whose `version` or stored fields/`field_meta` differ from their latest revision snapshot;
- entities with no revision;
- fields whose `field_meta` entry says `verified` while its `evidence_id` is missing, names a deleted evidence row, names evidence of another record or field, or names evidence without a quote (kind `verification`, §5, §6.4).
- Phase 2:
  - `raw_snapshot` rows whose body file is missing or has another size than `size` (the file is not re-hashed; `mdt check --deep` re-hashes every file and compares `sha256`);
  - references to missing rows: `document.raw_snapshot_id`, `evidence.raw_snapshot_id`, `proposal.raw_snapshot_id`, `fetch_log.raw_snapshot_id`, every `field_meta[*].raw_snapshot_ids` entry (§5), `document.text_hash` without a `document_text` row, observations and open proposals whose `subject_id`/`related_id` names no record;
  - missing append-only triggers on `raw_snapshot`;
  - more than one run in status `running`, and runs in status `running` whose `heartbeat_at` is older than the stale limit (`docs/COLLECTORS.md` §6.3);
  - records with `merged_into` that are not deleted, or whose survivor does not exist.
  - A field that an older revision snapshot does not record and whose current value is empty is not reported (e.g. `document.source_record_at`, added by migration `0002`). The snapshot-file, trigger and run checks are part of the `mdt check` command (`cli.py`), the others of `domain/check.py`; nothing is reported twice.
- Phase 3 (all in `domain/check.py`):
  - **`evidence_anchor`:** anchored evidence (`text_hash` set) whose `document_text` row is missing, whose `document_id` is null, whose `text_hash` is not a text version of its document (§21), whose offsets are missing or lie outside its text version, or whose `quote` differs from `text[char_start:char_end]` of that version (§20.1); evidence with offsets but without `text_hash` (possible only in rows written through the generic API before Phase 3);
  - **`client_identifier`:** stored values of curated records (any field, `field_meta` excluded) and `document_text` texts that contain one of the patterns of §7 (Phase 3, client identifiers), e.g. stored before Phase 3; the line names the record and field, or the documents whose versions use the text, never the value.
  The empty fields added by migration `0003` (`codes = []`, the bases, `period_text`, `value_text`) follow the rule above for fields an older snapshot does not record.

## 14. Data acquisition tables (Phase 2)

System tables of migration `0002`. They are not curated entities: they have no `field_meta` and no revisions, and the generic entity API does not serve them (their endpoints are in `docs/API.md` §7). Timestamps follow §1.1, JSON columns §6.1 item 4. Foreign keys are `ON DELETE RESTRICT`; nothing here is ever deleted in Phase 2 (a purge is Phase 4, `PLAN.md` §6.4).

### 14.1 `raw_snapshot` (prefix `raw_`)

One row per response body the app has kept: every final response of a polite-client request that has a body (whatever its HTTP status; an empty body counts as none), every upload and every replayed fixture response. **Rows are immutable** (append-only triggers abort `UPDATE` and `DELETE`, like those of `revision`).

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | `raw_<ULID>` |
| `run_id` | TEXT NULL, FK `collector_run` | null for uploads and manual fetches |
| `source_id` | TEXT NOT NULL | collector name (key in `sources.yaml`), or `manual` (uploads, manual fetches) |
| `via` | TEXT NOT NULL | `live` · `wayback:<14-digit timestamp>` (an archived copy fetched by hand, `docs/COLLECTORS.md` §10.3; the capture's timestamp, taken from the final URL) · `upload` · `replay` (a fixture served by the replay transport in tests and E2E, `docs/COLLECTORS.md` §4.10) |
| `url` | TEXT NULL | requested URL (normalised as in `docs/COLLECTORS.md` §4.1); null for uploads |
| `final_url` | TEXT NULL | URL of the final response after redirects |
| `redirects` | JSON NOT NULL DEFAULT `[]` | hops as `"<status> <url>"` |
| `http_status` | INTEGER NULL | null for uploads |
| `fetched_at` | TEXT NOT NULL | UTC; the upload time for uploads; the fixture's `retrieved_at` for `replay` |
| `headers` | JSON NOT NULL DEFAULT `{}` | lower-case names, only `content-type`, `content-length`, `content-encoding`, `content-language`, `content-disposition`, `etag`, `last-modified`, `cache-control`, `date` (never cookies or request headers) |
| `content_type` | TEXT NULL | media type without parameters, lower-case (from the header; for uploads from the file name and magic bytes) |
| `filename` | TEXT NULL | original file name of an upload (base name only) |
| `sha256` | TEXT NOT NULL | SHA-256 (hex) of the body |
| `size` | INTEGER NOT NULL | body length in bytes |

- **Body** = the HTTP entity body after removing the transfer coding (`Content-Encoding` gzip/deflate), otherwise unchanged: never re-encoded, re-serialised, trimmed or normalised; for uploads the uploaded bytes.
- **File:** `<DATA_DIR>/raw/<sha256[0:2]>/<sha256>.gz`, gzip of the body (compression level 6, header mtime 0, no file name, so equal bodies give equal files). It is written to a temporary file in `<DATA_DIR>/raw/` and hard-linked into place (atomic, never replacing a file); an existing file is never rewritten (content addressing deduplicates). The row is inserted only after the file exists, so no row points to a missing file; a crash can leave an unreferenced file, which is harmless.
- **Indexes:** `(url)`, `(sha256)`, `(run_id)`, `(source_id, fetched_at)`.
- Raw snapshots never leave the server: no export or release contains them (`PLAN.md` §6.7, D-5); the snapshot body endpoint (API §7.3) serves them to the app's user only.

### 14.2 `collector_run` (prefix `run_`)

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | `run_<ULID>` |
| `collector` | TEXT NOT NULL | key in `sources.yaml` (`docs/COLLECTORS.md` §3), including the built-in `tagger` |
| `trigger` | TEXT NOT NULL | `cli` · `ui` (Phase 4 adds `schedule`) |
| `mode` | TEXT NOT NULL | `incremental` · `full` (meaning per collector, `docs/COLLECTORS.md` §6.4) |
| `params` | JSON NOT NULL DEFAULT `{}` | parameters given at start (`limit`, `refetch`, `recall_sample`, `recall_seed`, `document_ids`); `replay: true` in replay mode |
| `status` | TEXT NOT NULL | `running` · `succeeded` · `partial` · `failed` · `cancelled` |
| `started_at` | TEXT NOT NULL | |
| `finished_at`, `heartbeat_at`, `cancel_requested_at` | TEXT NULL | |
| `complete_listing` | INTEGER NOT NULL DEFAULT 0 | the run parsed every listing unit of its collector (`docs/COLLECTORS.md` §8), whatever its end status (§15.7) |
| `stats` | JSON NOT NULL DEFAULT `{}` | counters, below |
| `error` | TEXT NULL | fatal error of a `failed` run (≤ 2 000 characters) |
| `code_version` | TEXT NOT NULL | app version and `GIT_COMMIT` (e.g. `0.2.0+3f2c1a9`) |
| `config_hash` | TEXT NOT NULL | SHA-256 of the collector's `sources.yaml` entry (with the defaults) and of the codebook files collectors use (`collector_mappings.yaml`, `event_patterns.yaml`; both for every collector) |

- **Status rules:** a run is inserted as `running` and ends as `succeeded` (finished without error-level messages), `partial` (finished, but some requests, pages or items failed), `failed` (stopped by a fatal error, including an interrupted process, `docs/COLLECTORS.md` §6.3) or `cancelled`. Finished runs never change again.
- **At most one running run** in the whole database (CLI and server alike): partial unique index `uq_collector_run_running` on `(status) WHERE status = 'running'`. A start while another run is running is refused (`docs/COLLECTORS.md` §6.1).
- **`stats` keys** (integers, all present, 0 by default): `requests`, `not_modified`, `robots_disallowed`, `bytes`, `snapshots`, `pages_parsed`, `parse_errors`, `items_seen`, `entities_created`, `entities_updated`, `revisions`, `proposals_opened`, `proposals_seen_again`, `proposals_superseded`, `observations_new`, `observations_missing`, `links_suggested`, `messages_suppressed`, `errors`, `warnings`; collector-specific counters go under `extra` (an object), which also holds `collector_version` (the collector's `VERSION`, recorded when the run starts). Counting rules: `docs/COLLECTORS.md` §6.6.
- **Indexes:** `(collector, started_at)`, `(status)`.

### 14.3 `fetch_log`

One row per HTTP request attempt (robots.txt, redirect hops and retries included), and one row per URL the client decided not to request.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `run_id` | TEXT NULL, FK `collector_run` | null for manual fetches |
| `at` | TEXT NOT NULL | start of the attempt (UTC) |
| `method` | TEXT NOT NULL | `GET` or `HEAD` |
| `url`, `host` | TEXT NOT NULL | normalised URL and host |
| `purpose` | TEXT NOT NULL | `robots` · `content` |
| `attempt` | INTEGER NOT NULL DEFAULT 1 | 2, 3 … for retries |
| `status` | INTEGER NULL | HTTP status; null without a response |
| `outcome` | TEXT NOT NULL | `ok` · `not_modified` · `redirect` · `http_error` · `network_error` · `robots_disallowed` · `blocked` · `too_large` · `refused` (not requested: excluded host, trap path, host blocked or throttled earlier in the run, robots.txt unavailable, no fixture in replay mode) |
| `bytes` | INTEGER NULL | body bytes received |
| `duration_ms` | INTEGER NULL | |
| `raw_snapshot_id` | TEXT NULL, FK `raw_snapshot` | the stored body; for `not_modified` the earlier snapshot that is still current |
| `retry_after_s` | REAL NULL | parsed `Retry-After` |
| `error` | TEXT NULL | short reason (≤ 500 characters) |

Indexes: `(run_id, id)`, `(host, at)`, `(url)`.

### 14.4 `run_message`

Notable events of a run (errors, warnings, notes), shown in the UI.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `run_id` | TEXT NOT NULL, FK `collector_run` | |
| `at` | TEXT NOT NULL | |
| `level` | TEXT NOT NULL | `info` · `warning` · `error` |
| `code` | TEXT NOT NULL | from the list in `docs/COLLECTORS.md` §6.6 |
| `message` | TEXT NOT NULL | ≤ 2 000 characters, plain text |
| `url`, `raw_snapshot_id`, `subject_id` | TEXT NULL | context |
| `details` | JSON NOT NULL DEFAULT `{}` | |

At most 200 messages per run and `code`; further ones only increase `stats.messages_suppressed`. Index: `(run_id, level, id)`.

### 14.5 `source_observation`

What a collector saw in its source, per stable key. The table is also the **binding between a source's keys and curated records**: once a key is bound to a record, later runs update that record (§15.3).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `collector` | TEXT NOT NULL | |
| `key` | TEXT NOT NULL | collector-defined stable key (≤ 500 characters), e.g. `entry:brave1`, `service:RD4U`, `news:<slug>` |
| `entity_type` | TEXT NOT NULL | the curated type the key describes |
| `subject_id` | TEXT NULL | the bound record; null while unbound (e.g. a C4b page judged not relevant, an unmatched C1 entry with its proposal) |
| `bound_by` | TEXT NULL | `auto` (a matching rule or a direct create, §15.3, §15.4) · `proposal` (an accepted `create_entity`, §16.4) |
| `bound_at` | TEXT NULL | |
| `external_id` | TEXT NULL | identifier given by the source (e.g. the project UUID on thedigital.gov.ua) |
| `url`, `label` | TEXT NULL | where and under which title the key was last seen |
| `first_seen_at`, `first_seen_run`, `last_seen_at`, `last_seen_run` | TEXT NOT NULL | |
| `present` | INTEGER NOT NULL DEFAULT 1 | false after a run with a complete listing that did not see the key |
| `missing_since_at`, `missing_since_run` | TEXT NULL | first such run (cleared when seen again) |
| `missing_runs` | INTEGER NOT NULL DEFAULT 0 | consecutive such runs |
| `last_snapshot_id` | TEXT NULL, FK `raw_snapshot` | |
| `details` | JSON NOT NULL DEFAULT `{}` | collector-specific latest details (e.g. rubric, sitemap `lastmod`, discard reason, recall sample seed) |

- UNIQUE `(collector, key)`; indexes `(subject_id)`, `(collector, present)`, `(collector, external_id)`.
- Rows are updated in place by runs of their collector; they are never deleted. An observation of a merged record keeps its `subject_id`; runs follow `merged_into` (§15.3), and an unmerge needs no change here (§18).

### 14.6 `proposal` (prefix `prp_`)

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | `prp_<ULID>` |
| `kind` | TEXT NOT NULL | `create_entity` · `update_field` · `create_event` · `possible_duplicate` · `possibly_discontinued` (§16.1) |
| `state` | TEXT NOT NULL | `open` · `accepted` · `accepted_modified` · `rejected` · `superseded` (§16.2) |
| `entity_type` | TEXT NOT NULL | type of the subject, or of the record to create |
| `subject_id` | TEXT NULL | existing record concerned; null for `create_entity` |
| `related_id` | TEXT NULL | `possible_duplicate`: the other record |
| `field` | TEXT NULL | `update_field`: the field (`text_hash` for a text version, §15.6) |
| `current_value` | JSON NULL | `update_field`: the field's value when the proposal was last raised; bulk accept compares it with the live value (§16.4) |
| `proposed_value` | JSON NULL | `update_field`: the proposed value (for add-only URL lists only the URLs to add); `possibly_discontinued`: `{"status": "discontinued"}` |
| `payload` | JSON NOT NULL DEFAULT `{}` | kind-specific (§16.1) |
| `collector` | TEXT NOT NULL | the collector (or `tagger`) that proposed it |
| `first_run_id`, `last_run_id` | TEXT NOT NULL, FK `collector_run` | first and latest run that proposed it |
| `raw_snapshot_id` | TEXT NULL, FK `raw_snapshot` | latest source snapshot (shown as the proposal's "Snapshot") |
| `source_url` | TEXT NULL | |
| `quote` | TEXT NULL | verbatim from the source, ≤ 1 000 characters |
| `locator` | TEXT NULL | |
| `observation_id` | INTEGER NULL, FK `source_observation` | `create_entity`, `possibly_discontinued` |
| `dedup_key` | TEXT NOT NULL | §16.3 |
| `seen_count` | INTEGER NOT NULL DEFAULT 1 | runs that proposed it |
| `created_at`, `last_seen_at` | TEXT NOT NULL | |
| `decided_at` | TEXT NULL | |
| `decided_by` | TEXT NULL | `user` (accept, reject) or `system` (superseded) |
| `decision_note` | TEXT NULL | ≤ 2 000; required for reject; the reason for `superseded` |
| `result_id` | TEXT NULL | record written by the acceptance (the created record, the merge survivor, the document marked as duplicate, the record linked instead of created) |

- Partial unique index on `(dedup_key) WHERE state = 'open'`; indexes `(state, kind)`, `(subject_id, state)`, `(related_id, state)`, `(collector, state)`, `(last_run_id)`.
- Proposal rows have no revisions: their lifecycle is recorded in the row (`decided_*`), and the curated writes they cause carry `revision.proposal_id`.

### 14.7 `merge_log` (prefix `mrg_`)

Record of a merge (§18): `id`, `entity_type`, `survivor_id`, `merged_id`, `at`, `batch_id`, `proposal_id` (NULL), `note`, `field_choices` (JSON `{field: "survivor"|"merged"|"union"}`), `changes` (JSON list of `{entity_type, id, field, before, after}`: every field the merge changed, the survivor's chosen values and every repointed reference, document `links` included), `unmerged_at` and `unmerge_batch_id` (NULL; set once by the unmerge). Rows are never deleted. Indexes `(survivor_id)`, `(merged_id)`.

### 14.8 `import_run` (prefix `imp_`)

One row per import that was run (mapping and dry runs are not stored, `docs/COLLECTORS.md` §9.1).

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | `imp_<ULID>`; also the `batch_id` of every revision the import writes |
| `upload_id` | TEXT NOT NULL, FK `raw_snapshot` | the uploaded file (`via = upload`; the CLI stores the file as an upload first) |
| `filename` | TEXT NOT NULL | |
| `file_label` | TEXT NOT NULL | `<filename>#<sha256[0:12]>`; provenance `import:<file_label>` (§17.1) |
| `entity_type` | TEXT NOT NULL | one of the five table types |
| `sheet` | TEXT NULL | XLSX sheet name |
| `status` | TEXT NOT NULL | `done` · `failed` (a fatal error such as an unreadable file; the rows written before it stay) |
| `mapping` | JSON NOT NULL | `{column: field}` |
| `key_field` | TEXT NULL | `id`, `slug` or `url`; null = create every row |
| `note` | TEXT NULL | revision note of the import's writes |
| `stats` | JSON NOT NULL | `rows`, `create`, `update`, `unchanged`, `conflicts`, `errors` (the keys of the plan, `docs/COLLECTORS.md` §9.4) |
| `errors` | JSON NOT NULL DEFAULT `[]` | row errors and conflicts (at most 500) |
| `error` | TEXT NULL | the fatal error of a failed import |
| `created_at`, `finished_at` | TEXT | |

## 15. Reconciliation of collector writes (Phase 2)

The reconciler turns a run's **candidates** (parser output, `docs/COLLECTORS.md` §2.1, §7) into writes, proposals and observation updates. Its rules hold for every collector; the per-collector parts (keys, matching rules, writable fields) are declared in `docs/COLLECTORS.md` §8.

### 15.1 Candidates and declarations

- A **candidate** names the curated type, its observation `key`, optional `external_id`, `url` and `label`, the field values it observed (API representation, normalised with §1.2 before any comparison; a value that fails normalisation or validation is dropped with the run warning `invalid_value`), the observed values of propose-only fields, the snapshots each field was parsed from (`field_snapshots`) and its main evidence (`raw_snapshot_id`, `source_url`, optional `quote` and `locator`). Document candidates also carry the extracted text with its snapshot and extraction method, and the links the source itself states (e.g. a project page and its project).
- A candidate contains **only the fields the run actually observed**: a field whose source page could not be read in this run is left out (absent, not empty), so a transient failure never changes or clears a value.
- Each collector declares per type: whether an unmatched candidate is created directly (`creates`) or becomes a `create_entity` proposal, the **fields it may write** (`writes`), the fields it may only propose (`propose_only`, e.g. C1's official URLs from project-page links), its matching rules (§15.3), and whether missing keys may raise `possibly_discontinued` (`discontinued`). A field outside `writes` and `propose_only` is never written or proposed by that collector.
- A **sighting** (`ctx.observe`: a known key seen in a listing or sitemap without being fetched, or a page that yields no record) only upserts its observation (§15.7).

### 15.2 Channel and provenance

Direct writes use `Actor.collector(<name>, <run_id>)`: channel `collector`, `created_by`/`updated_by` = `collector:<name>`, `revision.run_id` set, `field_meta` per §5 (`src = collector:<name>@<run_id>`, `locked = false`, `raw_snapshot_ids` from the candidate's `field_snapshots`). Collector-created records start with `verification_status = unverified` (documents also `screening_status = unscreened`).

### 15.3 Matching a candidate to a record

1. If the observation `(collector, key)` is bound, its `subject_id` is the record. A subject merged into another (`merged_into` set) is followed to its survivor, repeatedly, without changing the observation; any other deleted subject is skipped (run message `subject_deleted`, nothing written).
2. Otherwise the collector's match rules apply, in this order, each only where the collector declares it:
   1. `external_id`: an observation of the same collector and the candidate's own `entity_type` with the same `external_id` that is bound (C1 gives a project entry and its project page the same `external_id`, C3 a service and its page; a project candidate is never matched to a document);
   2. `document`: a document with the same (`source_id`, `external_id`), then one with the same `canonical_url` (§3.4);
   3. `url_fields`: exactly one record whose URL fields contain the candidate's canonical URL (project `ministry_urls`, `official_urls`; service `urls`).
   Each rule considers live and deleted records of the candidate's type only; a merged record counts as its survivor. Bindings are only ever made to records of the key's type; a key found bound to a record of another type (a damaged row) is reported as `write_error` and nothing is written.
3. A unique live match binds the observation (`bound_by = auto`) and the candidate updates that record (§15.5).
4. A match that is **deleted** (and not merged), where the same rule finds no live record, blocks the candidate: nothing is created or proposed (run message `subject_deleted`), so a person's deletion is never undone by a collector.
5. Several live matches bind nothing; they are listed as `candidates` in the `create_entity` proposal (§16.1) or, for types the collector creates directly, the record is created and a `possible_duplicate` proposal names each other match (`basis = match`, `details = {rule, key}`).

### 15.4 New records

An unmatched candidate becomes:
- a **direct create** if the collector declares `creates` for its type (C3 services, C1–C4 documents; `docs/COLLECTORS.md` §8), and the observation is bound to the new record (`bound_by = auto`);
- otherwise a **`create_entity` proposal** (C1 projects), whose observation stays unbound until the proposal is accepted.

A create needs every required field; a candidate without them becomes a run warning `incomplete_candidate` instead. C5's events follow §15.12.

### 15.5 Updates of a bound record

A field counts as **locked** for collectors when its `field_meta` entry has `locked = true` (set, accepted, imported, restored, seeded or field-verified by a person), or when the record's `verification_status` is `verified` or `disputed` (the person's judgement covers the whole record, CODEBOOK §2). For every field in the collector's `writes`, comparing the candidate value **V** with the current value **C** read inside the write unit:

| V compared with C | Field | Result |
|---|---|---|
| V is empty | any | nothing: collectors never clear a field (a value missing from a source is no evidence that it is empty) |
| V equals C (`values_equal`, §1.2) | any | nothing; open `update_field` proposals of this collector for this field become `superseded` ("the source agrees with the current value") |
| V differs | not locked | direct write |
| V differs | locked | `update_field` proposal (§16) |

- **Propose-only** fields: a V that differs from C always becomes an `update_field` proposal.
- All direct writes of one candidate to its record are **one** `apply_change` (one revision).
- List values are compared whole and in order (§1.2); collectors emit lists in the canonical order of their declaration, so a source that only reorders produces no change.
- **URL lists are add-only** (`ministry_urls`, `official_urls`, `urls`, `archive_urls`): only URLs the list does not contain yet (compared by canonical URL, §3.4) count as a difference; a collector never removes or reorders URLs. Not locked: the current list with the new URLs appended is written. Locked or propose-only: an `update_field` proposal whose `proposed_value` holds only the URLs to add (§16.3, §16.4).
- **System fields** in `writes` (`source_categories`, `source_record_at`, `published_at_utc`) cannot be locked by a person, so `apply_change` does not check locks on them; they are written directly unless the record is verified or disputed, in which case the difference is proposed and the domain layer writes it on accept. `source_id` and `external_id` are set on create only and never rewritten by a later match; `canonical_url` follows `url` (§6.2); the text version follows §15.6.
- **Create-only fields** (`domain/reconcile.py` `CREATE_ONLY`): project `name_en` and `name_uk`, service `project_id`, document `source_id` and `external_id`. A collector may carry them in a candidate (declared in `writes`); they are used for direct creates and `create_entity` proposals only, never to update a bound record (C1 never renames a project, C3 sets `project_id` on create only).
- **Unknown codes:** see §15.10; a code already stored in the field (e.g. an inactive term) is kept.
- The record-level `verification_status`, `notes`, the scope fields and the D1–D4 fields are never in a collector's `writes`.

### 15.6 Change detection, text versions and idempotency

- Collectors compare **parsed, normalised values**, never raw bytes. Most HTML responses change on every request (CSP nonces, tokens), so the raw `sha256` is no change signal.
- **Volatile content never reaches a candidate.** Parsers must not emit: CSP nonces; csrf tokens; bot-manager scripts and tokens (the kmu.gov.ua `__uzdbm_*` token encodes the client's IP address); Telegram `data-view` attributes and view counts; relative times such as `publishedAt.related` ("1 день тому"); cache-busting query parameters on image and asset URLs (`?v=…`); Sentry trace and baggage values; any render or request timestamp. Every collector has a test that parses two captures differing only in volatile parts and gets identical candidates (fixture pairs in `docs/COLLECTORS.md` §12.2).
- **Document texts:** the extracted text is normalised (NFC; CRLF and CR to LF; C0 control characters except tab and newline removed; trailing whitespace removed per line; runs of three or more line breaks reduced to two; trimmed). `text_hash` = SHA-256 of its UTF-8 bytes.
- **Text versions:** a document's text version is `text_hash`, `raw_snapshot_id`, `retrieved_at` and `extraction_method`, and it changes only as a whole. A candidate whose text hash differs from the document's inserts a `document_text` row (if not yet present) and then
  - writes the four fields directly, in the record's `apply_change`, when the document's `source_id` is the writing collector, `retrieved_at` is not locked and the record is not verified or disputed;
  - otherwise (a manual document, a document of another source, a retrieval time a person corrected, a verified record) raises one `update_field` proposal on `text_hash` whose payload carries the new `raw_snapshot_id`, `retrieved_at` and `extraction_method`; accepting it writes all four (§16.4).
  An unchanged hash changes none of them, so re-fetching an unchanged page writes nothing.
  The text version comes from the candidate's `text`, `text_snapshot_id` (else the main evidence's snapshot) and `extraction_method`; `retrieved_at` is that snapshot's `fetched_at`. A candidate without text never clears a stored text. The tagger and the event patterns (§15.8, §15.9) run only when the text is written (create or direct update), not when it becomes a text-version proposal. An open text-version proposal is superseded when the source's text equals the current one again. A restore treats the text version as a unit too: restoring `retrieved_at` from another version also restores `text_hash`, `raw_snapshot_id` and `extraction_method`.
- **No-op:** a record whose candidate yields no difference gets no `apply_change` call: no revision, no version bump.
- **One candidate per record and run:** within one run, each record is reconciled from its first candidate. A later candidate of the same run that resolves to the same record (the same key listed twice, two keys bound to one record, a key of a merged record) only updates its own observation; where it carries a different value for a field, the run warning `conflicting_candidates` names both keys and the field (no write, no proposal). Collectors emit candidates in a deterministic order (`docs/COLLECTORS.md` §6.1), so repeated runs decide alike.
- **Idempotency (Definition of Done 3):** running a collector twice against the same responses creates on the second run **no record, no revision and no proposal row**, and no proposal changes its state. The second run only writes log rows (`collector_run`, `fetch_log`, `run_message`, `raw_snapshot` for bodies it fetched again) and bookkeeping (`source_observation`; `proposal.last_run_id`, `last_seen_at`, `seen_count`, `current_value`, `payload`). The acceptance test is `docs/COLLECTORS.md` §12.1.

### 15.7 Observations and disappearance

- Every candidate and every sighting upserts its observation: `present = 1`, `last_seen_*`, `missing_runs = 0`, `missing_since_*` cleared, `url`, `label`, `external_id`, `details`, `last_snapshot_id`; a new key is inserted with `first_seen_* = last_seen_*`.
- A run sets `complete_listing = 1` when it parsed every listing unit of its collector (definition per collector, `docs/COLLECTORS.md` §8), whatever its end status: keys come from listings, so a failed detail page cannot hide a key. After a run with a complete listing that was not cancelled, every observation of the collector that the run did not see gets `present = 0`, `missing_runs + 1`, and `missing_since_*` if it was present before. Runs without a complete listing (incremental runs, runs with `limit`, a listing page that failed) never mark keys as missing.
- A key seen again closes the open `possibly_discontinued` proposals of this collector for its subject as `superseded` ("seen again in run …").
- **`possibly_discontinued`:** after a run with a complete listing, a live project or service bound to observations of a collector with `discontinued: true` gets a proposal when **all** its observations of that collector have `missing_runs` ≥ `discontinued_after_runs` (`sources.yaml`, default 2), unless its `status` is already `discontinued`. Documents get no proposal; their observations show them as missing (UI "Seen in sources").
- A candidate that fails validation at write time (`write_error`) still updates its observation, in a second small unit, so its key is never treated as missing.

### 15.8 Document links from alias tagging

- The reconciler runs the tagger (`docs/COLLECTORS.md` §7.6) for every document candidate whose text is new or changed; the built-in collector `tagger` runs it over stored texts. It yields the projects and services whose curated aliases (or names) occur in the text, each with `matched_aliases`, `match_count` and `snippet`.
- For every suggested subject, and every subject the source itself links (a project page and its project, an official URL and its project, a service page and its service), that is **not yet in the document's links in any state**, the reconciler adds `{subject_id, origin: "auto", state: "suggested", matched_aliases, match_count, snippet}`. A subject the source links keeps the source's snippet (e.g. "Service page on diia.gov.ua") and takes the tagger's `matched_aliases` and `match_count` when the tagger found it too.
- **Adding suggestions is an add-only write outside the decision table** (§15.5): it changes no existing value, so on channel `collector` it is allowed even when `links` is locked or the record is verified, and it leaves the existing `field_meta.links` entry unchanged (a collector entry is written only when there is none). It is part of the record's `apply_change`, so the document revision carries the run.
- Collectors never change or remove an existing link. In the app, an automatic link can be confirmed or rejected but not removed, so a rejected subject stays in the links and is never suggested again; manual links can be removed (`docs/UI.md` §8.7).
- Only confirmed links count in analyses (`PLAN.md` §5.3).

### 15.9 Event proposals from text patterns

The tagger also matches the phrase patterns of `codebook/event_patterns.yaml` (CODEBOOK §4). A sentence that contains an alias match of a project or service and a pattern match yields one `create_event` proposal per (subject, event type) (§16.1), with `collector = tagger`. It is never a fact: the date is the document's publication date with basis `inferred`, because an announcement date is not automatically the event date (CODEBOOK §2.6), and the evidence is the document's current text version (`docs/COLLECTORS.md` §7.7). The quote is the sentence cut to at most 1 000 characters with trailing whitespace removed after the cut (Phase 3), and `char_end` = `char_start` + its length, so `quote == text[char_start:char_end]` (§20.6).

### 15.10 Unknown vocabulary codes

A candidate code that is not an active term of the field's vocabulary is never written: the code is dropped from a list value (a scalar value is dropped whole), and the run gets the warning `unknown_code` naming the code, the source's label for it (from the candidate's `details.code_labels`, `{code: label}`) and the record. A code the field already holds (e.g. a term deactivated later) is kept. Collectors never create or propose terms: a person adds the term (Codebook page, or the codebook file and `mdt seed`), and the next run writes the code.

### 15.11 Write units

Each record's reconciliation (direct writes, link additions, proposals, observation update) is **one write unit** (§6.1): it re-reads the record and its `field_meta` inside the unit, decides, and writes. A `LockedFieldError` cannot occur, because the decision uses the state read inside the same unit. Run bookkeeping (`stats`, `heartbeat_at`) is written in separate small units.

### 15.12 `first_archived` events (C5)

C5 (`docs/COLLECTORS.md` §8.5) maps captures from the Wayback Machine's CDX index to projects and services, per subject and URL the earliest capture:
- **Exact** matches (the subject's own ministry URL or service URL): C5 creates a `first_archived` event (unverified) together with its evidence row, in one write unit, unless
  - the capture is **already recorded**: an event C5 created for the subject from the same capture (its creating revision names the subject and the capture's `date_text`), whatever a person did with it since (re-dated, widened, moved to another subject, retyped, deleted), or
  - a live `first_archived` event of the subject (from anyone) or a deleted one created by C5 (`created_by = collector:wayback`) has a `date_end` on or before the capture's date.
  A capture earlier than every existing bound therefore creates a new event; C5 never updates an event, so each event keeps the evidence of its own capture, and the derived `existed_by` takes the earliest (§8.3). **Once a person has changed or deleted an event C5 created for the subject** (any later revision of it), such a capture becomes a `create_event` proposal instead of a direct create, so an automatic fact never undoes a person's correction of the subject's archive bound (Definition of Done 5).
- **Other** matches (official URLs such as domain roots, pre-relaunch or other-rubric project URLs): a `create_event` proposal with the same event and evidence values (§16.1), under the same conditions, because such a capture can predate the project.
- **Values:** `date` = the Europe/Kyiv calendar date of the 14-digit UTC timestamp, precision `day`, `date_basis = archive_upper_bound`, `date_text` = the timestamp and the archived URL, `description_en` naming the capture; evidence: subject = the event, `target = entity`, `url` = the CDX request URL (what C5 retrieved), `archive_url` = the capture URL, `raw_snapshot_id` = the CDX response, `retrieved_at` = its `fetched_at`, `quote` = the CDX row as JSON.

## 16. Proposals (Phase 2)

### 16.1 Kinds

| Kind | Raised by | Concerns | Payload | Accept writes |
|---|---|---|---|---|
| `create_entity` | an unmatched candidate of a type the collector does not create (§15.4; Phase 2: C1 projects) | `entity_type`; `observation_id` | `{fields: {…observed…}, field_snapshots, candidates: [ids], observation_key, site_slug}` | creates the record from the observed `fields` plus the person's `values` and binds the observation (`bound_by = proposal`); a project needs `in_paper_scope` and `scope_note` from the person (§7); its `slug` is generated at accept time from `site_slug` (lower-cased, `_` → `-`, other characters outside `[a-z0-9-]` removed, suffixed `-2`, `-3`, … while taken, deleted rows included) unless `values` sets it. Or, as **link to existing** (`match_id`), binds the observation to that record and writes nothing else |
| `update_field` | a differing value of a locked or propose-only field (§15.5), or a new text version (§15.6) | `subject_id`, `field` | `{field_snapshots}`; text version: `{raw_snapshot_id, retrieved_at, extraction_method, char_count}` | `apply_change {field: proposed_value}` (or the edited value); add-only URL lists: the URLs appended to the current list; text version: the four fields |
| `create_event` | a text pattern near an alias match (§15.9; collector `tagger`), or a C5 capture that is not an exact match or whose subject has a C5 event a person changed (§15.12) | `entity_type = event` (the record to create); `subject_id` (project or service) | `{event: {subject_id, event_type, date, date_basis, date_text, description_en}, evidence: {document_id, text_hash, char_start, char_end, url, archive_url, raw_snapshot_id, retrieved_at}, pattern_id, matched_alias}` (keys that do not apply are null); `quote` = the sentence or the CDX row | creates the event (edited values with edit & accept) and an evidence row (subject = the new event, `target = entity`, the payload's evidence values and the quote), two revisions with one `batch_id` |
| `possible_duplicate` | duplicate detection (`docs/COLLECTORS.md` §7.8), or a direct create with several live matches (§15.3) | `subject_id`, `related_id` (ordered: `subject_id` < `related_id`) | `{basis: "title_date"\|"text"\|"name"\|"match", similarity, details}` (`match`: `details = {rule, key}`) | documents: `values = {"duplicate_id": <one of the two>}`: that document gets `screening_status = excluded`, `screening_reason = duplicate`, `screening_note = "Duplicate of <other id>"`; services and projects: `values = {"survivor_id", "fields"}` runs the merge (§18) |
| `possibly_discontinued` | disappearance (§15.7) | `subject_id` (project or service); `observation_id` | `{reason: "missing_from_listing", last_seen_at, missing_since_at, keys}`; `proposed_value = {"status": "discontinued"}` | `apply_change {status: "discontinued"}`, or with edit & accept another `status` code (e.g. `suspended`, `unknown`) |

### 16.2 States

`open` → `accepted` (accepted as proposed) · `accepted_modified` (edit & accept whose values change an observed or proposed value, or link to existing; values the person only adds, such as a new project's scope and slug, keep `accepted`) · `rejected` (by the user, note required) · `superseded` (closed by the system, `decision_note` says why). Closed proposals never reopen; if the situation recurs, a new row may open (§16.3).

### 16.3 Deduplication and superseding

- `dedup_key` = SHA-256 of the canonical JSON array `[kind, scope, entity_type, target, core]`:

  | Kind | `scope` | `target` | `core` |
  |---|---|---|---|
  | `create_entity` | collector | observation key | `null` (a changed title refreshes the open proposal instead of opening a second one) |
  | `update_field` | collector | `subject_id` | `[field, normalised proposed value]`; add-only URL lists: `[field, sorted canonical URLs to add]` |
  | `create_event` | `"*"` (any collector or the tagger) | `subject_id` | text evidence: `[event_type, document_id, fold(quote)]`; archive evidence: `[event_type, archive key of the captured URL]` |
  | `possible_duplicate` | `"*"` | `subject_id` | `related_id` |
  | `possibly_discontinued` | collector | `subject_id` | `reason` |

- When a run raises a proposal whose key exists:
  - **open** → no new row: `last_run_id`, `last_seen_at`, `seen_count`, `raw_snapshot_id`, `source_url`, `quote`, `locator`, `current_value` and `payload` are refreshed (so an open C5 proposal follows an earlier capture of its URL);
  - **rejected** → nothing (rejection memory);
  - **accepted** or **accepted_modified** → nothing (a value a person accepted and later changed is not proposed again), unless a newer `update_field` proposal of the same collector for the same subject and field was created after that decision, i.e. the source changed and came back; then a new proposal opens;
  - **superseded**, or no row → a new proposal opens.
- The system supersedes an open proposal (`decided_by = system`) when: a newer `update_field` value of the same collector for the same subject and field opens in a later run; the source value equals the current value again (§15.5); the subject is deleted (checked whenever a run touches the subject and at accept time); a `possibly_discontinued` subject is seen again (§15.7); a merge retires its subject (§18); the observation key of an open `create_entity` proposal becomes bound by a match rule ("The source entry now matches <id>"); accepting a `create_entity` proposal whose observation is already bound to a live record supersedes it (`changed: false`).

### 16.4 Accept, edit & accept, reject

- **Accept** (API §7.4) re-checks the proposal inside one write unit: the subject must be live (else `409 entity_deleted`), and if nothing is left to write (e.g. the field already holds the proposed value) the proposal becomes `superseded` and the response says `changed: false`. For the add-only URL lists, accepting appends the proposal's URLs to the **current** list (URLs already present are skipped), so URLs a person added meanwhile are kept; other values are written as proposed (the UI shows the live value next to the proposed one, API §7.4).
- Writes use `Actor.accept(proposal_id, src)`: channel `ui`, author `user`, `revision.proposal_id` = the proposal, revision note = the decision note, else `Accepted proposal <id>`. The validation rules of §7 apply as to any edit. A text version is written by the domain layer (its fields are system fields).
- **Field provenance** (§5): values observed in a source and taken unchanged (an `update_field` value other than an add-only list, the observed `fields` of a `create_entity` proposal) get `src = collector:<collector>@<last_run_id>` and `raw_snapshot_ids` from the payload's `field_snapshots`; edited values, add-only list results, values the person adds (e.g. the scope and slug of a new project) and suggested interpretations (`create_event`, `possibly_discontinued`, `possible_duplicate`) get `src = manual`. All get `by = user`, `locked = true`, `verified = unverified`.
- **Evidence** written by accepting a `create_event` proposal takes `document_id`, `text_hash`, the offsets, `url`, `archive_url`, `raw_snapshot_id` and `retrieved_at` from the payload, so it records when and from which snapshot the quote was retrieved, never the time of acceptance. Phase 3: text evidence is anchored (§20.6), so its `quote` is taken from the stored text of the payload's version at the payload's offsets and checked against the proposal's quote (§7, anchored evidence).
- **Edit & accept** = accept with `values` (for `create_entity` any `in_create` field of the type, validated like a create; for `update_field` the one field; for `create_event` the event fields; for `possibly_discontinued` the `status`) → state `accepted_modified`. **Link to existing** (`create_entity` with `match_id`) → `accepted_modified`, `result_id` = the linked record.
- **Reject** requires a note (≤ 2 000 characters) and writes no curated data.
- **Bulk** accept and reject apply the same rules per proposal (each its own write unit, one shared `batch_id` for the revisions of a bulk accept). Bulk accept takes no `values`, so it leaves proposals that need them (`create_entity` for projects, `possible_duplicate`) with the result `needs_values`, and it leaves `update_field` proposals whose live value differs from `current_value` (the field changed after the proposal was last raised) with the result `stale`; the person decides those one by one.
- `result_id` records the created or written record. Accepting a `create_event` proposal recomputes the subject's derived values (§8.1), like any event write.

## 17. Imports and manual documents (Phase 2)

### 17.1 Imports (CSV and XLSX)

The workflow (upload, preview, dry run, run) is in `docs/COLLECTORS.md` §9; the data rules are:
- **Channel `import`**, actor `Actor.importer(<file_label>)` (§14.8), so `created_by`/`updated_by`, `revision.author` and `field_meta.by` read `import:<file_label>` and values get `src = import:<file_label>`, `locked = true` (§5). `revision.batch_id` = the import run's ID; the note is the import's `note`.
- **Importable fields:** `editable` fields of the type, and `create_only` fields on create; never system, derived or virtual fields, never `links`.
- **Never overwriting manual values:** an existing record's field is written only if the value differs and the field has **no `field_meta` entry**, or its entry is **unlocked** (a collector value), or it was written by an import and not touched by a person since (`by` starts with `import:`, `verified = unverified`, `restored_from_version = null`). Any other differing field is left unchanged and reported as a **conflict** with the reason `manual` (set in the app, accepted from a proposal or chosen in a merge), `seed`, `verified` or `restored` in the dry run and the result; imports raise no proposals. A row that changes `in_paper_scope` must carry a `scope_note` (the scope rule, §7); when the imported note equals the current one or is a conflict, the current note goes along unchanged (as with the seed), so a conflicting note is never written.
- Empty cells never clear a field. A row matched by `key_field` updates that record (a deleted match → row error `entity_deleted`); a row without a match creates a record (rows of an import without `key_field` always create).
- Each row is its own write unit; a row that fails validation (§7) is reported and skipped, the others proceed. A row without differences writes nothing, so running the same import again writes 0 revisions.

### 17.2 Manual documents

- **Created from a snapshot** (an upload or a manual fetch, `docs/COLLECTORS.md` §10) on channel `ui`: the values the person submits get `src = manual`, locked. The server's suggested values (title, language, publisher) are only defaults in the form; they become values when the person submits them. The domain layer sets, on this create path only, the system fields `source_id = manual`, `raw_snapshot_id` = the snapshot, `text_hash` from the extracted text (§15.6) and `extraction_method` (`pdf` · `docx` · `html` · `txt` · `none`); `retrieved_at` is the fetch time for a fetched snapshot and the person's value for an upload (required with a `url`, §3.4). An archived copy also gets `archive_urls` = [the capture URL] (`docs/COLLECTORS.md` §10.3).
- `canonical_url` uniqueness (§7) applies: adding a URL that a live document already has → `409 unique_violation` with a link to it.
- A later collector run that matches a manual document (§15.3) treats it like any record: its fields are locked, so differences become proposals, a new text becomes one text-version proposal (§15.6), and its `source_id` never changes.

## 18. Merging duplicates (Phase 2)

`merge(entity_type, survivor_id, merged_id, field_choices, note, proposal_id=None)` and `unmerge(merged_id, note)`, endpoints in API §7.6, channel `merge` (`Actor.merge()`).

- **Types:** project and service (merging organisations and components is deferred, `docs/COLLECTORS.md` §14). Both records live, distinct and of the same type; otherwise `409 invalid_state`.
- **One transaction** (all or nothing) with one new `batch_id`; every changed curated row gets its own revision on channel `merge` with that `batch_id` (and `proposal_id` when the merge accepts a `possible_duplicate` proposal).
- **Field values:** for each tracked editable field, `field_choices[field]` is `survivor` (default), `merged` or, for list fields, `union` (the survivor's items, then the merged record's items not yet present). A value taken from the merged record, or a union, is written to the survivor as the person's choice: `src = manual`, `by = user`, `locked = true`, verification reset (§5); `field_meta` entries are never copied, so the survivor never claims evidence of another record. Validation applies to the result (e.g. the survivor keeps its own `slug`). The survivor's revision has action `merge`.
- **Repointing** (only live referencing rows; deleted rows keep their reference): the references held in editable fields move to the survivor: `service.project_id` and `service.parent_service_id`, `event.subject_id`, `participation.subject_id`, `relation.from_id` and `to_id`, `indicator.subject_id`, and document links (a document that links both keeps one link, to the survivor, with the stronger state, `confirmed` > `rejected` > `suggested`, and origin `manual` if either link was manual). **Evidence and comments stay on the merged record** (their `subject_id` is create-only); its page shows them under the "Merged into" banner. Phase 3 reads resolve such evidence instead of moving it: the survivor's `evidence_count` counts it (§2.4), evidence `subject_current_id` names the survivor (§3.5), and the survivor's evidence panels and the exports use that field; an unmerge needs no change. Field evidence still supports the value of the record it was captured for: coverage counts it for that record only (`docs/API.md` §8.6), verifying a field of the survivor needs the survivor's own evidence (§6.4), and the evidence page compares its `value_snapshot` with the survivor's value (`docs/UI.md` §9.3). **Observations keep their subject**; runs follow `merged_into` (§15.3). Open proposals of the merged record become `superseded` ("merged into …"). Derived values of both records are recomputed.
- **Refused** with `409 merge_conflict` and the list of conflicts, changing nothing, when repointing would break a rule: a relation between the two records (it would point to itself), a service whose new parent would create a cycle or lie in another project, services of the merged project or service that would end up in a different project than their parent, or a unique constraint.
- A project merge moves each service family (a service with its sub-services) together, so the service rules (a sub-service lies in its parent's project) hold at every step. The survivor gets a revision only when its fields change.
- **The merged record** is soft-deleted with `merged_into = survivor_id` (revision action `merge`). **`merge_log`** records the choices and every change with its before and after value (§14.7; a document-link change is logged per document as the subject's link object before and after).
- **Unmerge** reverses a merge in one transaction with a new `batch_id` (channel `merge`, action `unmerge`): it clears the merged record's `deleted_*` and `merged_into`; it moves every reference logged in `merge_log.changes` back where the field still holds the logged `after` value (other rows are reported as `skipped`, with their current value); it restores the survivor's fields that the merge changed and that still hold the merge's value (`src = manual`, channel `merge`); and it sets `merge_log.unmerged_at` and `unmerge_batch_id`. Proposals the merge superseded stay closed (later runs may raise new ones). A plain undelete of a merged record is refused (§6.4).

## 19. Phase 3 overview and migration `0003`

Phase 3 (analysis) adds evidence anchored in document texts (§20), reading, screening and coding in the document view (§21), usable analysis records for D2–D4 (§22), computed periods and new derived and virtual fields (§3, §8.3, §8.4), exports built on request (§23), the timeline and the dashboard (`docs/API.md` §8, `docs/UI.md` §9) and, optionally and last, the Telegram collector C7a (`docs/COLLECTORS.md` §15). Everything still goes through the one write path (§6); nothing in Phase 3 writes curated data outside it. The required backend tests are listed in §24.

### 19.1 Migration `0003`

`backend/migrations/versions/20261031_0003_analysis.py`, `down_revision = "0002"`:
- **New columns**, each added with a plain `ALTER TABLE … ADD COLUMN` (`op.add_column` outside batch mode, as `0002` did, so no curated table, partial index or trigger is recreated):

  | Table | Column | Type |
  |---|---|---|
  | `evidence` | `codes` | JSON NOT NULL DEFAULT `'[]'` |
  | `participation` | `start_basis`, `end_basis`, `period_text` | TEXT NULL |
  | `indicator` | `as_of_basis`, `value_text` | TEXT NULL |
  | `derived` | `portfolio_entry_basis` | TEXT NULL |
  | `derived` | `entry_period` | TEXT NOT NULL DEFAULT `'unknown'` |
  | `derived` | `entry_period_reason` | TEXT NULL DEFAULT `'no_date'` |

- **New indexes** `ix_evidence_document_id` and `ix_participation_role` (§12). No new table.
- **Recompute:** it deletes the `app_state` row `derived_inputs_hash`. The portfolio roles arrive only with `mdt seed` (§19.2), so the full recompute that `mdt db upgrade` runs right after the migration finds none and leaves every portfolio entry empty (`entry_period = unknown`); the seed's writes of the `participation_role` terms recompute again (§8.1), so `portfolio_entry`, `portfolio_entry_basis` and `entry_period` are right once `mdt seed` has run. The entrypoint, `make dev`, the E2E servers and the migration test run both (§24).
- It alters neither `revision` nor `raw_snapshot`. Its downgrade drops what it created (the columns in batch mode).
- The registry fields of the new columns are tracked, so revisions written after the migration record them, and older snapshots show them as *not recorded* (§6.3).

### 19.2 Codebook changes

`mdt seed` loads (format §9, content CODEBOOK §3):
- **`codebook/dimension.yaml`:** vocabulary `dimension` (`multi: false`, `fixed_codes: true`), the four dimensions of the paper's analytical framework (Table 1): codes `d1`…`d4`, `label_en` the dimension's name and `definition` its "analytical focus" questions, both verbatim from the paper, and `attributes = {target: "dimension:Dn", theoretical_source: "<the Table 1 column, verbatim>"}`. Evidence targets keep the form `dimension:D1`…`D4` (§3.5); term `dn` labels target `dimension:Dn`.
- **`codebook/analysis_code.yaml`:** vocabulary `analysis_code` (`multi: true`, `fixed_codes: false`) with **no terms** (`terms: []`): the team's analysis codes for the dimensions, added on the Codebook page or from the capture panel while coding (CODEBOOK §2.10). Each term needs `attributes.dimension` (§7).
- **`codebook/participation_role.yaml`:** the attribute `portfolio_role: true` on `initiator`, `owner` and `operator`, the roles that decide the portfolio entry (§8.3 item 6). The team can change it on the Codebook page (it recomputes the derived values, like `counts_as_modification`), e.g. when decision D-10 adds `coordinator`.
- **`codebook/derived_reason.yaml`:** the definitions of `no_date` and `imprecise_date` take the Phase 3 text of CODEBOOK §3, which also covers `entry_period_reason`, and the description names that field.

### 19.3 Registry changes (summary)

| Change | Where |
|---|---|
| Table types: + component, participation, relation, indicator, evidence | §3.5 |
| Virtual `evidence_count`, counting the evidence of records merged into a record | §2.4 |
| Project and service: derived `entry_period`, `existed_before_invasion` and the filter-only reason fields; virtual `period_unevidenced`, `derived_unevidenced`, `entry_unevidenced`, `adaptation_relation`; project virtual `services_new_in_war`, `services_adapted_in_war` | §3.1, §3.2, §8.3 |
| Computed `period` of events, documents and participations; evidence `document_period`, `case_period` | §8.4 |
| Document `source_id` filterable; virtual `citation_count`, `dimension_citation_count` | §3.4 |
| Participation `start_basis`, `end_basis`, `period_text`; indicator `as_of_basis`, `value_text`; evidence `codes` and the read-only `subject_current_id`, `dimension`, `case_id`; evidence `char_start`, `char_end` become system fields; evidence `subject_id` no longer accepts vocabulary terms and saved views | §3.5, §7, §20 |
| Quick filters of the new table types, new toggles, event and document period chips | `docs/API.md` §3.1 |

## 20. Evidence anchored in document texts (Phase 3)

### 20.1 Text versions, anchors and offsets

- A document's **text version** is the `document_text` row named by its `text_hash` (immutable and content-addressed, §4, §15.6) together with the document's `raw_snapshot_id`, `retrieved_at` and `extraction_method` while that version was current. Every version a document ever had stays recoverable: its revisions record each `text_hash`, and `document_text` rows are never deleted (§21).
- **Anchored evidence** cites one passage of one text version: `document_id`, `text_hash`, `char_start`, `char_end` and `quote`, with **`quote == text[char_start:char_end]`** of that version.
- **Offsets** count **Unicode code points** (Python `str` indices) from the start of the stored text (`document_text.text`: NFC, LF line ends, §15.6); `char_start` is inclusive, `char_end` exclusive. Browsers count UTF-16 code units, so the frontend converts (`docs/UI.md` §9.2); texts with characters outside the Basic Multilingual Plane (e.g. emoji in Telegram posts) are the case that differs.
- Evidence without `text_hash` is not anchored: a URL citation (with `retrieved_at`, optional `archive_url`), a C5 archive capture, a citation of a whole document without a quote, or a citation of a document that has no text (its quote, typed by the person, cannot be checked; §7, citing a document).

### 20.2 Capture

`capture_evidence(…)` (`mdt.domain.anchoring`; API `POST /api/evidence/capture`, `docs/API.md` §8.3) runs **one write unit** (§6.1, all or nothing) on channel `ui`; its revisions share one new `batch_id`. Steps:
1. **Subject**, one of:
   - **a new record** (`record = {type, data}`, type `event`, `participation`, `relation`, `indicator`, `component` or `organization`): created through `apply_change` exactly as by `POST /api/entities/{type}`; it becomes the evidence's subject;
   - **an existing live record** (`subject_id`; 409 `reference_deleted` for a deleted one, §7), optionally with **`values`**: fields of the subject, written first through `apply_change` exactly as by `PATCH` (channel `ui`, `src = manual`), so a person codes a field from the passage and cites it in one step. `values` given with a `field:<name>` target must contain that field (else 400 on `values`).
2. **The source**, one of:
   - **a passage** (`document_id`, `text_hash`, `char_start`, `char_end`, optional `quote`): the document must be live (else 409 `reference_deleted`) and have a text (else 400 on `document_id`); `text_hash` must be the document's **current** `text_hash` (else 409 `invalid_state {state: "text_changed", text_hash: <current>}`), so a text that a collector replaced while the person was reading never shifts a quote; `0 ≤ char_start < char_end ≤ char_count`; the slice must not start or end with whitespace (`str.isspace`; 400 on `char_start` or `char_end`) and has at most 1 000 characters (400 on `char_end`). The domain layer sets `quote` = the slice; a `quote` in the request must equal the slice after the normalisation of §1.2 (else 400 on `quote`: "does not match the document text at these offsets"), which catches offset mistakes of a client. It also sets `raw_snapshot_id` and `retrieved_at` to the document's current values (the time the quoted text was retrieved, never the time of capture; a `retrieved_at` in the request → 400);
   - **a whole document** (`document_id` alone, optional `quote`): the rule of §7 for citing a document: `retrieved_at` and `raw_snapshot_id` come from the document; a typed quote on a document with a text must occur in it exactly once and is then stored as that passage, anchored; without a quote the row cites the document as a whole;
   - **a URL** (`url`, `retrieved_at`, optional `archive_url` and `quote`): the ordinary rules of §7.
3. **The evidence row** (`target` default `entity`; `codes`, `locator`, `description`) is created through `apply_change` and validated by §7 (target, codes, `value_snapshot`). The values of step 1 are written before it, so `value_snapshot` holds the value the passage was captured for.
4. **Optional field verification** (`verify_field: true`, only with `target = field:<name>`): the field is marked verified with the new row (§6.4) in the same unit; an empty field or a target that is not a field → 400 on `verify_field`. A verification needs a quote (§5), so a citation without a quote cannot verify a field.

A failure in any step writes nothing. Field provenance is that of channel `ui` (`src = manual`, `by = user`) for every value of the unit, the domain-set anchor values included. **Capture never changes the document's links**; the document view asks the person to confirm or add the link to the citation's case first, as a write of its own (`docs/UI.md` §9.2).

### 20.3 Anchored evidence afterwards

- **Frozen anchor:** on anchored evidence, a PATCH or bulk edit that changes `document_id`, `char_start`, `char_end`, `quote` or `retrieved_at` → 400 `validation_error` on that field ("anchored evidence: capture the passage again"); `text_hash` and `raw_snapshot_id` are system fields anyway. `target` and `subject_id` are create-only (§3.5). `codes`, `locator`, `description`, `notes` and `verification_status` stay editable.
- **Restore** treats the anchor as one unit, like a document's text version (§6.4): restoring a version whose anchor differs restores `text_hash`, `raw_snapshot_id`, `retrieved_at`, `char_start`, `char_end` and `quote` together (listed in `changes`), and none of them alone; every earlier anchor was valid for its own text version, which still exists.
- Deleting evidence that a field verification rests on stays refused (§6.4).

### 20.4 Text changes

- When a document gets a new text version (a collector's direct write, an accepted text-version proposal, a restore; §15.6), its anchored evidence **keeps pointing at the version it quotes**: the quote stays true of the text the person read, and that `document_text` row remains. Nothing is moved automatically.
- The UI tells evidence on the **current** text version (its `text_hash` is the document's) from evidence on an **earlier** one by comparing the two hashes (`docs/UI.md` §9.2); the evidence page shows an earlier passage in the text of its own version (API §8.2). If the passage still makes its point in the new text, the person captures it there anew. Moving evidence to a new version by hand ("re-anchoring") is deferred (`docs/COLLECTORS.md` §14).

### 20.5 Dimensions, analysis codes and cases

- `target = dimension:Dn` cites a passage for dimension Dn of the paper's analytical framework (vocabulary `dimension`, §19.2; coding rules CODEBOOK §2.10). It is thematic coding of a document passage, separate from evidence for a field (`field:d1_need` supports the value of that field). The read-only evidence field `dimension` holds `dn` for such rows.
- `codes` (vocabulary `analysis_code`) refines a dimension citation with the team's own codes; it is optional, and the vocabulary starts empty, because the paper and the codebook draft define no codes below the four dimensions. Validation: §7 (Phase 3). The UI offers only active codes of the target's dimension and lets the person add a code without leaving the page (`docs/UI.md` §9.2).
- The **case** of an evidence row (`case_id`, read-only, §3.5) is the project or service it concerns: its current subject (`subject_current_id`) if that is a project or service; otherwise the project or service named by that subject's `subject_id` (event, participation, indicator) or, for a relation, its `from_id`, or its `to_id` when `from_id` is no project or service, followed along `merged_into`; else none (organisations, components, documents). With `dimension` and `document_period` it lets tables, the dashboard and the QDA corpus compare codings across the periods, by the date of the document and by the case (§8.4, `docs/API.md` §8.8.3).

### 20.6 Earlier evidence

Evidence written by accepting a `create_event` proposal of the tagger (§16.4) carries `document_id`, `text_hash`, offsets and the sentence as `quote`: it is anchored, the accept takes the quote from the stored slice (§7), and it follows §20.3–§20.4 (tagger quotes end without whitespace, §15.9). C5's evidence (`url`, `archive_url`, no `text_hash`) is not anchored. `mdt check` verifies every anchor (§13, kind `evidence_anchor`).

## 21. Reading, screening and coding documents (Phase 3)

- **Text versions:** a `text_hash` is a text version of a document when one of the document's revision snapshots records it. `GET /api/documents/{id}/text?text_hash=` serves any of them (API §8.2), and an anchor must name one (§7, §13).
- **Screening** writes `screening_status`, `screening_reason` and `screening_note` through PATCH on channel `ui`, with the rules of §7 (CODEBOOK §2.8, D-13): `excluded` needs a reason in the same change; a change back to `included` or `unscreened` clears the reason in the same change (the UI sends `screening_reason: null`). Every decision is a revision, so the screening flow of any past state can be reproduced from the history.
- **Queue:** the person works through a *queue*, a documents list query (filters, `q`, `sort`; API §4), kept in the document view's URL. The neighbours of a document are its predecessor and successor in the queue's order, where the queue is evaluated as `(<filters and q>) OR id = <current>`, so the current document keeps its place after screening or coding removed it from a filtered queue (e.g. a queue of unscreened documents). The **next unscreened** document is the first one after the current one in queue order with `screening_status = unscreened`, else the first such one before it (wrap-around), else none (API §8.2).
- **Coding:** a document counts as coded once a live evidence row cites one of its passages for a dimension (`dimension_citation_count` ≥ 1, §3.4). The dimension coding is the document analysis (CODEBOOK §2.10); citations for a record or a field, such as the sentence of an accepted event proposal or the evidence of the document's own date, do not code a document. The included documents that are not coded yet form a queue like any other (`f.screening_status=in:included&f.dimension_citation_count=eq:0`): a document that gets its first dimension citation keeps its place, and Next goes on to the next uncoded one.
- **Links and proposals** in the document view use the Phase 2 rules: links are confirmed, rejected or added through the document's `links` field (§15.8); proposals concerning the document (`create_event` proposals that cite it, duplicates, text versions; API §8.4) are decided by §16.4.

## 22. Analysis records (Phase 3)

### 22.1 Organisations

The focal organisation (§3.5) anchors `portfolio_entry`. In Phase 3 organisations are also created from the participation forms (`docs/UI.md` §9.3) and from passages (§20.2). Merging organisations is deferred (`docs/COLLECTORS.md` §14): a duplicate is resolved by moving its participations (and documents' `publisher_org_id`) to the other organisation and deleting it; its evidence stays with it.

### 22.2 Participations (D3)

- One row records one organisation's `role` in one subject (project, service or component) for one period (`start`, `end` with their bases and the verbatim `period_text`). A change of role or a gap is a new row; an open-ended participation has no `end`. Its computed `period` is that of its `start` (§8.4).
- The focal organisation's participations in a portfolio role (§8.3 item 6) decide `portfolio_entry` and `entry_period`; disputed or deleted ones are ignored (§8.2). The timeline draws them as portfolio bands (API §8.5).
- Their sources are evidence rows with the participation as subject.

### 22.3 Components (D2)

Platforms or infrastructure that are not portfolio projects (§3.5). Evidence is optional, as for events: the create forms offer it (`docs/UI.md` §9.3), and it can be captured later. A component can be the subject of events, participations, indicators and evidence and an end of relations.

### 22.4 Relations (D2, D4)

- Read as "from — type — to" (CODEBOOK §3). `extends`, `builds_on` and `successor_of` are the structural sign of adaptation (CODEBOOK §2.5), `recombines` marks combinatorial innovation (D4).
- **No duplicates:** a second live relation with the same (`from_id`, `to_id`, `relation_type`) → 409 `unique_violation` `{field: "to_id", existing}`, checked inside the write transaction on create, PATCH, restore and undelete (a domain check, no database index, so earlier rows never block the migration).

### 22.5 Indicators

Reported values from sources (`metric`, `value`, `unit`, `as_of` with `as_of_basis`); the app never computes an indicator. `value` is the number as stated; a qualifier ("more than", "about", "up to") stays in `value_text`, verbatim together with the number (CODEBOOK §2.6). `metric` and `unit` are free strings; `GET /api/indicators/metrics` lists the values in use so that forms reuse them (API §8.9). The create form requires evidence (`docs/UI.md` §9.3); the indicators table has the quick filter "No evidence".

## 23. Exports (Phase 3)

### 23.1 Kinds

| Kind | What | Format |
|---|---|---|
| `dataset` | the curated dataset with derived values, field provenance with licences, source observations, merges, the source register, the codebook with the coding rules, and a manifest | `docs/API.md` §8.8.2 |
| `qda` | the corpus for qualitative analysis: texts of the included documents, metadata, cases, links, codings and the codebook | `docs/API.md` §8.8.3 |
| codebook | the vocabularies of the working copy as Markdown or CSV | `docs/API.md` §8.8.4 |

All three are built on request (§23.4). The dataset bundle is the content that Phase 4 releases freeze and tag (`PLAN.md` §6.7); the view exports of API §5 are unchanged.

### 23.2 Content policy (decision D-5, proposed default)

- **Dataset:** the live records of the ten table types and the document links; the derived values (prefixed `derived_`); the field provenance of every exported value with the licence that applies to it (a document's fields: the document's `license`; other collected values: their collector's licence; `docs/API.md` §8.8.2); the source observations (keys, labels, URLs and crawl times, marked as crawl times, never dates of an initiative, §2.4); the merge log; the source register (collectors with their SOURCES IDs and licences); the codebook with the coding rules (`docs/CODEBOOK.md`); and the manifest. **Excluded:** deleted and merged records (evidence of a merged record names its survivor in `subject_current_id`, §18); comments and the comment and proposal counts; proposals; raw snapshots and their bodies (field provenance names a snapshot by ID, URL and retrieval time only); run, fetch and import logs; saved views; and **every document full text**. Evidence quotes (at most 1 000 characters each, chosen by the person) are included, also from sources that are not openly licensed, and so are collected text fields of such sources (e.g. service descriptions); the licence recorded with each value (a quote: its cited document's `license`, a column of `csv/evidence.csv`) lets a Phase 4 release filter them (D-5). Values that a person, the seed or an import wrote on records other than documents record no source licence, and the README says that they can still contain source text.
- **QDA corpus:** only documents with `screening_status = included`, with the full texts of every licence: an **internal** working corpus, marked so in its README and manifest, never published (D-5). It holds the current text of each document and every earlier text version that one of its codings quotes.
- A reference to a record outside the bundle (deleted, merged, or a document that is not included) keeps its ID and label; the manifest counts such references per field (`references_outside_bundle`), and the QDA manifest counts the codings of documents that are not included (`codings_outside_corpus`, by screening status).

### 23.3 Privacy guard

- **At write time:** values that contain a client identifier are refused on every channel (§7, Phase 3), and `mdt check` reports older ones (§13, kind `client_identifier`), so no table, view export, timeline figure or crosstab file can carry them.
- **At export time** (a backstop): before a bundle or a codebook file is delivered, every file is decoded as UTF-8 (an XLSX file: every XML part inside it) and checked for the configured `CONTACT_EMAIL` (case-insensitive), the User-Agent product token `MDT-Portfolio-Research` and the bot-manager token marker `__uzdbm`. The address is checked only when `CONTACT_EMAIL` is set and not blank after trimming; otherwise the manifest records that check as `not_checked`, never as passed. A hit fails the export (API `409 privacy_check_failed {file, record_id}`; the CLI prints `error: …` and exits 1) and nothing is delivered; the person removes the value (`mdt check` names the record and field) and exports again. A stored text cannot be edited: the person excludes or deletes the document (`mdt check` names it) and adds a redacted copy as a new manual document.

### 23.4 Building an export

- **On request:** `GET /api/exports/dataset`, `GET /api/exports/qda` and `GET /api/codebook/export` build the file inside the request (API §8.8.1); `mdt export` writes it to a directory or file (API §8.10). There is no job table and no queue: the app has one user (D-15), and two requests simply build two files.
- **Steps:** check that the derived values are current (§8.1: the stored `derived_inputs_hash` equals the hash of the current inputs; else `409 invalid_state {state: "derived_out_of_date"}`, "run mdt recompute"); open one read transaction; write the bundle to a temporary file in `DATA_DIR/exports/.tmp/`; run the privacy guard; stream it (server) or move it into the output directory (CLI, default `DATA_DIR/exports/`); delete the temporary file, also after a failure (a file left behind by a crash is removed by a later build once it is older than a day; younger files may belong to a build that is still running).
- Each bundle gets an export ID `exp_<ULID>` and its creation time, recorded in its `manifest.json` and `README.md` only.
- Exports only read curated data, so they run while a collector run writes (WAL).

### 23.5 Consistency and reproducibility

- An export reads everything in **one read transaction** (a consistent WAL snapshot), so a collector writing meanwhile cannot mix two states into one bundle.
- **Data revision:** a data state is stamped as `data_revision` = the highest `revision.id` and `data_as_of` = that revision's `at`, read in the same transaction as the data. Revisions are append-only and every change of curated data writes one (deletions, restores and vocabulary terms included), so the stamp moves with every change and identifies the curated state. The manifest, `GET /api/stats`, the timeline, crosstab and coverage responses and the codebook export use this one definition (`docs/API.md` §8), so a figure or table can be matched to a bundle with the same `data_revision`. Derived and computed values also depend on the cut-off dates of `parameters.yaml` and on the derivation code, which can change without a revision (a recompute writes none), so figures and crosstab files print the cut-off dates and the app version next to the data revision, and the manifest records both together with `derived_inputs_hash` (§8.1).
- **Deterministic data files:** rows sorted by `id`; columns in registry order; JSON with sorted keys, `ensure_ascii=False`, written as a stream; CSV as in API §5; ZIP entries in a fixed order with the fixed timestamp 1980-01-01 00:00:00. Two exports of an unchanged database by the same code version give byte-identical files (`dataset.json` included, which holds no export ID or time), except `manifest.json`, `README.md` (export ID and time), `SHA256SUMS` and `dataset.xlsx` (openpyxl writes the time into the workbook, and its README sheet holds the export ID); the XLSX file is a convenience copy of the CSV files, covered by its SHA-256 in the manifest like every file (§24).
- The manifest records the code version, the schema revision, the codebook parameters, `data_revision`, `data_as_of`, `derived_inputs_hash`, counts per type and status, every file with its size, SHA-256 and row count, and the collector runs and imports that the exported field provenance names (API §8.8.2).

## 24. Phase 3 backend tests

Required pytest coverage, offline and on databases created with `alembic upgrade head` (§11 item 5), in addition to the tagger and collector tests of `docs/COLLECTORS.md` §15.4; the frontend tests and E2E scenarios are in `docs/UI.md` §9.8.
- **Migration:** `tests/test_migration_0003.py` upgrades a `0002` database with rows (including a participation of the focal organisation as operator), checks the new columns and their defaults, then runs the seed (§19.1) and checks that `portfolio_entry` and `entry_period` are filled (`portfolio_entry_basis` stays null: the participation has no `start_basis` yet), and downgrades.
- **Capture:** on a text with Cyrillic and an emoji, the code-point slice equals the stored quote; every 400 path (whitespace at an end, an empty or over-long slice, a quote that does not match the offsets, a given `retrieved_at`, codes without a dimension target, `verify_field` on an empty field, `values` without the target field); 409 `text_changed`; a failing verification rolls back the record and the evidence; `values` are written before the evidence, so `value_snapshot` holds the new value; `retrieved_at` and `raw_snapshot_id` of a document citation come from the document on every channel (the document case of the Phase 1 test `test_evidence_retrieved_at_defaults_to_now_on_channel_ui_only` changes accordingly); a typed quote on a document with text found once is anchored, found twice or not at all → 400; capture leaves the links unchanged.
- **Anchors:** the frozen-anchor PATCH refusal; restoring an anchor as a unit; accepting a `create_event` proposal whose sentence is longer than 1 000 characters with a space at the cut gives an anchor that passes `evidence_anchor`; `evidence_anchor` reports a quote mismatch and a `text_hash` that is not a version of the document.
- **Rules:** evidence codes (dimension match; inactive codes kept, and restored with a warning); the `analysis_code` attribute freeze; participation and indicator bases; duplicate relations on create, PATCH, restore and undelete; client identifiers refused on every channel, in field values and in document texts, and reported by `client_identifier`; click identifiers removed from URLs; evidence subjects of the nine allowed types only.
- **Derived and computed fields:** `portfolio_entry` and `entry_period` follow the `portfolio_role` attribute (a changed attribute recomputes); `existed_before_invasion`, the reason fields, `period_unevidenced`, `derived_unevidenced`, `entry_unevidenced`, `services_new_in_war`, `adaptation_relation`; filter, sort and facet on the computed `period` of events, documents (an archive-bound date included) and participations and on evidence `document_period`, `case_period`, `dimension` and `case_id` (a relation from a component takes its `to_id`); `subject_current_id` and `evidence_count` across a chain of merges, and coverage's `with_evidence` counting a merged record's field evidence for that record only; `citation_count` and `dimension_citation_count`; `GET /api/stats` reports `derived_current: false` after `parameters.yaml` changes.
- **Document text and queue:** `GET /api/documents/{id}/text` with its marks (evidence and open proposals of that version only), an earlier version by `text_hash` and 404 for a hash that is no version of the document; `/neighbours` with the `OR id = <current>` position, `next_unscreened_id` with wrap-around and the totals; `GET /api/proposals?document_id=`; `GET /api/indicators/metrics`.
- **View exports** of the five new table types: the column rules of `docs/API.md` §5 (`derived_entry_period` with `_label` and `_reason`, `derived_portfolio_entry_basis`, `derived_existed_before_invasion`, the computed periods with `_label` only, the virtual refs `subject_current_id` and `case_id` and the virtual `dimension` with `_label`); the filter-only reason fields refused in `cols`.
- **Timeline:** order, domain, `counts.by_period`, the portfolio bands, the evidence filter and the limits.
- **Crosstab and coverage:** every cell count equals the total of the list query that its row and column filters give (vocab, vocab_list, bool, ref and `(empty)` rows); coverage counts against `field_meta`.
- **Exports:** every file of a bundle matches `SHA256SUMS`; two exports of an unchanged database differ only in `manifest.json`, `README.md`, `SHA256SUMS` and `dataset.xlsx`; `dataset.json` holds no document `text` key, and no file of the dataset bundle contains a stored document text longer than 1 000 characters (documents of every licence); the content-policy exclusions; the licences of field provenance (a document's fields take the document's `license`, a manual value of another record none) and of `evidence.csv`; a privacy-guard hit gives `409 privacy_check_failed` and leaves no file; an unset or blank `CONTACT_EMAIL` is recorded as `not_checked`; out-of-date derived values give 409; the QDA corpus writes the BOM, code-point offsets that hold for the file content after the BOM, the earlier text versions its codings quote and the count of codings outside the corpus; the codebook export is byte-identical for an unchanged data revision; the CLI (`mdt export dataset|qda --out DIR` writes the ZIP into `DIR` and prints its path, ID and SHA-256; `mdt export codebook` writes to standard output or `--out`; a privacy-guard hit or out-of-date derived values exit 1 and leave neither an output file nor a file in `.tmp/`).
