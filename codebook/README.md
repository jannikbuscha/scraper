# Codebook files

One YAML file per controlled vocabulary (`<vocabulary>.yaml`, 26 files; 28 from Phase 3, below) plus three files that are not vocabularies (no `vocabulary` key, so `mdt seed` skips them): `parameters.yaml`, `event_patterns.yaml` and `collector_mappings.yaml`. The format is defined in `docs/DATA_MODEL.md` §9; the coding rules are in `docs/CODEBOOK.md`.

## Where the values come from

- **Codes, labels, definitions:** the Phase 0 codebook draft `docs/CODEBOOK.md` (2026-10-28): §3 "Vocabularies" plus the tables in §2.4 (`wartime_relevance`), §2.5 (`development_mode`) and §2.7 (derived values). Nothing was added from general knowledge.
- **`definition`:** copied from CODEBOOK.md (Markdown bold removed; backticks mark codes and field names). It is `null` where CODEBOOK.md gives no definition. Where CODEBOOK.md only gives a short note in parentheses after a code (`component_type`, `license`, `language: other`), that note is the definition.
- **`label_en`:** the label from CODEBOOK.md. Where CODEBOOK.md lists a code without a label, `label_en` is a plain-English rendering of the code: its words in order, with "and", "or", "of" added where needed and abbreviations in capitals (e.g. `ngo_civil_society` → "NGO or civil society"). For `ministry_category`, `label_en` is the URL segment. One derived label adds a noun: `residents_frontline_occupied` → "Residents of frontline or occupied areas". All labels are provisional and can be edited in the app.
- **`label_uk`:** `null` everywhere, because CODEBOOK.md gives no confirmed Ukrainian label. The page title "Досягнення" for the ministry category `progress` was only seen in search results and is recorded as unconfirmed in that term's `include_note`. Collector C1 captures the category labels shown on the ministry site.
- **`include_note`:** for `wartime_relevance`, the "Rule" column of CODEBOOK.md §2.4; otherwise only the unconfirmed title above.
- **`examples`:** only for `paper_cluster`: the projects the paper assigns to each cluster. CODEBOOK.md allows examples only from the paper's own assignments or from collected and verified data.
- **Phase 3 files** (`docs/DATA_MODEL.md` §19.2, CODEBOOK.md §2.10 and §3):
  - `dimension.yaml`: the four dimensions of the paper's Table 1, codes `d1`…`d4`, `fixed_codes: true`; `label_en` is the dimension's name and `definition` its "Analytical focus" text, both verbatim from the paper; `attributes` = `target` (the evidence target `dimension:D1` … `D4`) and `theoretical_source` (the table's column, verbatim). Nothing else is added.
  - `analysis_code.yaml`: the team's analysis codes, `multi: true`, `fixed_codes: false`, with **no terms** (`terms: []`): the paper and the codebook draft define no codes below the dimensions, so codes are added on the Codebook page (or from the capture panel of the document view) during coding, each with `attributes.dimension` (`d1`…`d4`), never from general knowledge.
- **`sort_order`:** the order in CODEBOOK.md, in steps of 10.
- **`active`:** `true` for all terms, including the candidate beneficiaries.
- **`multi`:** `true` for the vocabularies of multi-valued fields (`ministry_category`, `policy_domain`, `beneficiary`, `channel`).
- **`fixed_codes`:** `true` for the system vocabularies that program logic uses (`verification_status`, `screening_status`, `date_basis`, `date_precision`, `period`, `war_trajectory`, `derived_reason`, and from Phase 3 `dimension`): their terms cannot be added or deactivated in the app; labels and definitions stay editable.
- **`attributes`:**
  - `event_type`: `counts_as_modification` (true/false) exactly as in the CODEBOOK.md table. The derived `war_trajectory` reads it (decision D-2). `fixed: true` marks `launch`, `beta_launch` and `first_archived`, which program logic uses (`docs/DATA_MODEL.md` §7); this attribute can only be changed here, not in the app.
  - `policy_domain`: `cofog`, the COFOG division number ("01" to "10"). The label is the COFOG division name without the number. The labels still have to be checked against the official COFOG publication (decision D-7).
  - `beneficiary`: `candidate: true` for the candidate codes; `paper_basis` (CODEBOOK.md column "Basis in the paper") for the codes grounded in the paper.
  - `participation_role`: `draft_addition: true` for `coordinator`; from Phase 3 `portfolio_role: true` for `initiator`, `owner` and `operator`, the roles in which a participation of the focal organisation decides the derived portfolio entry (the rule of CODEBOOK.md §2.7; `docs/DATA_MODEL.md` §8.3 item 6; decision D-10).
  - `dimension`: `target` and `theoretical_source` (Phase 3); `analysis_code`: `dimension`, required for every term (Phase 3).
- Decision IDs (D-n) refer to `PLAN.md` §12. `[search]` marks information that was only seen in search results (legend of `docs/CODEBOOK.md`).

## parameters.yaml

Cut-off dates and time zones, each with its source under `sources`:

| Parameter | Value | Source |
|---|---|---|
| `ministry_founded` | 2019-08-29 | paper (case description) and assignment §1 |
| `full_scale_invasion` | 2022-02-24 | assignment §1 (the paper gives only the month, February 2022) |
| `publication_timezone` | Europe/Kyiv | assignment §4 |
| `storage_timezone` | UTC | assignment §4 |

`parameters.yaml` is not a vocabulary file: it has no `vocabulary` key. The backend reads it directly; the derived values (`period`, `war_trajectory`) use the two dates.

## event_patterns.yaml

The phrase patterns that turn a sentence with a project or service mention into a `create_event` proposal (never a fact): the draft phrase list of `docs/CODEBOOK.md` §4, nothing added, one entry per Ukrainian stem or phrase and one per English cell, each with an `id` (its precision is reported per `id`), an `event_type`, a `lang` and `stems`, `phrases` or `all_of`. Matching rules: `docs/COLLECTORS.md` §7.7. The file is read by the tagger; its SHA-256 is part of each collector run's `config_hash`.

## collector_mappings.yaml

Source labels mapped to vocabulary codes for the collectors (`docs/COLLECTORS.md` §7.9): the `kind.slug` of thedigital.gov.ua documents → `doc_type` (C4, fallback `other`) and the channel leads of diia.gov.ua service pages → `channel` (C3, "Результат" ignored). Draft coding rules, open to the team like the codebook. Every target code must be an active term of its vocabulary, otherwise runs of the collector that uses the mapping fail.

## Working copy and releases

- `mdt seed` loads the vocabularies into the database. It is idempotent: terms are matched by `vocabulary` + `code`, and a field changed by a person in the app is never overwritten.
- From then on **the database holds the working copy**. Terms are edited on the Codebook page of the app, and every change creates a revision.
- Codes are stable: a code is never renamed or deleted, only deactivated (`active: false`) and, where applicable, linked to its replacement (`replaced_by`).
- **Each release regenerates `codebook/`** (and `docs/CODEBOOK.md`) from the database (releases arrive in Phase 4). After the first release these files show the curated state, not this initial draft. Edit vocabularies in the app, not here; a changed YAML value reaches the database only for fields that no person has changed (the seed rule of `docs/DATA_MODEL.md` §9).
