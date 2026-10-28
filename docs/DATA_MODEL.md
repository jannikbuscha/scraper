# Data model

> **Status:** v1 contract for Phase 1 (2026-10-28). Implementations must follow this document. Deviations must be agreed and the document updated in the same change.
> **Related:** `PLAN.md` §4 and §6 (rationale), `docs/API.md` (HTTP interface), `docs/UI.md` (frontend), `docs/CODEBOOK.md` (vocabularies and coding rules).

## 1. Conventions

| Topic | Rule |
|---|---|
| **IDs** | Prefixed ULIDs as text primary keys: `<prefix>_<26-char ULID>`, e.g. `prj_01JBX3…`. The prefix determines the entity type (table in §3). IDs are never reused or regenerated. |
| **Timestamps** | UTC, stored as ISO-8601 text `YYYY-MM-DDTHH:MM:SS.ffffffZ` (sorts lexicographically). The API returns the same format. |
| **Calendar dates** | Text `YYYY-MM-DD`. Publication dates are calendar dates in Europe/Kyiv. |
| **Partial dates** | Field type `partial_date`, stored in three columns `<name>_start`, `<name>_end` (inclusive, `YYYY-MM-DD`) and `<name>_precision` (`day`, `month`, `quarter`, `year`). In the API it is a canonical string: `YYYY`, `YYYY-Qn`, `YYYY-MM` or `YYYY-MM-DD` (1900–2100, validated; e.g. `2022-02-30` is rejected). Start and end are derived from the string and are read-only. |
| **Lists** | JSON arrays in a JSON column. Normalisation: strings trimmed, empty strings dropped, duplicates removed keeping first occurrence. |
| **Booleans** | SQLite integer 0/1, API `true`/`false`. |
| **Soft delete** | `deleted_at`/`deleted_by` set, row kept. Default queries exclude deleted rows. |
| **Versions** | `version` starts at 1 on creation and increases by exactly 1 per revision of the row. |
| **Text** | Stored as entered (NFC-normalised). Search uses a normalised copy (§10). |

## 2. Entity registry

A single registry module describes every entity type and its fields. Validation, revisions, the API (filters, sorting, exports) and the frontend (via `GET /api/meta`) are all driven by it.

### 2.1 Field types

| Type | API value | Storage | Notes |
|---|---|---|---|
| `string` | string or null | TEXT | single line, max 500 characters |
| `text` | string or null | TEXT | multi-line, max 20 000 characters |
| `slug` | string | TEXT | `^[a-z0-9]+(-[a-z0-9]+)*$`, max 100 characters |
| `bool` | boolean | INTEGER | |
| `int` | integer or null | INTEGER | |
| `number` | number or null | REAL | |
| `url` | string or null | TEXT | absolute `http`/`https` URL, max 2 000 characters |
| `url_list` | string[] | JSON | each element a valid `url` |
| `string_list` | string[] | JSON | each element a valid `string` |
| `vocab` | code or null | TEXT | `vocabulary` attribute names the vocabulary |
| `vocab_list` | code[] | JSON | |
| `ref` | ID or null | TEXT | `ref_types` lists the allowed entity types; the referenced row must exist and not be deleted when the value is set |
| `partial_date` | canonical string or null | 3 columns (§1) | |
| `datetime` | ISO string or null | TEXT | system-set, read-only |
| `alias_list` | object[] | JSON | items `{text: string, lang: "uk"|"en"|"other", case_sensitive: bool (default true), kind: "name"|"inflection"|"abbreviation"|"spelling"|"domain", exclude_patterns: string[]}` |
| `json` | any JSON | JSON | used for collector-filled structures (read-only in the UI unless stated) |
| `doc_links` | object[] | table `document_link` | items `{subject_id, origin: "auto"|"manual", state: "suggested"|"confirmed"|"rejected"}` plus read-only `matched_aliases`, `match_count`, `snippet` |

### 2.2 Field attributes

