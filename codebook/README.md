# Codebook files

One YAML file per controlled vocabulary (`<vocabulary>.yaml`, 26 files) plus `parameters.yaml`. The format is defined in `docs/DATA_MODEL.md` §9; the coding rules are in `docs/CODEBOOK.md`.

## Where the values come from

- **Codes, labels, definitions:** the Phase 0 codebook draft `docs/CODEBOOK.md` (2026-10-28): §3 "Vocabularies" plus the tables in §2.4 (`wartime_relevance`), §2.5 (`development_mode`) and §2.7 (derived values). Nothing was added from general knowledge.
- **`definition`:** copied from CODEBOOK.md (Markdown bold removed; backticks mark codes and field names). It is `null` where CODEBOOK.md gives no definition. Where CODEBOOK.md only gives a short note in parentheses after a code (`component_type`, `license`, `language: other`), that note is the definition.
- **`label_en`:** the label from CODEBOOK.md. Where CODEBOOK.md lists a code without a label, `label_en` is a plain-English rendering of the code: its words in order, with "and", "or", "of" added where needed and abbreviations in capitals (e.g. `ngo_civil_society` → "NGO or civil society"). For `ministry_category`, `label_en` is the URL segment. One derived label adds a noun: `residents_frontline_occupied` → "Residents of frontline or occupied areas". All labels are provisional and can be edited in the app.
- **`label_uk`:** `null` everywhere, because CODEBOOK.md gives no confirmed Ukrainian label. The page title "Досягнення" for the ministry category `progress` was only seen in search results and is recorded as unconfirmed in that term's `include_note`. Collector C1 captures the category labels shown on the ministry site.
- **`include_note`:** for `wartime_relevance`, the "Rule" column of CODEBOOK.md §2.4; otherwise only the unconfirmed title above.
- **`examples`:** only for `paper_cluster`: the projects the paper assigns to each cluster. CODEBOOK.md allows examples only from the paper's own assignments or from collected and verified data.
- **`sort_order`:** the order in CODEBOOK.md, in steps of 10.
- **`active`:** `true` for all terms, including the candidate beneficiaries.
- **`multi`:** `true` for the vocabularies of multi-valued fields (`ministry_category`, `policy_domain`, `beneficiary`, `channel`).
- **`fixed_codes`:** `true` for the system vocabularies that program logic uses (`verification_status`, `screening_status`, `date_basis`, `date_precision`, `period`, `war_trajectory`, `derived_reason`): their terms cannot be added or deactivated in the app; labels and definitions stay editable.
- **`attributes`:**
  - `event_type`: `counts_as_modification` (true/false) exactly as in the CODEBOOK.md table. The derived `war_trajectory` reads it (decision D-2). `fixed: true` marks `launch`, `beta_launch` and `first_archived`, which program logic uses (`docs/DATA_MODEL.md` §7); this attribute can only be changed here, not in the app.
  - `policy_domain`: `cofog`, the COFOG division number ("01" to "10"). The label is the COFOG division name without the number. The labels still have to be checked against the official COFOG publication (decision D-7).
  - `beneficiary`: `candidate: true` for the candidate codes; `paper_basis` (CODEBOOK.md column "Basis in the paper") for the codes grounded in the paper.
  - `participation_role`: `draft_addition: true` for `coordinator`.
- Decision IDs (D-1 … D-12) refer to `PLAN.md` §12. `[search]` marks information that was only seen in search results (legend of `docs/CODEBOOK.md`).

## parameters.yaml

Cut-off dates and time zones, each with its source under `sources`:

| Parameter | Value | Source |
|---|---|---|
| `ministry_founded` | 2019-08-29 | paper (case description) and assignment §1 |
| `full_scale_invasion` | 2022-02-24 | assignment §1 (the paper gives only the month, February 2022) |
| `publication_timezone` | Europe/Kyiv | assignment §4 |
| `storage_timezone` | UTC | assignment §4 |

`parameters.yaml` is not a vocabulary file: it has no `vocabulary` key. The backend reads it directly; the derived values (`period`, `war_trajectory`) use the two dates.

## Working copy and releases

- `mdt seed` loads the vocabularies into the database. It is idempotent: terms are matched by `vocabulary` + `code`, and a field changed by a person in the app is never overwritten.
- From then on **the database holds the working copy**. Terms are edited on the Codebook page of the app, and every change creates a revision.
- Codes are stable: a code is never renamed or deleted, only deactivated (`active: false`) and, where applicable, linked to its replacement (`replaced_by`).
- **Each release regenerates `codebook/`** (and `docs/CODEBOOK.md`) from the database (releases arrive in Phase 4). After the first release these files show the curated state, not this initial draft. Edit vocabularies in the app, not here; a changed YAML value reaches the database only for fields that no person has changed (the seed rule of `docs/DATA_MODEL.md` §9).
