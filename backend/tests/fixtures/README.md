# Test fixtures

Responses of the source hosts, captured once in Phase 0b (2026-10-29) for the offline tests of the Phase 2 collectors and of the polite HTTP client, plus synthetic Wayback Machine responses written by hand for C5 (see "Synthetic fixtures"). The source checks behind them are documented in [`docs/SOURCES.md`](../../../docs/SOURCES.md); the collector strategy is in [`PLAN.md`](../../../PLAN.md) §5.2.

**Fixtures are not data.** They are test input for parsers. Nothing in this folder is a fact for the dataset, nothing here is imported, and no value may be copied from a fixture into the seed, the codebook or the database. Every fixture is a snapshot of one day; the live sources have changed since and will change again.

## Layout

One directory per collector or shared component (the names follow `PLAN.md` §5.2):

| Directory | Collector or component | Source |
|---|---|---|
| `ministry_projects/` | C1 `ministry_projects` | S1 thedigital.gov.ua/projects |
| `project_sites/` | C2 `project_sites` (generic pass, Diia sites, own project domains) | S2 |
| `digitalstate_catalog/` | C2a `digitalstate_catalog` (specialised C2) | S2 (C-1) |
| `diia_catalog/` | C3 `diia_catalog` | S3 diia.gov.ua/services |
| `diia_guide/` | C3b `diia_guide` | S3 (C-2) guide.diia.gov.ua |
| `plan2/` | C3c one-off snapshot of PlanDiia 2.0 | S3 (C-3) |
| `ministry_news/` | C4 `ministry_news` (news, documents, /ministry, files, microsites) | S4 |
| `kmu_news/` | C4b `kmu_news` | S4b www.kmu.gov.ua |
| `wayback/` | C5 `wayback` | S5 |
| `telegram/` | C7 `telegram` | S7a |
| `ckan/` | C7 `ckan` | S7b data.gov.ua |
| `polite_client/` | shared `PoliteHttpClient` (robots.txt edge cases, block pages) | several |

There are no fixtures for C6 `legal_acts`: zakon.rada.gov.ua and data.rada.gov.ua did not answer from the development environment, and www.kmu.gov.ua disallows `/npas/` in its robots.txt (`docs/SOURCES.md` S6, S4b).

Each fixture is a body file `<name>.<ext>` (HTML, XML, JSON, text or PDF) plus `<name>.meta.json`:

| Key | Meaning |
|---|---|
| `fixture`, `body` | fixture name and body file name |
| `collector`, `source` | directory (collector or component) and source ID in `docs/SOURCES.md` |
| `purpose` | what the fixture is for in tests |
| `url`, `final_url`, `redirects` | requested URL, URL after redirects, redirect hops as `"<status> <url>"` |
| `status`, `retrieved_at`, `content_type`, `headers` | HTTP status, retrieval time (UTC), content type and a subset of the original response headers (lower-case names) |
| `sha256_original`, `bytes_original` | SHA-256 and size of the original capture (`sha256_original_basis` explains the rare cases where only the decoded robots.txt text was kept) |
| `sha256_stored`, `bytes_stored` | SHA-256 and size of the body file in this folder |
| `trimmed`, `trim_note` | whether the body differs from the original capture, and exactly what was kept, removed or redacted |
| `licence`, `attribution` | licence as stated by the source (quoted from the page) and the attribution to give |
| `capture` | how and by which Phase 0b explorer the response was fetched |
| `synthetic` | only in synthetic fixtures: `true` (see "Synthetic fixtures" below) |

`backend/tests/test_fixtures.py` checks the format: every body has a meta file with these keys, the stored SHA-256 matches, `trimmed` is a boolean, untrimmed bodies equal the original capture, no body is larger than 1 MiB, no meta file carries a User-Agent field or a `mailto:` address, no body echoes the fetcher's User-Agent or contains the kmu.gov.ua bot-manager token, and, where `CONTACT_EMAIL` is configured locally (not in CI), no fixture contains that address. It also enforces the rules of the synthetic fixtures below.

## How the fixtures were captured

