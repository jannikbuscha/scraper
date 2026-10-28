# Data model

> **Status:** v1 contract for Phase 1, revised 2026-10-28 after a five-lens contract review. Implementations must follow this document. Deviations must be agreed and the document updated in the same change.
> **Related:** `PLAN.md` §4 and §6 (rationale), `docs/API.md` (HTTP interface), `docs/UI.md` (frontend), `docs/CODEBOOK.md` (vocabularies and coding rules).

## 1. Conventions

### 1.1 Identifiers, time and dates

| Topic | Rule |
|---|---|
| **IDs** | Prefixed ULIDs as text primary keys: `<prefix>_<26-char ULID>`, e.g. `prj_01JBX3…`. The prefix determines the entity type (§3). IDs are never reused or regenerated. |
| **Timestamps** | UTC. Every timestamp comes from one helper, `utc_now()` = `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")`, and is stored as TEXT through a `UtcTimestamp` type that accepts only aware UTC datetimes or exactly this pattern. There is no `server_default` and no SQLite date function. One write unit uses a single timestamp for `updated_at`, every `field_meta[*].at` and `revision.at`. "Newest first" for revisions means `ORDER BY revision.id DESC`. |
| **Calendar dates** (type `date`) | TEXT `YYYY-MM-DD`. Publication dates are calendar dates in Europe/Kyiv. |
| **Partial dates** (type `partial_date`) | Canonical strings only: `YYYY`, `YYYY-Qn` (uppercase `Q`, n = 1–4), `YYYY-MM`, `YYYY-MM-DD`; years 1900–2100. Anything else, e.g. `2022-q1` or `2022-02-30`, is rejected. Storage: three columns `<name>_start`, `<name>_end` (inclusive, `YYYY-MM-DD`) and `<name>_precision` (`day`, `month`, `quarter`, `year`), all derived from the string. |
| **Booleans** | SQLite integer 0/1, API `true`/`false`. |
| **Soft delete** | `deleted_at`/`deleted_by` set, row kept. Default queries exclude deleted rows. |
| **Versions** | `version` starts at 1 on creation and increases by exactly 1 per revision of the row. |

### 1.2 Normalisation

These rules apply to every channel, before validation, comparison (no-op detection) and storage:

| Type | Rule |
|---|---|
| `string`, `slug` | NFC; trim; `''` → null; any C0 control character → 400. |
| `url` | Trim; `''` → null; any whitespace or C0/C1 control character → 400; scheme `http` or `https` (case-insensitive, stored lowercase); non-empty host; **no userinfo** (`https://a@b/` → 400); host stored IDNA-encoded (punycode); ≤ 2 000 characters. The same rule applies to URLs inside `json` fields (e.g. `source_categories[].url`) and on every channel. |
| `text` | NFC; CRLF and CR → LF; trim; `''` → null; C0 control characters other than tab and newline → 400. |
| `url_list`, `string_list`, `vocab_list` | Column `NOT NULL DEFAULT '[]'`; API null → `[]`. Elements are normalised like their scalar type; empty elements are dropped; duplicates are removed, keeping the first occurrence. **Order is significant**: the first element is the main value (CODEBOOK §2.3), and a reorder is a change. |
| `alias_list` | Items become full objects `{text, lang, case_sensitive, kind, exclude_patterns}` with defaults (`case_sensitive: true`, `kind: "name"`, `exclude_patterns: []`, normalised like `string_list`). Duplicates are items with the same (`text`, `lang`); the first is kept. `exclude_patterns` are **literal phrases** (never regular expressions), matched on normalised text. |
| `doc_links` | Sorted by `subject_id`; at most one link per subject; read-only keys are ignored on input. |
| `json` | Compared by canonical serialisation (sorted keys); stored as given. |

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
| `doc_links` | object[] | table `document_link` | items `{subject_id, origin: "auto"|"manual", state: "suggested"|"confirmed"|"rejected"}` plus read-only `matched_aliases`, `match_count`, `snippet` |

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
- `sortable`, `in_list` (default table column), `bulk_editable`, `help` (tooltip text from the codebook).