Every field in the registry has these attributes:
- `name`, `label` (English), `type`;
- `vocabulary` (for `vocab`/`vocab_list`), `ref_types` (for `ref`);
- `group`: `basics` · `classification` · `wartime` · `framework` · `sources` · `system`;
- `required`, `editable`, `tracked` (part of revisions and `field_meta`), `derived` (read-only, computed);
- `filter`: `text` · `multiselect` · `date_range` · `bool` · `number_range` · `ref` · none;
- `sortable`, `in_list` (default table column), `help` (tooltip text).

### 2.3 Common columns of curated entities

Every curated entity table (all tables in §3) has these columns:

| Column | Type | Tracked | Notes |
|---|---|---|---|
| `id` | TEXT PK | — | prefixed ULID |
| `version` | INTEGER NOT NULL | — | optimistic locking |
| `created_at`, `created_by` | TEXT | — | `created_by` = author name or `collector:<name>` / `seed` / `import:<file>` |
| `updated_at`, `updated_by` | TEXT | — | |
| `deleted_at`, `deleted_by` | TEXT NULL | state | soft delete |
| `merged_into` | TEXT NULL | state | ID of the surviving entity after a merge (merge itself is Phase 2) |
| `verification_status` | TEXT NOT NULL DEFAULT `unverified` | ✓ | vocabulary `verification_status`; group `basics`; filter multiselect; in list |
| `notes` | TEXT NULL | ✓ | internal notes; group `sources` |
| `field_meta` | JSON NOT NULL DEFAULT `{}` | — | provenance per field (§5) |

## 3. Curated entities

Legend: **R** required · **E** editable in the UI · **F** filter · **S** sortable · **L** default list column. Groups: B basics, C classification, W wartime, Fw framework, So sources. All fields are tracked unless marked "derived" or "read-only (system)".

### 3.1 `project` (prefix `prj_`)

| Field | Type | Vocab / ref | R | E | Group | F | S | L |
|---|---|---|---|---|---|---|---|---|
| `slug` | slug (unique, incl. deleted) | | ✓ | ✓ | B | text | ✓ | ✓ |
| `name_en` | string | | ✱ | ✓ | B | text | ✓ | ✓ |
| `name_uk` | string | | ✱ | ✓ | B | text | ✓ | ✓ |
| `aliases` | alias_list | | | ✓ | B | | | |
| `description_en`, `description_uk` | text | | | ✓ | B | text | | |
| `official_urls`, `ministry_urls` | url_list | | | ✓ | B | text | | |
| `in_paper_scope` | bool (default false) | | ✓ | ✓ | B | bool | ✓ | ✓ |
| `scope_note` | text | | | ✓ | B | text | | |
| `status` | vocab | `status` | | ✓ | B | multiselect | ✓ | ✓ |
| `paper_cluster` | vocab | `paper_cluster` | | ✓ | C | multiselect | ✓ | ✓ |
| `unit_type` | vocab | `unit_type` | | ✓ | C | multiselect | ✓ | |
| `ministry_categories` | vocab_list | `ministry_category` | | ✓ | C | multiselect | | ✓ |
| `primary_objectives` | text | | | ✓ | C | text | | |
| `policy_domains` | vocab_list | `policy_domain` | | ✓ | C | multiselect | | ✓ |
| `beneficiaries` | vocab_list | `beneficiary` | | ✓ | C | multiselect | | |
| `development_mode` | vocab | `development_mode` | | ✓ | C | multiselect | ✓ | |
| `development_rationale` | text | | | ✓ | C | text | | |
| `wartime_relevance` | vocab | `wartime_relevance` | | ✓ | W | multiselect | ✓ | ✓ |
| `wartime_rationale` | text | | | ✓ | W | text | | |
| `d1_need`, `d1_affected_groups`, `d1_priority_link` | text | | | ✓ | Fw | text | | |
| `d2_summary`, `d3_summary`, `d4_summary` | text | | | ✓ | Fw | text | | |
| derived: `launch` | partial_date | | | | W | date_range (+ empty) | ✓ | ✓ |
| derived: `existed_by` | date | | | | W | date_range | ✓ | |
| derived: `period` | vocab | `period` | | | W | multiselect | ✓ | ✓ |
| derived: `war_trajectory` | vocab | `war_trajectory` | | | W | multiselect | ✓ | |
| derived: `portfolio_entry` | partial_date | | | | W | date_range | ✓ | |