- Phase 0b, 2026-10-29, 12:55 to 14:09 UTC, from the cloud development environment (no target server yet). The orchestrating session and five explorers shared one polite fetcher: 186 logged requests (195 HTTP requests including 9 followed redirects) to 34 hosts, plus 8 logged browser page loads used only to watch XHR/JSON requests (not stored as fixtures). The request log stays outside the repository.
- The fetcher obeyed robots.txt (fetched once per host; an unreachable robots.txt counted as "disallow all"), kept at least 1 s between requests per host across all explorers (5 s for archive hosts; 10 s by hand for data.gov.ua, whose robots.txt sets `Crawl-delay: 10`), honoured `Retry-After` (at most 2 retries), followed at most 5 redirects and recorded them (a redirect was followed at once inside the same request, so a redirect target was requested less than 1 s after the redirect response: 9 hops in the run, 6 of them to the same host), and sent a unique User-Agent with the project name, the repository URL and a contact address (the address is not stored anywhere in the repository).
- No CAPTCHA solving, no proxy rotation, no faked browser fingerprints. Where a host blocked or did not answer (codeua.com: Cloudflare challenge; www.undp.org: HTTP 403; web.archive.org, zakon.rada.gov.ua, data.rada.gov.ua, cms.thedigital.gov.ua: no TLS answer; archive.org: HTTP 429), the explorers stopped and recorded it.
- Three weaknesses of the shared fetcher were found and are now requirements for the Phase 2 client (`docs/SOURCES.md` §2): it followed one redirect (`https://www.kmu.gov.ua/news` to the robots-disallowed `/timeline`) without re-checking robots.txt (that response is not used anywhere); it requested robots.txt with `Accept: text/plain`, which osvita.diia.gov.ua answered with HTTP 406 and the fetcher then treated as "allow all" (kept as `polite_client/robots_osvita_406.txt`; the explorer checked that host's paths by hand against the real file); and its parser (`urllib.robotparser`) applies the first matching rule instead of the longest match required by RFC 9309.

## Trimming, redaction and licences

- **Openly licensed sources (CC BY 4.0)** keep their original bytes: thedigital.gov.ua (footer: "Весь контент доступний за ліцензією Creative Commons Attribution 4.0 International license, якщо не зазначено інше"), guide.diia.gov.ua and 2years.thedigital.gov.ua (same sentence) and www.kmu.gov.ua (the same sentence on Ukrainian pages and "All content is available under the Creative Commons Attribution 4.0 International license unless otherwise noted." on English pages, both with a link to the licence). Exceptions are marked `trimmed: true` and state the changes in `attribution`, as CC BY requires: the kmu.gov.ua pages are excerpts because every raw page embeds a bot-manager token that encodes the requesting client's IP address; the guide registers are reduced for size (18.5 MB and 5.7 MB); one ministry document page has a staff e-mail address replaced by `redacted@example.invalid`.
- **All other sources** are not openly licensed (footers such as "Всі права захищені", "All rights reserved", or no statement at all). Their fixtures are **minimal excerpts**: only the elements a parser needs, with their ancestors as empty shells so that selectors still match, long texts shortened and marked with "…", and no images, media or unrelated scripts. They are kept for software testing only; all rights remain with the owners. HTML excerpts were re-serialised with BeautifulSoup (`html.parser`): tags, attributes and the text of the kept elements are unchanged, but entity spelling and whitespace between the kept parts may differ from the original. Where an embedded data payload had to be kept (the turbo-stream of digitalstate.gov.ua), only prose strings inside it were shortened; its array structure and indices are unchanged. Small technical files without creative content are kept whole: the four robots.txt files `polite_client/robots_data_gov_ua.txt`, `robots_osvita_406.txt`, `robots_osvita_allow_first.txt` and `robots_playcity_no_user_agent.txt`, the URL-only sitemaps `diia_catalog/sitemap_index.xml`, `diia_catalog/sitemap_categories.xml` and `project_sites/playcity_sitemap.xml`, and the 117-byte error body `wayback/availability_429.html`.
- **Redacted wherever they occur:** personal names and e-mail addresses from feeds and contact fields (data.gov.ua authors and contact points, a staff address on a ministry document page, CNAP phone numbers and e-mail addresses), per-request or per-visitor tokens (kmu.gov.ua bot-manager script, Cloudflare `/cdn-cgi/content?id=` values and challenge tokens, Telegram `data-view` attributes and `tme` download tokens, Sentry baggage values), and an embedded public API key (osvita.diia.gov.ua runtime config, removed with its script). Functional addresses of institutions (e.g. `hello@thedigital.gov.ua`) and the names of officials and authors that the pages publish as part of their content are kept.
- The PDF `ministry_news/storage_pdf_draft_resolution.pdf` carries no licence statement of its own; it is linked from a CC BY page. It is the one fixture of unclear licence that keeps its original bytes, because an excerpt would break what it tests (the file name is the MD5 of the content; text extraction). Whether the site footer ("якщо не зазначено інше") covers linked files is decision 6 in `docs/SOURCES.md` §5; if the answer is no, remove or replace this fixture before the repository is pushed.

## Synthetic fixtures

The Wayback Machine did not answer from the development environment (`docs/SOURCES.md` S5), so the C5 tests run against **synthetic fixtures** written by hand in the documented CDX JSON format (`docs/COLLECTORS.md` §8.5): `wayback/synthetic_*`. They are not captures and say nothing about any real site. Rules, enforced by `backend/tests/test_fixtures.py`:

- the fixture name starts with `synthetic_`, and the meta file has every key of the table above plus `"synthetic": true` (a name and the flag always come together);
- `capture` starts with `synthetic:` and cites the documentation the body follows (for C5: the wayback-cdx-server README, as recorded in `docs/SOURCES.md` S5); `licence` is exactly "synthetic test data written for this repository"; `retrieved_at` is the time of writing; `trimmed` is `false` (both SHA-256 values describe the body as written);
- every URL inside the body (gzip bodies are decompressed first) and every source URL the request names (the `url=` value of a CDX query, the original URL of a capture URL) uses a reserved example host: `example.org`, `www.example.org` or `example.com`; every CDX `urlkey`, also inside a resume key, starts with `org,example)` or `com,example)`;
- digests and lengths are obviously made up: every `digest` value starts with `SYNTHETIC` and every `length` value is `0`;
- each CDX fixture's `url` is exactly a query that C5 builds for the test sources file of `docs/COLLECTORS.md` §12.1 (prefix `example.org/projects/`, the synthetic projects and services of `backend/tests/collectors/wayback_helpers.py`); the C5 tests check this.

The real C5 fixtures come from `mdt fixtures capture wayback` on the target server (`docs/COLLECTORS.md` §11). After that capture, the C5 parser tests also run against them, and every difference from the documented format is recorded in `docs/SOURCES.md` S5 and corrected in the synthetic fixtures.

## Adding or refreshing fixtures

Phase 2 adds `mdt fixtures capture <source>` (`PLAN.md` §5.7), which fetches a fixed URL list through the polite client and writes the same body and meta format. Until then, add a fixture by hand only from a capture with known URL, time and SHA-256, keep the format above, and run `uv run pytest -q tests/test_fixtures.py` in `backend/`. Captures still missing are listed in `docs/SOURCES.md` (Phase 0b results, "from the target server").

## Fixture list

111 fixtures in 12 directories, 3.0 MB of bodies: 44 with the original bytes, 59 trimmed or redacted, 8 synthetic (written by hand, see "Synthetic fixtures").

| Directory | Fixture | Source | URL | HTTP | Trimmed |
|---|---|---|---|---|---|
| `ckan` | `dataset_dcat_jsonld.json` | S7b | https://data.gov.ua/dataset/809b0526-3526-4a3b-a88d-5df784674f5a.jsonld | 200 | yes |
| `ckan` | `dataset_page.html` | S7b | https://data.gov.ua/dataset/96612ea3-53b5-45db-be0b-377cac72704d | 200 | yes |
| `ckan` | `org_feed_atom.xml` | S7b | https://data.gov.ua/feeds/organization/mincyfry.atom | 200 | yes |
| `ckan` | `org_page1.html` | S7b | https://data.gov.ua/organization/mincyfry | 200 | yes |
| `ckan` | `org_page2.html` | S7b | https://data.gov.ua/organization/mincyfry?page=2 | 200 | yes |
| `digitalstate_catalog` | `project_govtech_diia.html` | S2 (C-1) | https://digitalstate.gov.ua/projects/govtech/diia | 200 | yes |
| `digitalstate_catalog` | `projects_page1.html` | S2 (C-1) | https://digitalstate.gov.ua/projects | 200 | yes |
| `digitalstate_catalog` | `projects_page3_last.html` | S2 (C-1) | https://digitalstate.gov.ua/projects/page/3 | 200 | yes |
| `digitalstate_catalog` | `projects_uk_page1.html` | S2 (C-1) | https://digitalstate.gov.ua/uk/projects | 200 | yes |
| `diia_catalog` | `catalog_root.html` | S3 | https://diia.gov.ua/services | 200 | yes |
| `diia_catalog` | `category_gromadyanam.html` | S3 | https://diia.gov.ua/services/categories/gromadyanam | 200 | yes |
| `diia_catalog` | `service_poshkodzhene_majno.html` | S3 | https://diia.gov.ua/services/poshkodzhene-majno | 200 | yes |
| `diia_catalog` | `service_reyestraciya_fop.html` | S3 | https://diia.gov.ua/services/reyestraciya-fop | 200 | yes |
| `diia_catalog` | `service_vityag_pro_nesudimist.html` | S3 | https://diia.gov.ua/services/vityag-pro-nesudimist | 200 | yes |
| `diia_catalog` | `sitemap_categories.xml` | S3 | https://diia.gov.ua/sitemap-kitsoftservicesmodelscategory-1.xml | 200 | no |
| `diia_catalog` | `sitemap_index.xml` | S3 | https://diia.gov.ua/sitemap.xml | 200 | no |
| `diia_catalog` | `sitemap_services.xml` | S3 | https://diia.gov.ua/sitemap-kitsoftservicesmodelsservice-1.xml | 200 | yes |
| `diia_catalog` | `subcategory_biznesu_pidpriyemnictvo.html` | S3 | https://diia.gov.ua/services/categories/biznesu/pidpriyemnictvo | 200 | yes |
| `diia_guide` | `guide_asc_json.json` | S3 (C-2) | https://guide.diia.gov.ua/asc/download/json/ | 200 | yes |
| `diia_guide` | `guide_card_00031.html` | S3 (C-2) | https://guide.diia.gov.ua/view/derzhavna-reiestratsiia-shliubu-097b2fa9-2c83-4ea9-988f-b5c6b48f71fe | 200 | no |
| `diia_guide` | `guide_home.html` | S3 (C-2) | https://guide.diia.gov.ua/ | 200 | no |
| `diia_guide` | `guide_register_json.json` | S3 (C-2) | https://guide.diia.gov.ua/register/download/json/ | 200 | yes |
| `diia_guide` | `guide_sitemap_500.html` | S3 (C-2) | https://guide.diia.gov.ua/sitemap.xml | 500 | no |
| `kmu_news` | `news_en_2019_regulation.html` | S4b | https://www.kmu.gov.ua/en/news/uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi | 200 | yes |
| `kmu_news` | `news_en_2019_regulation_refetch.html` | S4b | https://www.kmu.gov.ua/en/news/uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi | 200 | yes |
| `kmu_news` | `news_en_2025_plans.html` | S4b | https://www.kmu.gov.ua/en/news/hranty-brave1-pilotnyi-zapusk-5g-ta-novi-posluhy-v-dii-mykhailo-fedorov-prezentuvav-plany-mintsyfry-na-2025-2026-roky | 200 | yes |
| `kmu_news` | `news_uk_2019_komanda_duplicate_pair.html` | S4b | https://www.kmu.gov.ua/news/komanda-ministerstva-cifrovoyi-transformaciyi-prezentuvala-proyekti-z-cifrovoyi-osviti-ta-rozvitku-malogo-ta-serednogo-biznesu | 200 | yes |
| `kmu_news` | `news_uk_2019_regulation.html` | S4b | https://www.kmu.gov.ua/news/uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi | 200 | yes |
| `kmu_news` | `news_uk_2020_other_body.html` | S4b | https://www.kmu.gov.ua/news/uryad-sproshchuye-mehanizmi-nadannya-poslug-vpo-za-dopomogoyu-mobilnogo-zastosunku-diya | 200 | yes |
| `kmu_news` | `news_uk_2025_playcity.html` | S4b | https://www.kmu.gov.ua/news/pleisiti-stane-novym-rehuliatorom-azartnykh-ihor-uriad-ukhvalyv-postanovu | 200 | yes |
| `kmu_news` | `news_uk_2025_year_review.html` | S4b | https://www.kmu.gov.ua/news/vid-shi-asystenta-v-dii-do-suputnykovoho-zviazku-ta-oboronnykh-tekhnolohii-pidsumky-mintsyfry-u-2025-rotsi | 200 | yes |
| `kmu_news` | `npa_sitemap_excerpt.xml` | S4b | https://www.kmu.gov.ua/sitemap-kitsoft-npa-models-act-1.xml | 200 | yes |
| `kmu_news` | `sitemap_index.xml` | S4b | https://www.kmu.gov.ua/sitemap.xml | 200 | no |
| `kmu_news` | `sitemap_posts_en_excerpt.xml` | S4b | https://www.kmu.gov.ua/en/sitemap-rainlab-blog-models-post-1.xml | 200 | yes |
| `kmu_news` | `sitemap_posts_uk_2016_2021_excerpt.xml` | S4b | https://www.kmu.gov.ua/sitemap-rainlab-blog-models-post-2.xml | 200 | yes |
| `kmu_news` | `sitemap_posts_uk_2021_2026_excerpt.xml` | S4b | https://www.kmu.gov.ua/sitemap-rainlab-blog-models-post-1.xml | 200 | yes |
| `ministry_news` | `document_page_content.html` | S4 | https://thedigital.gov.ua/documents/ministry/povidomlennia-pro-opryliudnennia-na-hromadske-obhovorennia-proektu-postanovy-kabinetu-ministriv-ukrayiny-deiaki-pytannia-rozvytku-ukrayinskykh-velykykh-movnykh-modeley | 200 | yes |
| `ministry_news` | `documents_list_page1.html` | S4 | https://thedigital.gov.ua/documents | 200 | no |
| `ministry_news` | `documents_list_page106.html` | S4 | https://thedigital.gov.ua/documents/page/106 | 200 | no |
| `ministry_news` | `microsite_2025_report.html` | S4 (C-4) | https://2025.thedigital.gov.ua/ | 200 | yes |
| `ministry_news` | `microsite_2years_report.html` | S4 (C-4) | https://2years.thedigital.gov.ua/ | 200 | no |
| `ministry_news` | `ministry_page.html` | S4 | https://thedigital.gov.ua/ministry | 200 | no |
| `ministry_news` | `news_article_2019.html` | S4 | https://thedigital.gov.ua/news/education/komanda-ministrerstva-prezentuvala-proekty-tsyfrovoi-osvity | 200 | no |
| `ministry_news` | `news_article_2022.html` | S4 | https://thedigital.gov.ua/news/technologies/nova-posluga-v-dii-oformlennya-sotsialnoi-dopomogi-dlya-tikh-khto-vtrativ-robotu-pid-chas-viyni | 200 | no |
| `ministry_news` | `news_article_2026.html` | S4 | https://thedigital.gov.ua/news/postanovy-uriadu/uriad-ukhvalyv-zapusk-yedumky-v-diyi-vyrishuvaty-problemy-hromady-teper-mozna-bez-paperovykh-pidpysiv | 200 | no |
| `ministry_news` | `news_article_en_2024.html` | S4 | https://thedigital.gov.ua/news/technologies/foreigners-can-start-and-run-business-in-ukraine-online-launch-of-the-uresidency-program | 200 | no |
| `ministry_news` | `news_article_redirect_2021.html` | S4 | https://thedigital.gov.ua/news/mintsifra-prezentue-94-proekti-tsifrovoi-transformatsii | 200 | no |
| `ministry_news` | `news_list_page1.html` | S4 | https://thedigital.gov.ua/news | 200 | no |
| `ministry_news` | `news_list_page366.html` | S4 | https://thedigital.gov.ua/news/page/366 | 200 | no |
| `ministry_news` | `not_found_en.html` | S4 | https://thedigital.gov.ua/en | 404 | no |
| `ministry_news` | `sitemap_latest100.xml` | S4 | https://thedigital.gov.ua/sitemap.xml | 200 | no |
| `ministry_news` | `storage_pdf_draft_resolution.pdf` | S4 | https://storage.thedigital.gov.ua/files/5/15/fa231dbe2422c63e946dc25c3c26f154.pdf | 200 | no |
| `ministry_projects` | `category_army.html` | S1 | https://thedigital.gov.ua/projects/army | 200 | no |
| `ministry_projects` | `category_business.html` | S1 | https://thedigital.gov.ua/projects/business | 200 | no |
| `ministry_projects` | `category_education.html` | S1 | https://thedigital.gov.ua/projects/education | 200 | no |
| `ministry_projects` | `category_how_tos_additional.html` | S1 | https://thedigital.gov.ua/projects/how-tos | 200 | no |
| `ministry_projects` | `category_progress.html` | S1 | https://thedigital.gov.ua/projects/progress | 200 | no |
| `ministry_projects` | `category_regions.html` | S1 | https://thedigital.gov.ua/projects/regions | 200 | no |
| `ministry_projects` | `category_technologies.html` | S1 | https://thedigital.gov.ua/projects/technologies | 200 | no |
| `ministry_projects` | `legacy_e_residency_404.html` | S1 | https://thedigital.gov.ua/projects/e-residency | 404 | no |
| `ministry_projects` | `link_entry_winwin_redirect.html` | S1 | https://thedigital.gov.ua/projects/technologies/winwin | 200 | yes |
| `ministry_projects` | `project_brave1_technologies.html` | S1 | https://thedigital.gov.ua/projects/technologies/brave1 | 200 | no |
| `ministry_projects` | `project_diiatsyfrova_hromada_additional_rubric.html` | S1 | https://thedigital.gov.ua/projects/technologies/diiatsyfrova-hromada | 200 | no |
| `ministry_projects` | `project_virtual_assets_business.html` | S1 | https://thedigital.gov.ua/projects/business/virtual_assets | 200 | no |
| `ministry_projects` | `project_yevrointegraciya_progress.html` | S1 | https://thedigital.gov.ua/projects/progress/yevrointegraciya | 200 | no |
| `ministry_projects` | `projects_data_turbostream.txt` | S1 | https://thedigital.gov.ua/projects.data | 200 | no |
| `ministry_projects` | `projects_page1.html` | S1 | https://thedigital.gov.ua/projects | 200 | no |
| `ministry_projects` | `projects_page2.html` | S1 | https://thedigital.gov.ua/projects/page/2 | 200 | no |
| `ministry_projects` | `variant_regions_city_same_record.html` | S1 | https://thedigital.gov.ua/projects/regions/city | 200 | no |
| `ministry_projects` | `variant_yevrointegraciya_302.html` | S1 | https://thedigital.gov.ua/projects/yevrointegraciya | 200 | no |
| `plan2` | `plan2_projects_json.json` | S3 (C-3) | https://plan2-backend.diia.gov.ua/api/front/project | 200 | yes |
| `polite_client` | `robots_codeua_cloudflare_challenge.html` | S2 | https://codeua.com/robots.txt | 403 | yes |
| `polite_client` | `robots_data_gov_ua.txt` | S7b | https://data.gov.ua/robots.txt | 200 | no |
| `polite_client` | `robots_kmu.txt` | S4b | https://www.kmu.gov.ua/robots.txt | 200 | no |
| `polite_client` | `robots_osvita_406.txt` | S2 | https://osvita.diia.gov.ua/robots.txt | 406 | no |
| `polite_client` | `robots_osvita_allow_first.txt` | S2 | https://osvita.diia.gov.ua/robots.txt | 200 | no |
| `polite_client` | `robots_plan2_html_200.html` | S3 (C-3) | https://plan2.diia.gov.ua/robots.txt | 200 | yes |
| `polite_client` | `robots_playcity_no_user_agent.txt` | S2 | https://playcity.gov.ua/robots.txt | 200 | no |
| `polite_client` | `robots_usf_content_signal_with_html.txt` | S2 | https://usf.com.ua/robots.txt | 200 | yes |
| `project_sites` | `center_home.html` | S2 | https://center.diia.gov.ua/ | 200 | yes |
| `project_sites` | `center_map_wartime.html` | S2 | https://center.diia.gov.ua/cnap-map | 200 | yes |
| `project_sites` | `center_sitemap.xml` | S2 | https://center.diia.gov.ua/sitemap.xml | 200 | yes |
| `project_sites` | `e_pidpryemets_home.html` | S2 | https://e-pidpryemets.diia.gov.ua/ | 200 | yes |
| `project_sites` | `osvita_home.html` | S2 | https://osvita.diia.gov.ua/ | 200 | yes |
| `project_sites` | `osvita_sitemap.xml` | S2 | https://osvita.diia.gov.ua/sitemap.xml | 200 | yes |
| `project_sites` | `playcity_home.html` | S2 | https://playcity.gov.ua/ | 200 | yes |
| `project_sites` | `playcity_pravovi_zasady.html` | S2 | https://playcity.gov.ua/pravovi-zasady | 200 | yes |
| `project_sites` | `playcity_sitemap.xml` | S2 | https://playcity.gov.ua/sitemap.xml | 200 | no |
| `project_sites` | `se_portal_page.html` | S2 | https://se.diia.gov.ua/en/unified-state-web-portal-of-electronic-services-diia | 200 | yes |
| `project_sites` | `u24_about.html` | S2 | https://u24.gov.ua/about | 200 | yes |
| `project_sites` | `u24_home.html` | S2 | https://u24.gov.ua/ | 200 | yes |
| `project_sites` | `u24_projects.html` | S2 | https://u24.gov.ua/projects | 200 | yes |
| `project_sites` | `united24media_about.html` | S2 | https://united24media.com/about | 200 | yes |
| `project_sites` | `united24media_home.html` | S2 | https://united24media.com/ | 200 | yes |
| `project_sites` | `usf_about.html` | S2 | https://usf.com.ua/about-usf | 200 | yes |
| `project_sites` | `usf_home.html` | S2 | https://usf.com.ua/ | 200 | yes |
| `project_sites` | `usf_program_startup_edge.html` | S2 | https://usf.com.ua/programs/startup-edge | 200 | yes |
| `project_sites` | `usf_sitemap_soft404.html` | S2 | https://usf.com.ua/sitemap.xml | 200 | yes |
| `project_sites` | `winwin_home_csr_shell.html` | S2 | https://thedigital.gov.ua/projects/technologies/winwin | 200 | yes |
| `telegram` | `mintsyfra_preview_before_8558.html` | S7a | https://t.me/s/mintsyfra?before=8558 | 200 | yes |
| `telegram` | `mintsyfra_preview_latest.html` | S7a | https://t.me/s/mintsyfra | 200 | yes |
| `telegram` | `mintsyfra_preview_oldest_before_30.html` | S7a | https://t.me/s/mintsyfra?before=30 | 200 | yes |
| `wayback` | `availability_429.html` | S5 | https://archive.org/wayback/available?url=thedigital.gov.ua/projects&timestamp=20191231 | 429 | no |
| `wayback` | `synthetic_capture_redirected.html` | S5 | https://web.archive.org/web/20200102000000id_/https://example.org/projects/technologies/example-gamma | 200 | synthetic |
| `wayback` | `synthetic_cdx_empty.json` | S5 | https://web.archive.org/cdx/search/cdx?url=www.example.org/&output=json&fl=urlkey,timestamp,original,statuscode,mimetype&filter=statuscode:200&limit=1 | 200 | synthetic |
| `wayback` | `synthetic_cdx_exact_limit1.json` | S5 | https://web.archive.org/cdx/search/cdx?url=example.com/&output=json&fl=urlkey,timestamp,original,statuscode,mimetype&filter=statuscode:200&limit=1 | 200 | synthetic |
| `wayback` | `synthetic_cdx_extra_columns.json` | S5 | https://web.archive.org/cdx/search/cdx?url=example.org/services/example-one&output=json&fl=urlkey,timestamp,original,statuscode,mimetype&filter=statuscode:200&limit=1 | 200 | synthetic |
| `wayback` | `synthetic_cdx_gzipped.json.gz` | S5 | https://web.archive.org/cdx/search/cdx?url=example.org/services/example-two&output=json&fl=urlkey,timestamp,original,statuscode,mimetype&filter=statuscode:200&limit=1 | 200 | synthetic |
| `wayback` | `synthetic_cdx_header_only.json` | S5 | https://web.archive.org/cdx/search/cdx?url=example.org/about&output=json&fl=urlkey,timestamp,original,statuscode,mimetype&filter=statuscode:200&limit=1 | 200 | synthetic |
| `wayback` | `synthetic_cdx_prefix_collapse.json` | S5 | https://web.archive.org/cdx/search/cdx?url=example.org/projects/&matchType=prefix&collapse=urlkey&output=json&fl=urlkey,timestamp,original,statuscode,mimetype&filter=statuscode:200&limit=5000&showResumeKey=true&resumeKey=org%2Cexample%29%2Fprojects%2Fexample-beta+20160704000000%21 | 200 | synthetic |
| `wayback` | `synthetic_cdx_resume_key.json` | S5 | https://web.archive.org/cdx/search/cdx?url=example.org/projects/&matchType=prefix&collapse=urlkey&output=json&fl=urlkey,timestamp,original,statuscode,mimetype&filter=statuscode:200&limit=5000&showResumeKey=true | 200 | synthetic |