Meta also exposes `default` (e.g. `in_paper_scope: false`, `verification_status: "unverified"`, `screening_status: "unscreened"`, `active: true`) and `in_create` (offered in the create form). Each type lists its constraints, e.g. `{"one_of_required": ["name_en", "name_uk"]}`.

- **All stored fields are tracked**, including read-only system fields, except `seed_key`.
- **Rule:** every field with filter `multiselect` is sortable; a backend test asserts this for the whole registry.

### 2.3 Common columns of curated entities

Every curated entity table (all tables in §3) has these columns:

| Column | Type | Tracked | Notes |
|---|---|---|---|
| `id` | TEXT PK | — | prefixed ULID |
| `version` | INTEGER NOT NULL | — | optimistic locking |
| `created_at`, `created_by` | TEXT | — | `created_by` = author name, `seed`, `import:<file>` or `collector:<name>` |
| `updated_at`, `updated_by` | TEXT | — | |
| `deleted_at`, `deleted_by` | TEXT NULL | state | soft delete |
| `merged_into` | TEXT NULL | state | ID of the surviving entity after a merge (Phase 2); a merge always also sets `deleted_at` |
| `verification_status` | TEXT NOT NULL DEFAULT `unverified` | ✓ | record-level review status (§7); vocabulary `verification_status`; group `basics`; filter multiselect; sortable; in list |
| `notes` | TEXT NULL | ✓ | internal notes; group `sources` |
| `field_meta` | JSON NOT NULL DEFAULT `{}` | — | provenance per field (§5) |

The system columns are also registry fields (read-only, group `system`), so tables can sort, filter, show and export them (e.g. "changed since Monday by Anna", trash sorted by deletion time):
- `created_at`, `updated_at`, `deleted_at`: datetime, filter `date_range`, sortable;
- `created_by`, `updated_by`, `deleted_by`: string, filter `text`, sortable;
- `version`: int, sortable.

### 2.4 Common virtual fields

Every curated type has these virtual fields. They are computed by correlated subqueries and are filterable, sortable and exportable like stored fields; `GET /api/meta` describes them like stored fields.
- **`open_comments`** (int): the number of non-deleted root comments with status `open` on the entity, field-level threads included. Filter `number_range`; sortable; in list for the five table types.
- **`comment_count`** (int): all non-deleted comments on the entity, replies included. Filter `number_range`; sortable.

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