✱ at least one of `name_en`/`name_uk` is required. There is no machine translation; a missing English name stays empty.

### 3.2 `service` (prefix `svc_`)

| Field | Type | Vocab / ref | R | E | Group | F | S | L |
|---|---|---|---|---|---|---|---|---|
| `project_id` | ref (FK) | project | ✓ | ✓ | B | ref | ✓ | ✓ |
| `parent_service_id` | ref (FK) | service | | ✓ | B | ref | | |
| `name_en`, `name_uk` | string | | ✱ | ✓ | B | text | ✓ | ✓ |
| `aliases` | alias_list | | | ✓ | B | | | |
| `description_en`, `description_uk` | text | | | ✓ | B | text | | |
| `urls` | url_list | | | ✓ | B | text | | |
| `status` | vocab | `status` | | ✓ | B | multiselect | ✓ | ✓ |
| `kind` | vocab | `service_kind` | | ✓ | C | multiselect | ✓ | ✓ |
| `channels` | vocab_list | `channel` | | ✓ | C | multiselect | | ✓ |
| `source_categories` | json `[{source,label,url}]` | | | read-only | So | | | |
| `source_audiences` | string_list | | | ✓ | So | text | | |
| `policy_domains` | vocab_list | `policy_domain` | | ✓ | C | multiselect | | |
| `beneficiaries` | vocab_list | `beneficiary` | | ✓ | C | multiselect | | ✓ |
| `development_mode`, `development_rationale` | vocab / text | `development_mode` | | ✓ | C | multiselect / text | ✓ | |
| `wartime_relevance`, `wartime_rationale` | vocab / text | `wartime_relevance` | | ✓ | W | multiselect / text | ✓ | ✓ |
| `d1_need` … `d4_summary` | text | | | ✓ | Fw | text | | |
| derived: `launch`, `existed_by`, `period`, `war_trajectory`, `portfolio_entry` | as for project | | | | W | as for project | ✓ | `launch`, `period` |
| virtual: `project_in_paper_scope` | bool (from the project) | | | | B | bool | | |

Constraints: `parent_service_id` must belong to the same project and must not create a cycle.

### 3.3 `event` (prefix `evt_`)

| Field | Type | Vocab / ref | R | E | Group | F | S | L |
|---|---|---|---|---|---|---|---|---|
| `subject_id` | ref | project, service, component, organization | ✓ | ✓ | B | ref | ✓ | ✓ |
| `event_type` | vocab | `event_type` | ✓ | ✓ | B | multiselect | ✓ | ✓ |
| `date` | partial_date | | | ✓ | B | date_range (+ empty) | ✓ | ✓ |
| `date_basis` | vocab | `date_basis` | | ✓ | B | multiselect | ✓ | ✓ |
| `date_text` | string (verbatim from source) | | | ✓ | So | text | | |
| `description_en`, `description_uk` | text | | | ✓ | B | text | | `description_en` |

### 3.4 `document` (prefix `doc_`)

| Field | Type | Vocab / ref | R | E | Group | F | S | L |
|---|---|---|---|---|---|---|---|---|
| `title` | string (max 1 000) | | ✓ | ✓ | B | text | ✓ | ✓ |
| `title_en` | string | | | ✓ | B | text | | |
| `url` | url | | | ✓ | So | text | | |
| `canonical_url` | url (normalised from `url`; unique among non-deleted) | | | read-only | So | text | | |
| `publisher` | string | | | ✓ | B | text | ✓ | ✓ |
| `publisher_org_id` | ref | organization | | ✓ | B | ref | | |
| `doc_type` | vocab | `doc_type` | | ✓ | B | multiselect | ✓ | ✓ |
| `language` | vocab | `language` | | ✓ | B | multiselect | ✓ | ✓ |
| `published` | partial_date | | | ✓ | B | date_range (+ empty) | ✓ | ✓ |
| `published_basis` | vocab | `date_basis` | | ✓ | B | multiselect | | |
| `published_text` | string (verbatim) | | | ✓ | So | text | | |
| `published_at_utc`, `retrieved_at` | datetime | | | read-only | So | date_range | ✓ | |
| `source_id`, `external_id`, `raw_snapshot_id`, `text_hash`, `extraction_method` | string | | | read-only | So | | | |
| `archive_urls` | url_list | | | ✓ | So | | | |
| `license` | vocab | `license` | | ✓ | So | multiselect | | |
| `screening_status` | vocab (default `unscreened`) | `screening_status` | ✓ | ✓ | B | multiselect | ✓ | ✓ |
| `screening_reason` | vocab | `exclusion_reason` | | ✓ | B | multiselect | | |
| `screening_note` | text | | | ✓ | B | text | | |
| `links` | doc_links | | | ✓ | So | ref (by `subject_id`) | | |
| virtual: `text` | text from `document_text` | | | read-only, detail only | So | full-text only | | |

