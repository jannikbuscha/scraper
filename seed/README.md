# Seed data

`projects.yaml` holds the initial projects and the focal organisation. The format is defined in `docs/DATA_MODEL.md` §9. Every value comes from the assignment; nothing comes from general knowledge.

## Where the values come from

- **19 projects of the paper:** slug, names, cluster and entry URL from the table in assignment §3. The assignment states that the entry URLs were checked on https://thedigital.gov.ua/projects on 2026-10-28. The cluster assignments are those of the paper's preliminary findings.
- **European Integration (Євроінтеграція):** from the paragraph below that table. It is listed on thedigital.gov.ua/projects but missing in the paper, so it is seeded with `in_paper_scope: false` and no cluster; the team decides (decision D-1, `PLAN.md` §12).
- **Names:** "EN / UK" in the table becomes `name_en` / `name_uk`. Where the table gives only one name, it is `name_en` and `name_uk` stays `null`; no Ukrainian name is invented.
- **`paper_cluster`:** the cluster names of the table, mapped to the codes in `codebook/paper_cluster.yaml`.
- **URLs:** entry URLs on thedigital.gov.ua go into `ministry_urls`, external entry URLs into `official_urls`; the other list is empty.
- **`in_paper_scope` and `scope_note`:** `true` for the 19 projects of the paper; `false` for European Integration, with the reason in `scope_note`.
- **`aliases`:** one alias of kind `name` per given name (`lang` `en` or `uk`, case-sensitive, no exclude patterns). For Diia also the inflected forms Дії and Дію (kind `inflection`), which the assignment names (§5, source 4). Further aliases and exclude patterns are curated in the app.
- **Focal organisation:** "Ministry of Digital Transformation of Ukraine (Мінцифри)" from assignment §1, with `org_type: ministry`, `country: UA` and one `name` alias per name. Its slug `ministry-of-digital-transformation` is the default of `FOCAL_ORG_SLUG`.

## Not in the seed

Descriptions, ministry categories, statuses, dates and all classification fields stay empty. Collectors and the team fill them, with evidence. The second listing of Diia.City under `/projects/regions/city`, mentioned in assignment §5, is not seeded; collector C1 records it.

## Working copy

- `mdt seed` loads this file after the vocabularies. It is idempotent: rows are matched by `slug` (including deleted rows), new rows get provenance `seed`, deleted rows are skipped, and a field that a person has changed is never overwritten. A second run creates no revisions.
- From then on **the database holds the working copy**. Releases regenerate `codebook/` but not this file; the curated dataset of each release is in `releases/`.