✱ at least one of `name_en`/`name_uk` is required (after normalisation). There is no machine translation; a missing English name stays empty.

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
| derived: `launch`, `existed_by`, `period`, `war_trajectory`, `portfolio_entry` | as for project | | | | W | as for project | ✓ | `launch`, `period` |
| virtual: `project_in_paper_scope` | bool (the project's value) | | | | B | bool | ✓ | |

Constraints: `parent_service_id` must belong to the same project and must not create a cycle.

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
| `source_id`, `external_id`, `raw_snapshot_id`, `text_hash`, `extraction_method` | string | | | system | So | | | |
| `archive_urls` | url_list | | | ✓ | So | | | |
| `license` | vocab | `license` | | ✓ | So | multiselect | ✓ | |
| `screening_status` | vocab (default `unscreened`) | `screening_status` | ✓ | ✓ | B | multiselect | ✓ | ✓ |
| `screening_reason` | vocab | `exclusion_reason` | | ✓ | B | multiselect | ✓ | |
| `screening_note` | text | | | ✓ | B | text | | |
| `links` | doc_links | | | ✓ | So | ref (by `subject_id`) | | |
| virtual: `linked_in_paper_scope` | bool: a confirmed link to an in-scope project or one of its services | | | | B | bool | ✓ | |
| virtual: `text` | text from `document_text` | | | detail only | So | full-text only | | |

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

**The other types** have the generic API only in Phase 1. F, S and L follow the field types: text fields text/S; vocab multiselect/S; refs ref/S (label); partial dates date_range/S.

| Table (prefix) | Fields (type) | Notes |
|---|---|---|
| `participation` (`par_`) | `organization_id` (ref organization, R, L), `subject_id` (ref project/service/component, R, L), `role` (vocab `participation_role`, R, L), `start`, `end` (partial_date, L; `end` ≥ `start`), `description` (text) | for D3 |
| `component` (`cmp_`) | `name_en`/`name_uk` (✱, L), `aliases`, `component_type` (vocab `component_type`, L), `description` (text), `urls` (url_list) | created only from sources |
| `relation` (`rel_`) | `from_id`, `to_id` (ref project/service/component, R, L, distinct), `relation_type` (vocab `relation_type`, R, L), `description` (text), virtual `endpoint` (ref, filter only: matches `from_id` OR `to_id`) | read as "from — type — to" |
| `indicator` (`ind_`) | `subject_id` (ref project/service/component/organization, R, L), `metric` (string, R, L), `value` (number, R, L), `unit` (string, L), `as_of` (partial_date, L), `description` (text) | |
| `evidence` (`evd_`) | `subject_id` (ref any curated type except evidence, R, **create-only**), `target` (string, R, create-only: `entity` \| `field:<field name of the subject type>` \| `dimension:D1`…`D4`), `document_id` (ref document), `url`, `archive_url` (url), `retrieved_at` (datetime; required when `document_id` is null; editable; defaults to now on channel ui), `raw_snapshot_id`, `text_hash` (string, system), `char_start`, `char_end` (int), `quote` (text ≤ 1 000), `locator` (string), `description` (text), `value_snapshot` (json, system: the target field's value when the evidence was created) | `document_id` or `url` is required |
| `vocabulary_term` (`voc_`) | `vocabulary` (string, R, **create-only**), `code` (`^[a-z0-9_]+$`, R, **create-only**), `label_en` (string, R), `label_uk` (string), `definition`, `include_note`, `exclude_note`, `examples` (text), `sort_order` (int), `active` (bool, default true), `replaced_by` (string code; §7), `attributes` (json) | UNIQUE (`vocabulary`, `code`); the vocabulary must exist; terms are never deleted (§7) |
| `saved_view` (`view_`) | `name` (string, R), `entity_type` (string, R, one of the table entity types), `query` (string, R; canonical URL query string without `?`), `description` (text) | visible to everyone |

The UI tables in Phase 1 cover project, service, event, document and organization. Vocabulary terms are edited on the Codebook page. The other types already have the generic API.

## 4. System tables

| Table | Columns | Rules |
|---|---|---|
| `vocabulary` | `name` PK, `label`, `description`, `multi`, `fixed_codes` (bool), `source_file` | Metadata loaded from `codebook/*.yaml` by the seed. It changes only through the YAML files, which are versioned in git; the terms themselves are revisioned in the database. |
| `revision` | `id` INTEGER PK AUTOINCREMENT, `entity_type`, `entity_id`, `version`, `at`, `author`, `channel` (`seed`, `ui`, `collector`, `import`, `restore`, `merge`, `system`), `action` (`create`, `update`, `verify`, `delete`, `undelete`, `restore`, `merge`, `resolve`, `reopen`), `note` (≤ 2 000), `run_id`, `proposal_id`, `restored_from` (revision id), `restored_from_version`, `batch_id`, `schema_revision` (Alembic head at write time), `snapshot` (JSON), `diff` (JSON) | UNIQUE (`entity_id`, `version`). **Append-only:** SQLite triggers abort every UPDATE and DELETE (`RAISE(ABORT, 'revision is append-only')`); see §11 for migrations. |
| `comment` (`cmt_`) | `id`, `subject_id`, `field`, `parent_id`, `body_md`, `status`, `resolved_by`, `resolved_at`, `version`, `created_*`, `updated_*`, `deleted_*` | rules in §6.5 |
| `document_text` | `text_hash` PK (sha256 of the normalised text), `text`, `char_count`, `created_at` | immutable |
| `document_link` | `id`, `document_id` FK, `subject_id`, `origin`, `state`, `matched_aliases` (JSON), `match_count`, `snippet` | UNIQUE (`document_id`, `subject_id`); managed through the document's `links` field and part of its snapshot |
| `derived` | `entity_id` PK, `launch_start`, `launch_end` (the launch interval, §8), `launch_value`, `launch_precision`, `launch_basis`, `launch_event_id` (the displayed candidate), `existed_by`, `existed_by_event_id`, `existed_before_invasion` (bool), `period`, `period_reason`, `war_trajectory`, `trajectory_reason`, `trajectory_event_id`, `portfolio_entry_start`, `portfolio_entry_end`, `portfolio_entry_value`, `portfolio_entry_precision`, `portfolio_entry_participation_id`, `computed_at` | one row per project and service, deleted or not; never edited directly (§8) |
| `search_key` | `rowid` INTEGER PK, `entity_id` TEXT NOT NULL UNIQUE, `entity_type` TEXT NOT NULL | stable integer keys for the FTS tables |
| `fts_entity` | FTS5 (`body`), `rowid` = `search_key.rowid`, `tokenize = "unicode61 remove_diacritics 2"`, `prefix = '2 3 4'` | maintained by the domain layer (§10) |
| `fts_document` | FTS5 (`title`, `body`), `rowid` = `search_key.rowid`, same tokenizer | |
| `app_state` | `key` PK, `value` | e.g. the hash of `codebook/parameters.yaml` and of the modification event types, used to trigger recomputes (§8) |

Later phases add `proposal`, `collector_run`, `fetch_log`, `raw_snapshot`, `source_observation`, `release` and `merge_log` (see `PLAN.md` §4.3) through new migrations.

## 5. Field provenance (`field_meta`)

`field_meta` is a JSON object keyed by field name. There is one entry per tracked field that has ever been set:

```json
{"name_en": {"src": "seed", "by": "seed", "at": "2026-10-28T17:00:00.000000Z", "locked": true, "verified": "unverified", "evidence_id": null, "restored_from_version": null}}
```

| Channel | `src` | `by` | `locked` |
|---|---|---|---|
| `ui` | `manual:<author>` | `<author>` | true |
| `seed` | `seed` | `seed` | true |
| `import` | `import:<file>` | `import:<file>` | true |
| `collector` (Phase 2) | `collector:<name>@<run_id>` | `collector:<name>` | false. A change to a locked field is refused (`LockedFieldError`); the reconciler turns it into a proposal. |
| `restore` | `src` of the restored snapshot's entry, or `manual:<author>` if it has none | `<author>` | true |
| `merge` (Phase 2) | `src` of the chosen value | `<author>` | true |
| `system` | mirrors the source field (e.g. `canonical_url` mirrors `url`) | as the source field | as the source field |

- **Entries are never removed.** Clearing a field (setting it to empty) writes an entry like any other change, so a cleared value stays protected.
- **Exception on create:** fields that are empty on create get no entry.
- **Value changes** set `verified = "unverified"`, `evidence_id = null` and `restored_from_version = null` (a restore then sets it).
- **Restore** sets `verified = "unverified"`, `evidence_id = null`, `restored_from_version = <version>`. A restored value must be verified again.
- **Field verification** (§6.4) sets `verified` and, for `verified`, `evidence_id`; it also sets `locked = true`.
- **`evidence_id` write path:** it is written only by field verification. The evidence rows that target a field (`target = field:<name>`) are its full evidence list.

## 6. Writes

### 6.1 Transactions and connections

1. **Driver mode:** the SQLite driver never begins transactions implicitly. The connect hook sets `isolation_level = None`, executes `PRAGMA foreign_keys=ON; PRAGMA busy_timeout=10000; PRAGMA synchronous=NORMAL`, and registers the SQL functions `mdt_fold` and `mdt_sortkey` (§10). `journal_mode=WAL` is set by `mdt db upgrade` and is persistent.
2. **Write transactions:** every write unit starts with `BEGIN IMMEDIATE` before it reads the row. Write units are: `apply_change`, delete, undelete, restore, field verification, each bulk item, each comment action, each seeded entity. Inside the transaction it re-reads the row and runs the version, lock and validation checks on it. Read-only requests use plain `BEGIN`.
3. **Compare-and-swap:** the row update is `UPDATE <t> SET …, version = :v + 1 WHERE id = :id AND version = :v`; rowcount 0 → `ConflictError`. An `IntegrityError` on `revision(entity_id, version)` also maps to 409 `conflict`, never 500.
4. **JSON columns are never modified in place.** The write path builds a new value (deep copy, change, assign) or calls `flag_modified`. JSON is serialised with `ensure_ascii=False`; nullable JSON columns use `none_as_null=True`.
5. **FastAPI handlers that use the database are plain `def`** (thread pool), never `async def` with a synchronous session.
6. **Required tests:**
   - two connections interleave read and write: one succeeds, the other gets a conflict;
   - after every write action, reloading the row in a new session gives fields and `field_meta` equal to the latest revision snapshot.

### 6.2 One write path

**Channels:**
- Every HTTP write uses channel `ui`; the restore endpoints use channel `restore`. No header, query parameter or body field can select a channel or a `src`.
- The channels `seed`, `collector`, `import`, `merge` and `system` are reachable only from the CLI and in-process jobs.

Every change of a curated entity (including comments, vocabulary terms and saved views) goes through:

`apply_change(session, entity_type, entity_id | None, changes, actor, channel, note=None, expected_version=None, batch_id=None, run_id=None) -> ChangeResult`

1. **Normalise and validate** (§1.2, §7):
   - field names must exist and be writable on this channel: `editable` for `ui`; `create_only` fields only on create; `system` fields never from clients;
   - types, vocabulary codes, references, uniqueness and entity-specific rules.
2. **Create** (`entity_id` is None):
   - new ID, `version = 1`, `created_*` and `updated_*` set;
   - a `field_meta` entry for every provided non-empty field;
   - system fields computed (e.g. `canonical_url`);
   - for project and service, the `derived` row is inserted;
   - revision version 1 with `diff = {"fields": {f: [null, value]}}` for the non-empty fields.
3. **Update:**
   - **Version check:** `expected_version` is required on channel `ui`; seed and collector use the version read inside the transaction. A mismatch → `ConflictError` (§6.5).
   - **Deleted rows:** a deleted row → 409 `entity_deleted`.
   - **Diff:** compare normalised values per field. If nothing differs → **no-op**: no revision, no version bump, `changed = false`.
   - **Write:** apply the values, recompute dependent system fields in the same revision (`canonical_url` follows `url`; its `field_meta` mirrors `url`'s entry), bump `version` (compare-and-swap), set `updated_*`, update `field_meta` (§5), write the revision.
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

- Empty sections are omitted.
- The diff between any two versions is computed from their snapshots. A field missing from one of the snapshots (older schema) is shown as *not recorded*, not as null.
- Version 0 denotes the empty state before creation.
- `changed_fields` of a revision = keys of `diff.fields` ∪ keys of `diff.meta` ∪ `deleted` if `diff.state` changes.

### 6.4 Other write actions

All of these run as write units (§6.1) and create a revision.

| Action | Semantics |
|---|---|
| **Field verification** | `set_field_verification(entity, field, status, actor, note, evidence_id, expected_version)`. The field must be tracked, non-system and non-empty (`verification_status` itself cannot be field-verified). `verified` requires `evidence_id` of a non-deleted evidence row with the same `subject_id` and `target = field:<name>`, else 400 `evidence_required`. `disputed` requires a note. Sets `locked = true`. The revision has a `meta` diff only. |
| **Soft delete** | `soft_delete(entity, actor, note, expected_version, cascade=False)`. A project with non-deleted services, or a service with non-deleted child services, raises `HasDependentsError` (with counts) unless `cascade=True`. Cascade deletes the dependents with the same `batch_id`, in **one transaction** (all or nothing). Events, comments and evidence are not deleted. Deleting a deleted row → 409 `invalid_state`. Vocabulary terms cannot be deleted (409 `not_deletable`; deactivate instead). |
| **Undelete** | Clears `deleted_*`. It re-validates uniqueness (409 `unique_violation`) and required references (409 `reference_deleted` {field, id, type}). With `cascade=True` it also undeletes the rows whose latest revision is the delete revision with this row's delete `batch_id`, in one transaction. Undeleting a live row → 409 `invalid_state`. |
| **Restore version** | `restore_version(entity, version, actor, note, expected_version, fields=None, dry_run=False)`, all or nothing. Applies the tracked, editable, non-create-only fields present in that version's snapshot whose value differs, optionally limited to `fields`. `dry_run` returns `{field: [current, restored]}` without writing; the UI uses it as a preview. Fields missing from an old snapshot are left unchanged; `state` is never restored; dependent system fields are recomputed. On channel `restore`, inactive vocabulary codes are accepted and reported back in `warnings`. Errors: 409 `unique_violation` {field}; 409 `reference_deleted` {field, id, type}; any other validation error → 400. Not allowed on a deleted entity (409 `entity_deleted`; undelete first). |
| **Bulk edit** | Each item has its own `expected_version` and runs as its own write unit with a shared `batch_id`. Operations: `set` (field → value), `add` (append missing values at the end, in the given order) and `remove` (delete values) for list fields. The whole request is rejected with 400 if a field is not `bulk_editable`, a field appears in more than one operation, `add`/`remove` targets a non-list field, or an ID is duplicated. Per item, the result is `updated`, `unchanged`, `conflict` (with `current_version` and the current values of the targeted fields), `entity_deleted` or `error` (with the error object of `docs/API.md` §1.2). At most 500 items. |

### 6.5 Conflicts

`ConflictError` (409 `conflict`) carries:
- `action` (`patch`, `delete`, `undelete`, `verify`, `restore`, `bulk`, `comment`);
- `entity_type`, `entity_id`;
- `base_version` (the client's `expected_version`), `current_version`;
- `base` and `current` (the `fields` of the two snapshots; `base` is null if no revision exists for `base_version`);
- `base_state` and `current_state` (`{deleted_at, deleted_by, merged_into}`);
- `changed_since_base` (fields where base ≠ current);
- `your_changes` (the submitted changes, normalised);
- `conflicting_fields`: fields in `your_changes` that also changed since base, where your value differs from the current value;
- `meta_changed_since_base` (`{field: {verified: [old, new]}}`), so the UI can warn that applying would reset a colleague's verification;
- `intervening`: the RevisionSummary list for versions base + 1 … current (author, time, note, action, changed fields);
- `refs`: labels for every ID in `base`, `current` and `your_changes`.

Nothing is written. For `action = patch` on a live row, the client resolves the conflict field by field and resubmits with `expected_version = current_version`. For every other action, the client reloads.

### 6.6 Comments

- **Written through the same write path** (`entity_type = comment`).
- **Fields:**
  - tracked: `body_md`, `status`, `resolved_by`, `resolved_at`;
  - create-only: `subject_id`, `field`, `parent_id`;
  - snapshots have `field_meta = {}` and `state = {deleted_at, deleted_by}`.
- **Subjects:** `subject_id` may reference any curated type of §3, deleted or not. `field` must be a registry field of the subject type (derived fields included).
- **Threads:** `parent_id` must be a root comment of the same subject. Replying to a deleted root → 400. A reply does not change the root's status.
- **Status:** roots start `open`; resolve and reopen apply to roots only. Replies have status null. Resolve and reopen are **idempotent**: if the target status is already set, they return without a revision (`changed = false`) and skip the version check.
- **Deleting a root** hides the whole thread; the replies are not modified and reappear on undelete. Comments are undeletable and restorable to any version, like entities.
- **`edited`** is true if any revision after version 1 changed `body_md`.
- **Body rendering:** `body_md` ≤ `MAX_COMMENT_CHARS` (default 10 000). `body_html` is rendered on read (docs/API.md §3.3), so sanitiser changes also apply to old comments.

## 7. Validation rules

- **Vocabulary codes:**
  - A code must exist in the field's vocabulary and be active.
  - An inactive code already stored in the field may be kept; adding an inactive code is rejected, except on channel `restore` (§6.4).
- **Fixed codes:**
  - The system vocabularies (`verification_status`, `screening_status`, `date_basis`, `date_precision`, `period`, `war_trajectory`, `derived_reason`) have `fixed_codes: true`. The `event_type` codes `launch`, `beta_launch` and `first_archived` carry `attributes.fixed = true`.
  - For these, adding or deactivating terms returns 409 `fixed_code`; labels and definitions stay editable.
- **`replaced_by`:** must be an active code of the same vocabulary, different from the term's own code; allowed only when `active = false`.
- **References:** must point to an existing row of an allowed type (by ID prefix). When a value is set or changed, the row must not be deleted (otherwise 409 `reference_deleted`).
- **Events:**
  - `date_basis` is required when `date` is set;
  - `first_archived` requires `archive_upper_bound`;
  - `archive_upper_bound` is allowed only for `first_archived` (record an archive capture as a separate `first_archived` event, never as a launch);
  - documents: `published_basis` is required when `published` is set.
- **Scope:** creating a project, or changing `in_paper_scope`, requires a non-empty `scope_note` in the same change (single or bulk); otherwise 400 `validation_error`. The rule makes scope "a field of its own, with a reason" (assignment §3).
- **Record-level `verification_status`:** setting it to `verified` or `disputed` (single or bulk) requires a revision note.
- **Evidence:**
  - `target = field:<name>` must name a tracked, non-system field of the subject type;
  - `document_id` or `url` is required;
  - `retrieved_at` is required when `document_id` is null;
  - `value_snapshot` is copied from the subject at creation.
- **Partial dates and URLs:** as in §1 and §2.1. Participation `end` ≥ `start` (compared by `_start`).
- **Uniqueness:**
  - `project.slug`, `organization.slug`, `seed_key`, `vocabulary_term` (`vocabulary`, `code`) and `document_link` (`document_id`, `subject_id`) are unique including deleted rows;
  - `document.canonical_url` is unique among non-deleted rows (partial index);
  - collisions are reported as 409 `unique_violation` `{field, existing: {id, label, deleted}}` on create, PATCH, restore and undelete. They are checked explicitly inside the write transaction, with `IntegrityError` mapped to the same response as a fallback.
- **Reference errors:** `reference_deleted` details are `{field, id, type, label}`, so the UI can offer to undelete the referenced row first.
- **Lengths:** comment body ≤ `MAX_COMMENT_CHARS`; revision notes ≤ 2 000.
- **Author names** (from the `X-Author` header):
  - **Decoding:** decoded exactly once with `urllib.parse.unquote(v, encoding="utf-8", errors="strict")`. A `%` not followed by two hex digits, a decoding error, or a header that occurs more than once → 400 `author_invalid`.
  - **Normalisation:** NFC, trim, runs of whitespace collapsed to one space.
  - **Rejected characters:** code points of the Unicode categories Cc, Cf, Co, Cs, Cn, Zl and Zp (control, format, bidi override, zero-width and unassigned characters) and the comma.
  - **Length:** 1–100 code points.
  - **Reserved:** names equal to `seed` or `system` (case-insensitive) or matching `^[A-Za-z_]+:` are rejected, so no person can be recorded as a machine channel.

## 8. Derived fields

### 8.1 When derived values are computed

- **One row per entity:** every project and service has exactly one `derived` row, deleted or not, inserted when the entity is created. A new entity starts as: `period = unknown`, `period_reason = no_date`, `war_trajectory = unknown`, `trajectory_reason = no_date`, `existed_before_invasion = false`.
- **Recompute triggers:** the row is recomputed in the same transaction for:
  - every write to an event (create, update, delete, undelete, restore, verify, bulk), for the old and the new `subject_id`, whatever the event's state before or after;
  - every write to a participation whose old or new `organization_id` is the focal organisation (old and new subject);
  - every write to an `event_type` term.
- **Full recomputes:** `mdt recompute` recomputes all rows. `mdt seed` and `mdt db upgrade` run it when the hash in `app_state` changes; the hash covers `codebook/parameters.yaml`, the focal organisation's ID and the set of modification event types.
- **Never dropped:** list, facet and sort queries LEFT JOIN `derived` and treat a missing row as `unknown`, so an entity never drops out of a table.

### 8.2 Inputs

- **Events:** the subject's non-deleted events whose `verification_status` is not `disputed`.
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
   1. s ≥ INVASION and `existed_before_invasion` → `unknown` (`conflicting_dates`);
   2. s ≥ INVASION → `new_in_war` (`trajectory_event_id` = the launch event);
   3. `existed_before_invasion` and at least one modification event with `date_start` ≥ INVASION → `adapted_in_war` (`trajectory_event_id` = the earliest such event by `date_start`, then `id`);
   4. `existed_before_invasion` and every modification event is dated with `date_end` < INVASION, or there is none → `prewar_unchanged`, meaning "no modification recorded up to the release";
   5. otherwise `unknown`, with reason `imprecise_modification_date` (an undated or straddling modification event; `trajectory_event_id` = that event), `imprecise_date` or `no_date`.
6. **`portfolio_entry`:** the earliest `start` of a participation of the focal organisation in the roles `initiator`, `owner` or `operator`, with `portfolio_entry_participation_id`.

The reason codes are those of the vocabulary `derived_reason` (CODEBOOK §3), including `conflicting_dates`.

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
  - **Existing rows:** a field is updated only if the value differs and either the field has no `field_meta` entry, or its entry has `by == "seed"`, `verified == "unverified"` and `restored_from_version == null`. Otherwise the field is left as it is and reported as a *seed drift* line (entity, field, current value, seed value).
  - **Unchanged data** produces no revision; a second run creates 0 revisions. Seed revisions carry the file's `provenance` string as their note.
  - **Vocabulary metadata** (label, description, multi, fixed_codes) is updated from YAML without revisions (it is versioned in git).

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
- **`fts_entity.body`:** the normalised values of the entity's `string`, `text`, `slug`, `string_list`, `url_list` fields and alias texts. For documents it excludes the full text.
- **`fts_document`:** `title` + `title_en` and the document text.
- **For documents, `q` matches** `fts_entity` OR `fts_document`, and list items get a `search_snippet`. It is built with FTS `snippet()` using the private-use markers U+E000/U+E001 internally, then returned as a list of segments `[{"text": "…", "hit": false}, …]`. No markup is ever sent, and Ukrainian «» quotation marks stay ordinary text.
- **Query building (`q`):**
  - normalise (`normalize_for_search`) and split into tokens (whitespace; `"…"` keeps phrases); at most 200 characters and 16 tokens;
  - tokens without a letter or digit (e.g. `-`, `.`, `–`) are dropped; such tokens would otherwise make the whole AND expression match nothing;
  - escape double quotes;
  - every token becomes `"token"*` (prefix match), phrases stay exact;
  - tokens are joined with AND;
  - if no token remains, the query matches nothing and does not raise.
- **Ranking:** with `sort=relevance` the results are ordered by FTS5 `bm25`.
- **`mdt reindex`** rebuilds both FTS tables.

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

## 13. Integrity checks (`mdt check`)

The check reports, without changing anything, and exits non-zero if anything is found:
- polymorphic references to missing rows;
- missing append-only triggers on `revision`;
- FTS rows missing or orphaned;
- missing or out-of-date `derived` rows;
- entities whose `version` or stored fields/`field_meta` differ from their latest revision snapshot;
- entities with no revision.