Normalisation of `canonical_url`: lowercase scheme and host; remove a trailing dot from the host, default ports, the fragment, `utm_*` parameters and the trailing slash (except the root path).

### 3.5 Other curated entities

| Table (prefix) | Fields (type) | Notes |
|---|---|---|
| `organization` (`org_`) | `slug` (slug, unique, optional), `name_en`/`name_uk` (string, ✱), `aliases` (alias_list), `org_type` (vocab `org_type`), `country` (string, ISO 3166-1 alpha-2, uppercase), `urls` (url_list), `description` (text) | the focal organisation has slug `ministry-of-digital-transformation` (configurable as `FOCAL_ORG_SLUG`) |
| `participation` (`par_`) | `organization_id` (ref organization, R), `subject_id` (ref project/service/component, R), `role` (vocab `participation_role`, R), `start`/`end` (partial_date; `end` ≥ `start`), `description` (text) | for D3 |
| `component` (`cmp_`) | `name_en`/`name_uk` (✱), `aliases`, `component_type` (vocab `component_type`), `description` (text), `urls` (url_list) | created only from sources |
| `relation` (`rel_`) | `from_id`, `to_id` (ref project/service/component, R, distinct), `relation_type` (vocab `relation_type`, R), `description` (text) | read as "from — type — to" |
| `indicator` (`ind_`) | `subject_id` (ref project/service/component/organization, R), `metric` (string, R), `value` (number, R), `unit` (string), `as_of` (partial_date), `description` (text) | |
| `evidence` (`evd_`) | `subject_id` (ref any curated type except evidence, R), `target` (string, R: `entity` \| `field:<field name of the subject type>` \| `dimension:D1`…`D4`), `document_id` (ref document), `url`, `archive_url` (url), `raw_snapshot_id`, `text_hash` (string, read-only), `char_start`, `char_end` (int), `quote` (text ≤ 1 000), `locator` (string), `description` (text) | `document_id` or `url` is required |
| `vocabulary_term` (`voc_`) | `vocabulary` (string, R, immutable), `code` (`^[a-z0-9_]+$`, R, immutable), `label_en` (string, R), `label_uk` (string), `definition`, `include_note`, `exclude_note`, `examples` (text), `sort_order` (int), `active` (bool, default true), `replaced_by` (string code), `attributes` (json) | unique (`vocabulary`, `code`); the vocabulary must exist |
| `saved_view` (`view_`) | `name` (string, R), `entity_type` (string, R, one of the table entity types), `query` (string, R; URL query string without `?`), `description` (text) | visible to everyone |

The UI tables in Phase 1 cover project, service, event, document and organization. The other types already have the generic API.

## 4. System tables

| Table | Columns | Rules |
|---|---|---|
| `vocabulary` | `name` PK, `label`, `description`, `multi` (informative), `source_file` | loaded from `codebook/*.yaml`; read-only in Phase 1 |
| `revision` | `id` INTEGER PK AUTOINCREMENT, `entity_type`, `entity_id`, `version`, `at`, `author`, `channel` (`seed`, `ui`, `collector`, `import`, `restore`, `merge`, `system`), `note` (≤ 2 000), `run_id`, `proposal_id`, `restored_from` (revision id), `batch_id`, `snapshot` (JSON), `diff` (JSON) | unique (`entity_id`, `version`); **append-only**: SQLite triggers abort every UPDATE and DELETE (`RAISE(ABORT, 'revision is append-only')`) |
| `comment` (`cmt_`) | `subject_id`, `field` (nullable; a field name of the subject type), `parent_id` (nullable; must be a root comment of the same subject), `body_md` (≤ `MAX_COMMENT_CHARS`), `status` (`open`/`resolved`; roots only, replies NULL), `resolved_by`, `resolved_at`, plus `id`, `version`, `created_*`, `updated_*`, `deleted_*` | every change creates a revision (`entity_type = comment`) |
| `document_text` | `text_hash` PK (sha256 of the normalised text), `text`, `char_count`, `created_at` | immutable |
| `document_link` | `id`, `document_id` FK, `subject_id`, `origin`, `state`, `matched_aliases` (JSON), `match_count`, `snippet` | managed through the document's `links` field; part of the document's revision snapshot |
| `derived` | `entity_id` PK, `launch_start`, `launch_end`, `launch_precision`, `launch_basis`, `launch_event_id`, `existed_by`, `existed_by_event_id`, `existed_before_invasion` (bool), `period`, `period_reason`, `war_trajectory`, `trajectory_reason`, `portfolio_entry_start`, `portfolio_entry_end`, `portfolio_entry_precision`, `computed_at` | one row per project and service; never edited directly (§8) |
| `fts_entity` | FTS5 (`entity_id` UNINDEXED, `entity_type` UNINDEXED, `body`), `tokenize = "unicode61 remove_diacritics 2"`, `prefix = '2 3 4'` | maintained by the domain layer (§10) |
| `fts_document` | FTS5 (`document_id` UNINDEXED, `title`, `body`), same tokenizer | |

Later phases add `proposal`, `collector_run`, `fetch_log`, `raw_snapshot`, `source_observation`, `release` and `merge_log` (see `PLAN.md` §4.3) through new migrations.

## 5. Field provenance (`field_meta`)

`field_meta` is a JSON object keyed by field name. There is one entry per tracked field that has ever been set:

```json
{
  "name_en": {
    "src": "seed",
    "by": "seed",
    "at": "2026-10-28T17:00:00.000000Z",
    "locked": true,
    "verified": "unverified",
    "evidence_id": null,
    "restored_from_version": null
  }
}
```

- **`src`**: `seed` | `manual:<name>` | `import:<file>` | `collector:<name>@<run_id>`. Origin of the current value.
- **`by`**: who wrote the current value (person name, `seed`, `import:<file>` or `collector:<name>`).
- **`locked`**: `true` once a person or a human-curated channel has set the value: channels `ui`, `seed`, `import`, `restore`, `merge` set `locked = true`; channel `collector` leaves it `false`. **A collector change to a locked field is refused** (`LockedFieldError`); in Phase 2 the reconciler turns it into a proposal instead.
- **`verified`**: `unverified` | `verified` | `disputed`. Set through the field-verification action. A value change resets it to `unverified`, unless the change is a restore, which takes the verification status from the restored snapshot.
- **Restore** keeps the restored value's original `src` and `evidence_id`, sets `by` to the restoring person, `locked = true` and `restored_from_version`.

## 6. Revisions and writes

### 6.1 One write path

Every change of a curated entity (including comments, vocabulary terms and saved views) goes through the domain function:

`apply_change(session, entity_type, entity_id | None, changes, actor, channel, note=None, expected_version=None, batch_id=None, run_id=None) -> ChangeResult`

1. **Validate:** field names exist and are editable for the channel (system channels may also set read-only fields such as `canonical_url`); types and normalisation (§1, §2.1); vocabulary codes (§7); references; uniqueness; entity-specific constraints.
2. **Create** (`entity_id` is None): new ID, `version = 1`, `created_*`/`updated_*` set; a `field_meta` entry for every provided non-null field; revision version 1 with `diff = {"fields": {f: [null, value]}}`.
3. **Update:**
   - **Version check:** if `expected_version` is given and differs from the stored `version` → `ConflictError` (§6.4). The UI and API always pass `expected_version`; only seed and collector channels may omit it.
   - **Diff:** compare the normalised new value with the stored value per field. If nothing differs → **no-op**: no revision, no version bump, `ChangeResult.changed = false`.
   - **Write:** apply the values, bump `version`, set `updated_*`, update `field_meta` for the changed fields, write the revision.
4. In the same transaction: refresh the FTS row (§10) and recompute derived values if the change affects them (§8).

### 6.2 Snapshot and diff format

Revision `snapshot` (the full state after the change):

```json
{
  "fields": {"slug": "diia", "name_en": "Diia", "...": "..."},
  "field_meta": {"name_en": {"src": "seed", "...": "..."}},
  "state": {"deleted_at": null, "deleted_by": null, "merged_into": null}
}
```

`fields` contains every tracked field in API representation (partial dates as canonical strings, lists as arrays, `links` as an array of objects). Revision `diff`:

```json
{
  "fields": {"name_en": ["Old", "New"]},
  "meta":   {"name_en": {"verified": ["unverified", "verified"]}},
  "state":  {"deleted_at": [null, "2026-10-28T17:00:00.000000Z"]}
}
```

Empty sections are omitted. The diff between any two versions is computed from their snapshots.

### 6.3 Other write actions (all through `apply_change` or the same transaction logic, all with a revision)

| Action | Semantics |
|---|---|
| **Field verification** | `set_field_verification(entity, field, status, actor, note, expected_version)`: changes `field_meta[field].verified`; a revision with a `meta` diff only; the field must have a value. |
| **Soft delete** | `soft_delete(entity, actor, note, expected_version, cascade=False)`. A project with non-deleted services raises `HasDependentsError` (with counts) unless `cascade=True`; cascade soft-deletes the services under one `batch_id`. Events and comments are not deleted. |
| **Undelete** | Clears `deleted_*`. Refused if a required reference points to a deleted row (e.g. a service whose project is deleted). |
| **Restore version** | `restore_version(entity, version, actor, note, expected_version)`. Takes the snapshot of that version and applies every tracked editable field whose value differs, with `channel = restore` and `restored_from` set to that revision's id. Not allowed on a deleted entity (undelete first). Uniqueness violations are reported as validation errors. |
| **Bulk edit** | Per item: `apply_change` in its own transaction with a shared `batch_id`. Operations: `set` (field → value), `add`/`remove` (list fields → values). Results are reported per item: `updated`, `unchanged`, `conflict` or `error`. |

### 6.4 Conflicts

`ConflictError` carries:
- `entity_type`, `entity_id`;
- `base_version` (the client's `expected_version`), `current_version`;
- `base` and `current` (the `fields` of the two snapshots);
- `changed_since_base` (fields where base ≠ current);
- `your_changes` (the submitted changes);
- `conflicting_fields`: fields in `your_changes` that also changed since base, where your value differs from the current value.

Nothing is written. The client resolves the conflict and resubmits with `expected_version = current_version`.

## 7. Validation rules

- **Vocabulary codes** must exist in the field's vocabulary and be active. Exception: an inactive code already stored in the field may be kept; adding an inactive code is rejected.
- **References** must point to an existing, non-deleted row of an allowed type, matched by ID prefix.
- **`evidence.target`:** `field:<name>` must name a field of the subject's type.
- **Partial dates and URLs** as in §1 and §2.1. Participation `end` ≥ `start` (compared by `_start` dates).
- **Lengths:** comment body ≤ `MAX_COMMENT_CHARS` (default 10 000); notes ≤ 2 000.
- **Author names:** 1–100 characters after trimming; control characters are rejected.

## 8. Derived fields

Computed for every project and service from its non-deleted events whose `verification_status` is not `disputed`. They are stored in `derived`, recomputed in the transaction of any change to such an event (old and new subject), to a participation of the focal organisation, to an `event_type` term's `attributes`, and by `mdt recompute`. The rules are those of `docs/CODEBOOK.md` §2.7; the parameters `MINISTRY_FOUNDED = 2019-08-29` and `FULL_SCALE_INVASION = 2022-02-24` are read from `codebook/parameters.yaml`.

- **`launch`:** the earliest `launch` event by `date_start`; if there is none, the earliest `beta_launch`. Events without a date are ignored.
- **`existed_by`:** the minimum `date_start` of `first_archived` events. It is an upper bound and is shown as "≤ date".
- **`period`, `period_reason`, `existed_before_invasion`:** CODEBOOK §2.7.
- **`war_trajectory`, `trajectory_reason`:** modification types are event-type terms with `attributes.counts_as_modification = true`.
  - `new_in_war`: launch_start ≥ INVASION.
  - `adapted_in_war`: existed before the invasion and at least one modification event with date_start ≥ INVASION.
  - `prewar_unchanged`: existed before the invasion and every dated modification event has date_end < INVASION.
  - Otherwise `unknown`.
  - Undated modification events make an otherwise `prewar_unchanged` result `unknown` (reason `imprecise_modification_date`).
- **`portfolio_entry`:** the earliest `start` of a non-deleted participation of the focal organisation in the roles `initiator`, `owner` or `operator`.

## 9. Seed and codebook files

**`codebook/<vocabulary>.yaml`**, one file per vocabulary:

```yaml
vocabulary: paper_cluster
label: Paper cluster
description: Seven thematic clusters used in the paper.
multi: false
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

**`codebook/parameters.yaml`**: `ministry_founded: 2019-08-29`, `full_scale_invasion: 2022-02-24`, `publication_timezone: Europe/Kyiv`, plus sources for each value.

**`seed/projects.yaml`**: the 19 projects of the paper plus European Integration (assignment §3), and the focal organisation:

```yaml
provenance: "Assignment §3; entry URLs checked by the data lead on 2026-10-28"
projects:
  - slug: diia
    name_en: Diia
    name_uk: Дія
    paper_cluster: digital_public_services_infrastructure
    in_paper_scope: true
    scope_note: null
    ministry_urls: ["https://thedigital.gov.ua/projects/technologies/diia-derzhavni-poslugi-onlajn"]
    official_urls: []
    aliases:
      - {text: Diia, lang: en, case_sensitive: true, kind: name}
      - {text: Дія, lang: uk, case_sensitive: true, kind: name}
organizations:
  - slug: ministry-of-digital-transformation
    name_en: Ministry of Digital Transformation of Ukraine
    name_uk: Мінцифри
    org_type: ministry
    country: UA
```

Rules:
- **Only values from the assignment.** Entry URLs on thedigital.gov.ua go into `ministry_urls`, external entry URLs into `official_urls`. `ministry_categories` stays empty (collector C1 fills it with evidence). No Ukrainian name is invented where the assignment gives only one name.
- **`mdt seed` is idempotent.** It loads the vocabularies first, then the organisations and projects, matched by `vocabulary`+`code` or `slug`, including deleted rows:
  - missing rows are created (`channel = seed`, `src = seed`, `locked = true`);
  - deleted rows are skipped;
  - for existing rows, a field is updated only if its `field_meta.src` is `seed` (or the field was never set) and the value differs. Fields changed by people are never overwritten;
  - unchanged values produce no revision. A second run creates 0 revisions.

## 10. Full-text search

- **Normalisation** (`normalize_for_search`): NFC; apostrophe variants `'`, `’`, `‘`, `` ` ``, `´`, `ʹ`, `ʼ` → `ʼ` (U+02BC); non-breaking and other Unicode spaces → space; soft hyphen removed; dash variants → `-`. The same function is applied to indexed text and to queries (see `PLAN.md` §4.7 for the probe that motivates it).
- **`fts_entity.body`** for each non-deleted curated entity concatenates the normalised values of its `string`, `text`, `slug`, `alias_list` (texts), `string_list` and `url_list` fields. Rows are replaced on every write and removed on soft delete (restored on undelete).
- **`fts_document`** holds `title` + `title_en` and the document text.
- **Query building** (`q` parameter):
  - split into tokens (whitespace; `"…"` keeps phrases);
  - escape double quotes;
  - every token becomes `"token"*` (prefix match), phrases stay exact;
  - tokens are joined with AND;
  - an empty or punctuation-only query matches nothing and does not raise.

## 11. Integrity checks (`mdt check`)

The check reports, without changing anything:
- polymorphic references that point to missing rows;
- FTS rows missing for or orphaned from entities;
- `derived` rows out of date (recomputed values differ);
- entities whose `version` does not match their latest revision.

It exits non-zero if anything is found.
