# Sources (draft)

> **Status:** Phase 0 draft, 2026-10-28.
> **No source has been accessed directly yet:** the development environment blocks all source hosts (see `PLAN.md` §2.2). Everything below comes from the assignment, the paper, the official Wayback CDX documentation or web-search results, labelled as follows.
> **Labels:** **[user]** assignment (data lead, 2026-10-28) · **[paper]** paper.docx · **[doc]** official documentation retrieved 2026-10-28 · **[search]** URL/title in search results 2026-10-28 (content not retrieved) · **[search-summary]** only in the search tool's model summary · **[hypothesis]** to be verified.
> **Status values:** `planned` (not yet checked) · `partially verified` · `verified` (Phase 0b done) · `blocked` · `deprecated`.

## 1. Register

| ID | Source | Base URL(s) | Planned access | Coverage / period | Licence | Status |
|---|---|---|---|---|---|---|
| S1 | Ministry project list | `https://thedigital.gov.ua/projects` | structured endpoint if found, else HTML | current listing only; history via S5 | CC BY 4.0 per footer, unless stated otherwise [user] | planned |
| S2 | Project pages and project websites | ministry project pages + 7 known own domains (§S2) | generic HTML + sitemaps; specialised collectors where structured | current; history via S5 | per site, unknown | planned |
| S3 | Diia portal service catalogue | `https://diia.gov.ua/services` | structured endpoint if found, else HTML | current; history via S5 | unknown | planned |
| S4 | Ministry news, documents, ministry pages | `https://thedigital.gov.ua/news`, `/documents`, `/ministry` | listings + detail pages; PDFs | archive depth unknown (titles from about 2020/21 seen [search]) | CC BY 4.0 per footer [user] | planned |
| S4b | Ministry news on the Government portal | `https://www.kmu.gov.ua/news/…`, `/en/news/…` | discovery strategy open (no per-ministry listing seen) | items from 2019 seen [search] | unknown (CC BY 4.0 [hypothesis]) | planned |
| S5 | Wayback Machine CDX API and captures | `https://web.archive.org/cdx/search/cdx`, `https://web.archive.org/web/<ts>id_/<url>` | CDX JSON; original-bytes captures | per URL; unknown | archived third-party content; cite as archive copy | planned (API parameters [doc]) |
| S6 | Legal acts | `https://zakon.rada.gov.ua/laws/show/<id>` | follow links only | per act | official texts [hypothesis: free reuse] | planned |
| S7a | Telegram channel (web preview) | `https://t.me/s/mintsyfra` | preview HTML, `?before=<id>` | unknown | unknown | planned (optional) |
| S7b | Open data portal (CKAN) | `https://data.gov.ua/organization/mincyfry` | CKAN API if confirmed | per dataset | per dataset | planned (optional) |
| S8 | Manual additions | URL or upload | polite client / upload | — | per document | available |
| C-1 | Digital State UA project catalogue | `https://digitalstate.gov.ua/projects/<category>/<slug>` | to assess | unknown | unknown | candidate |
| C-2 | Diia service guide (+ reported open data) | `https://guide.diia.gov.ua/view/<slug>-<uuid>` | open data if it exists, else HTML | unknown | unknown | candidate |
| C-3 | Diia dashboard | `https://plan2.diia.gov.ua/` | to assess | unknown | unknown | candidate |
| C-4 | Year-in-review microsites | `https://2years.thedigital.gov.ua/`, `https://5years.thedigital.gov.ua/`, `https://2025.thedigital.gov.ua/` | treated as documents (S4) | single snapshots | CC BY 4.0 [hypothesis] | candidate |

## 2. Collection policy (all sources)

- **Robots.txt** is obeyed. **Default throttling** is about 1 request per second per host; the Wayback Machine gets 1 request per 5 s. Backoff on 429/5xx honours `Retry-After`.
- **User-Agent:** `MDT-Portfolio-Research/<version> (+<repository URL>; mailto:<CONTACT_EMAIL from .env>)`.
- **No circumvention:** no CAPTCHA solving, no proxy rotation, no faked browser fingerprints. If a source blocks: the run is marked `partial`, logged and reported, and the collector falls back to the Wayback Machine only where configured.
- **Conditional requests** (ETag/Last-Modified). Every response is stored unchanged as a raw snapshot (sha256, timestamp, HTTP status).
- **Licence per source** is recorded here and in `sources.yaml`. Releases contain full texts only from openly licensed sources (see `PLAN.md` §6.7).

---

## S1 — Ministry project list

- **URLs:** `https://thedigital.gov.ua/projects` (paginated, 20 entries on 2 pages on 2026-10-28 [user]). Category listings such as `https://thedigital.gov.ua/projects/technologies` [search] and `https://thedigital.gov.ua/projects/progress` (title "Досягнення — Проєкти — Міністерство цифрової трансформації України") [search].
- **Role:** the portfolio backbone. Per entry: name, ministry category, short description, link to the project page or an external domain [user]. New or disappeared entries become proposals.
- **Known structure:**
  - Project pages: `/projects/<category>/<slug>`; a slug can equal its category (e.g. `/projects/business/business`, `/projects/education/osvita`) [search].
  - Category paths in the seed: `technologies`, `business`, `regions`, `education`, `progress` [user].
  - Page-title pattern: "<Page> — <Section> — Міністерство цифрової трансформації України" [search].
- **Known limits:**
  - Beta relaunch [user].
  - Categories are inconsistent: Diia.City appears under `/projects/business/city` and `/projects/regions/city` [user].
  - Several projects link directly to external domains (WINWIN, USF, CodeUA, UNITED24, UNITED24 Media, Digital State UA) [user].
  - The search index holds `https://thedigital.gov.ua/projects/yevrointegraciya` [search], while the seed URL (checked by the data lead) is `https://thedigital.gov.ua/projects/progress/yevrointegraciya` [user]. Possibly a redirect or an older route [hypothesis].
- **Licence:** CC BY 4.0 per footer unless stated otherwise [user]; the exact footer wording is to be captured.
- **Phase 0b checklist:**
  - robots.txt; sitemap(s); RSS.
  - Does the frontend load JSON (XHR log via Playwright on `/projects` and one project page)? Is framework data embedded in the HTML?
  - Pagination parameters; full category list and labels (uk/en).
  - Do project pages carry dates (published/updated)?
  - Redirect behaviour of URL variants; exact licence footer text.
  - Fixtures: listing pages 1–2, one page per category, 3 project pages.

## S2 — Project pages and project websites

- **Role:** descriptions, operator and owner statements, outbound links (legal acts, partners), structured offers (programmes, grants, courses, fundraising directions).
- **Own domains seen in search results:**
  - `https://center.diia.gov.ua/centr-diia` ("Дія. Платформа Центрів"), with `/blog/<slug>` and `/uploads/…` paths [search]
  - `https://osvita.diia.gov.ua/en/hubs-news/ebook-program` (paths `/en/hubs-news/<slug>`) [search]
  - `https://playcity.gov.ua/`, with a legal-basis page `https://playcity.gov.ua/pravovi-zasady` [search]
  - `https://u24.gov.ua/news/24000_friends_of_ukraine` [search]
  - `https://united24media.com/profiles/companies/united24` [search]
  - `https://codeua.com/about-us` [search]
  - `https://digitalstate.gov.ua/projects/govtech/diia`: Digital State UA has its own project catalogue with `/projects/<category>/<slug>` [search] (see C-1)
  - `https://e-pidpryemets.diia.gov.ua/` ("е-Підприємець") [search]
  - `https://se.diia.gov.ua/en/unified-state-web-portal-of-electronic-services-diia` [search]; that it belongs to the state enterprise "Дія" is [hypothesis]
- **Not seen in search results:** `winwin.gov.ua`, `usf.com.ua`, any Brave1 domain [search]. The seed entry URLs for WINWIN and USF come from the data lead [user].
- **Known limits:** heterogeneous sites; licences unknown; some pages may be outdated (e.g. PlayCity's site reportedly still names the old coordination [search-summary]).
- **Phase 0b checklist:**
  - For every domain: robots.txt, sitemap, about page, footer (operator, licence), structured offers (JSON/XHR).
  - Resolve the official domains of Brave1, Mriia, CDTO Campus, Diia.Engine, Diia.Digital Community, uResidency, Virtual Assets through the ministry pages (do not guess).
  - Decide on specialised collectors.
  - Fixtures: home and about page per domain; one page per structured offer.

## S3 — Diia portal service catalogue

- **URLs:**
  - `https://diia.gov.ua/services` [user]
  - category tree `https://diia.gov.ua/services/categories/biznesu` and `https://diia.gov.ua/services/categories/biznesu/pidpriyemnictvo` [search], i.e. `/services/categories/<audience>/<subcategory>`
  - single services `/services/<slug>` [user] (not seen in search results)
  - portal news `https://diia.gov.ua/news/podatki-v-dekilka-klikiv-na-diyi-zyavlyatsya-novi-poslugi-dlya-biznesu` [search]
- **Role:** service inventory with section (rubric) and audience.
- **Known limits:**
  - Diia app services are not fully listed on the web [user]; they enter as proposals from announcements.
  - The host is also indexed with a trailing dot (`https://diia.gov.ua./`) [search], so hosts need normalising.
  - The catalogue's history is only available through the Wayback Machine (layout eras).
- **Related sources:**
  - **C-2 service guide** `guide.diia.gov.ua` ("Гід онлайн Дія"): service cards at `/view/<slug>-<uuid>` [search], e.g. `https://guide.diia.gov.ua/view/derzhavna-reiestratsiia-shliubu-097b2fa9-2c83-4ea9-988f-b5c6b48f71fe`. Launch announcement: `https://www.kmu.gov.ua/news/v-ukrayini-zyavivsya-gid-z-derzhavnih-poslug` [search]. Reportedly published as open data in Excel and JSON, with around 1 000 to 1 500+ services, 17 categories and 36 life events [search-summary].
  - **C-3** `https://plan2.diia.gov.ua/` (title "Державні послуги онлайн") [search]; described in an academic paper as the public dashboard of digital-transformation projects [search-summary].
- **Phase 0b checklist:**
  - robots.txt; sitemap; XHR/JSON for the catalogue and service pages; audience slug for citizens; number of categories; fields on a service page (description, channels, legal basis links).
  - Does the guide's open dataset exist on data.gov.ua, with versions (pre/post 2022)? Mapping between guide UUIDs and portal slugs.
  - CDX coverage of `diia.gov.ua/services/`.
  - Fixtures: catalogue root, 2 category pages, 3 service pages; one historic capture per layout era.

## S4 — Ministry news, documents and pages (thedigital.gov.ua)

- **URLs and structure:**
  - **News:** two URL schemes coexist in the search index [search]:
    - `/news/<slug>` (older transliteration style), e.g. `https://thedigital.gov.ua/news/mintsifra-prezentue-94-proekti-tsifrovoi-transformatsii`, `https://thedigital.gov.ua/news/zmina-mistsya-reestratsii-onlayn-ta-rezhim-bez-paperu-mikhaylo-fedorov-anonsuvav-masshtabni-proekti-mintsifri-u-2021-rotsi`
    - `/news/<category>/<slug>` (the same categories as projects), e.g. `https://thedigital.gov.ua/news/progress/zberihayemo-temp-oleksandr-borniakov-ocholyv-mintsyfry`, `https://thedigital.gov.ua/news/technologies/foreigners-can-start-and-run-business-in-ukraine-online-launch-of-the-uresidency-program`
    - Which scheme is current and whether old URLs redirect: [hypothesis].
  - News rubrics including "Постанови Уряду" [user] (not seen in search).
  - **Documents:** `https://thedigital.gov.ua/documents` with sub-sections `/documents/community` (Громадянам), `/documents/legislation` (Законодавство), `/documents/ministry` (Міністерство) [search]. The listing reportedly shows dates as DD.MM.YYYY ("Розпорядження від 16.10.2026 …") [search-summary].
  - **Ministry page:** `https://thedigital.gov.ua/ministry` ("Про нас") [search]; cited in the paper [paper].
  - **Files:** `https://storage.thedigital.gov.ua/files/<x>/<yx>/<32 hex>.pdf`, hash-sharded and not enumerable, so they can only be discovered through links [search]. An older path scheme also exists: `https://thedigital.gov.ua/storage/uploads/files/page/community/budget/Паспорт_бюджетної_програми_2901010_на_2020_рік_зміни.pdf` [search].
  - **Annual reports** (attributions only in the search summary): results report 2022 `https://storage.thedigital.gov.ua/files/2/62/c533ab6febc2ec3ca780f257703a262e.pdf`, order approving it `https://storage.thedigital.gov.ua/files/6/c6/5ccc6fb6900195e357b68202b83a7c68.pdf`, work plan 2024 `https://storage.thedigital.gov.ua/files/5/85/b4ff9273c9b9a51580608575a2f91850.pdf` [search-summary]. A copy of a 2021 report: `https://nrat.ukrintei.ua/zvit-minczyfry-za-2021-rik/?pdf=16008` [search]. Reports for 2019, 2020, 2023 and 2025 were not found.
  - **Year-in-review microsites (C-4):** `https://2025.thedigital.gov.ua/` ("Підсумки року роботи Мінцифри 2025"), `https://2years.thedigital.gov.ua/` ("Мінцифра: два роки в дії"), `https://5years.thedigital.gov.ua/` [search]. Also `https://ai.thedigital.gov.ua/en/vision` [search].
- **Coverage:** news titles from about 2020/21 seen; no 2019 items seen [search]. Archive depth is unknown.
- **Known limits:**
  - Beta relaunch; dates partly without year ("22 жов., 14:00") [user].
  - Transliteration styles differ between thedigital.gov.ua, kmu.gov.ua and guide.diia.gov.ua [search], so items cannot be matched across sites by slug.
- **Licence:** CC BY 4.0 per footer [user].
- **Phase 0b checklist:**
  - robots.txt; sitemap; RSS; XHR/JSON for news listings and articles.
  - Pagination and depth (binary search over listing pages until the oldest item).
  - Machine-readable dates (`<time datetime>`, JSON-LD, meta tags).
  - Rubric list; document listing fields; how attachments are linked.
  - Redirects of old URLs; English content.
  - Fixtures: 2 listing pages (newest/oldest), 3 articles (different years), 1 document page, 1 PDF.

## S4b — Ministry news on the Government portal (kmu.gov.ua)

- **URLs and structure:**
  - **News:**
    - Ukrainian `https://www.kmu.gov.ua/news/<slug>`, e.g. `https://www.kmu.gov.ua/news/uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi` [search]
    - English `https://www.kmu.gov.ua/en/news/<slug>` with Ukrainian-transliterated slugs, e.g. `https://www.kmu.gov.ua/en/news/mincifri-pracyuye-nad-tehnologichnim-rozvitkom-ukrayini` [search]
    - Two transliteration styles in slugs (`cifrovoyi`/`mincifra` vs. `tsyfrovykh`/`mintsyfry`); slugs do not always match titles [search].
  - **Legal acts:** `https://www.kmu.gov.ua/npas/<slug><suffix>`, e.g. `https://www.kmu.gov.ua/npas/pitannya-ministerstva-cifrovoyi-t180919` [search]. The suffix probably encodes a date (DDMMYY) [hypothesis].
  - **Attachments:** `https://www.kmu.gov.ua/storage/app/uploads/public/…` [search].
  - **No per-ministry listing, tag or filter** was seen [search].
- **Coverage:** ministry items from 2019 seen, e.g. `https://www.kmu.gov.ua/news/komanda-ministerstva-cifrovoyi-transformaciyi-prezentuvala-proyekti-z-cifrovoyi-osviti-ta-rozvitku-malogo-ta-serednogo-biznesu` [search]; their dates (Sep–Nov 2019) are [search-summary].
- **High-priority items found:**
  - 2025 year-in-review: `https://www.kmu.gov.ua/news/vid-shi-asystenta-v-dii-do-suputnykovoho-zviazku-ta-oboronnykh-tekhnolohii-pidsumky-mintsyfry-u-2025-rotsi` [search]
  - plans for 2025–2026 (EN): `https://www.kmu.gov.ua/en/news/hranty-brave1-pilotnyi-zapusk-5g-ta-novi-posluhy-v-dii-mykhailo-fedorov-prezentuvav-plany-mintsyfry-na-2025-2026-roky` [search]
  - retrospective: `https://www.kmu.gov.ua/news/vid-startapu-do-it-kompanii-iak-mintsyfry-pobuduvalo-naizruchnishu-tsyfrovu-derzhavu` [search]
  - regional results 2023 and 2024: `https://www.kmu.gov.ua/news/rezultaty-tsyfrovoi-transformatsii-v-rehionakh-ukrainy-za-2023-rik`, `https://www.kmu.gov.ua/news/mintsyfry-pro-rezultaty-tsyfrovoi-transformatsii-v-rehionakh-ukrainy-za-2024-rik` [search]
- **Phase 0b checklist:**
  - robots.txt; sitemap; site search and filters; pagination; date format on pages.
  - Do UA and EN versions share slugs? Licence footer.
  - Discovery strategy (ministry filter, tags, sitemap, or CDX prefix with slug keywords in both transliteration styles).
  - Fixtures: 1 listing, 3 news pages (UA 2019, UA 2025, EN), 1 `/npas/` page.

## S5 — Wayback Machine (CDX API)

- **Documentation:** `https://raw.githubusercontent.com/internetarchive/wayback/master/wayback-cdx-server/README.md` (read 2026-10-28) [doc].
- **Verified parameters** [doc]:
  - `url`; `matchType=exact|prefix|host|domain` (also as wildcards `url=…/*`); `output=json` (first row = field names).
  - Public fields `urlkey,timestamp,original,mimetype,statuscode,digest,length`, selectable with `fl=`.
  - `from=`/`to=` (1–14 digits, inclusive); `filter=[!]field:regex` (repeatable).
  - `collapse=field[:N]` (adjacent duplicates; `collapse=urlkey` with prefix queries gives one row per URL, "may be slow").
  - `limit=N` (first N), `limit=-N` (last N, slow), `fastLatest=true`, `offset=`; maximum 150 000 rows per query.
  - `showResumeKey=true`/`resumeKey=`; `showDupeCount`; `showSkipCount=true` + `lastSkipTimestamp=true` (experimental).
  - Pagination API `page=`, `showNumPages=true`, `pageSize=`.
  - The index is "usually sorted by url and date". The README is labelled BETA and dates from 2013, so the live behaviour is to be verified.
- **Rate limits:** none documented [doc]. Third parties report about 15 requests/min per IP before 429/503 [search-summary]. Our default is 1 request per 5 s with long backoff.
- **Save Page Now:** about 12 concurrent capture sessions per user according to third-party sources [search-summary]; optional and opt-in only.
- **Planned use:** earliest and latest capture per project and service URL (`first_archived` events, `date_basis = archive_upper_bound`); the catalogue reconstructed at 31 Dec 2019–2025 and on 2022-02-23; fallback for blocked or vanished pages (`/web/<timestamp>id_/<url>`).
- **Phase 0b checklist:**
  - Coverage per prefix (`thedigital.gov.ua/projects/`, `thedigital.gov.ua/news/`, `diia.gov.ua/services/`, `kmu.gov.ua/news/`): number of unique URLs and earliest year.
  - Do the skip counters work on the live server?
  - Observed throttling.
  - Fixtures: 3 CDX responses, 2 `id_` captures from different years.

## S6 — Legal acts (zakon.rada.gov.ua)

- **URL patterns:** `https://zakon.rada.gov.ua/laws/show/<id>`, `https://zakon.rada.gov.ua/go/<id>`, `/rada/show/<id>`, `/laws/main/<id>` [search].
- **Acts identified so far** (titles from search; content not retrieved):
  - `https://zakon.rada.gov.ua/go/856-2019-%D0%BF`: "Питання Міністерства цифрової трансформації", resolution of 18.09.2019 № 856 [search]
  - `https://zakon.rada.gov.ua/go/386-2025-%D0%BF`: amendments to the ministry's regulation (adds AI and semiconductor development) [search]
  - `https://zakon.rada.gov.ua/laws/show/314-2025-%D0%BF`: on the central executive body for gambling and lotteries (PlayCity) [search]
  - `https://zakon.rada.gov.ua/laws/show/214-2026-%D0%BF`: changes the minister's title in a working group [search]
- **Open data:** data.rada.gov.ua with CSV/JSON/XML and free reuse with attribution, per a third-party page only [search-summary].
- **Planned use:** only acts linked from collected pages; doc_type `legal_act`; proposals for `legal_basis_adopted`/`governance_change`.
- **Phase 0b checklist:** robots.txt; bot protection; text and edition-history pages; open-data endpoints and licence. Fixtures: 2 acts (one with several editions).

## S7a — Telegram channel (optional)

- **URLs:** `https://t.me/mintsyfra` ("Telegram: View @mintsyfra"), web preview `https://t.me/s/mintsyfra` ("Мінцифра") [search]. The preview paginates with `?before=<id>` (seen on another government channel) [search].
- **Known limits:** Ukrainian government Telegram channels were targeted by an attack and later restored [search], so gaps in the post history are possible [hypothesis].
- **Phase 0b checklist:** robots.txt for t.me; depth of `?before=` paging; machine-readable timestamps per post; fixtures for 2 preview pages.

## S7b — data.gov.ua (CKAN, optional)

- **URLs:** organisation `https://data.gov.ua/organization/mincyfry` (+ `/organization/about/mincyfry`) [search]; datasets at `/dataset/<uuid>` [search], e.g. the national register of electronic information resources `https://data.gov.ua/dataset/96612ea3-53b5-45db-be0b-377cac72704d` [search].
- **API:** CKAN-style search parameters seen [search]; `https://data.gov.ua/api/3/action/` per a third-party catalogue [search-summary].
- **Known limits:** access was temporarily restricted "to protect state interests" and later restored [search-summary].
- **Phase 0b checklist:** `organization_show` and `package_search` for `mincyfry`; licence fields; is the Diia guide dataset (C-2) there?

## S8 — Manual additions

- Upload (PDF/DOCX/HTML/TXT) or URL; provenance `manual:<name>`.
- Known candidate: the KIIS/UNDP report "Public opinion on state electronic services in Ukraine in 2025", page `https://www.undp.org/node/565986` [search]; press release `https://www.undp.org/ukraine/press-releases/59-ukrainians-use-government-e-services-undp-backed-study-finds` [search]. The URL in the paper's reference list [paper] did not appear in search results; check that it resolves.

---

## 3. Leads for the paper (project list and responsibilities)

Context and interpretation: `PLAN.md` §13. All entries are **leads to verify**; none is in the data.

**PlayCity**
- Interfax-Ukraine "Кабмін вивів PlayCity із сфери координації Мінцифри": `https://interfax.com.ua/news/telecom/1168056.html`; English: `https://en.interfax.com.ua/news/telecom/1168081.html` [search]
- Forbes Ukraine 15.05.2026: `https://forbes.ua/news/kabmin-perepidporyadkuvav-pleysiti-sobi-regulyator-azartnikh-igor-vikhodit-z-pid-mintsifri-15052026-38857` [search]
- Ukranews: `https://ukranews.com/en/news/1152160-svyrydenko-to-coordinate-playcity-activities-instead-of-the-ministry-of-digital-transformation` [search]
- PDF on kmu.gov.ua ("ЗАТВЕРДЖЕНО постановою Кабінету Міністрів України"): `https://www.kmu.gov.ua/storage/app/uploads/public/6aa/d0b/cb2/6aad0bcb2c6b9821451515.pdf` [search]; trade press: `https://sigma.world/news/ukraines-playcity-moves-under-direct-pm-oversight/` [search]
- Creation (2025): `https://www.kmu.gov.ua/npas/pro-tsentralnyi-orhan-vykonavchoi-vlady-shcho-realizuie-derzhavnu-polityku-u-sferi-orhanizatsii-ta-t210325`, `https://www.kmu.gov.ua/news/pleisiti-stane-novym-rehuliatorom-azartnykh-ihor-uriad-ukhvalyv-postanovu` [search]
- Budget programme passport 2026 (title: approved by order of the ministry): `https://playcity.gov.ua/static-objects/playcity/sites/1/content/hromadianam/biudzhet-ta-zakupivli/pasport-2026/pasport-biudzetnoyi-programi-2026-2902020-2026-07-31.pdf` [search]
- Forbes Ukraine interview with minister Oksana Ferchuk, 11.08.2026: `https://forbes.ua/innovations/ya-dlya-nikh-ne-kit-u-mishku-ochilnitsya-mintsifri-oksana-ferchuk-pro-zlagodzhennya-z-komandoyu-strategiyu-ministerstva-ta-zagrozu-telegram-intervyu-11082026-41111` [search]
- Interfax items citing that interview (on Brave1): `https://interfax.com.ua/news/general/1192435.html`, `https://en.interfax.com.ua/news/telecom/1192463.html`; Forbes news item: `https://forbes.ua/news/oboronniy-klaster-brave1-zalishaetsya-pid-upravlinnyam-mintsifri-oksana-ferchuk-11082026-41119` [search]

**Leadership of the ministry**
- `https://thedigital.gov.ua/news/progress/zberihayemo-temp-oleksandr-borniakov-ocholyv-mintsyfry` [search]
- `https://interfax.com.ua/news/telecom/1185588.html` (appointment of Oksana Ferchuk) [search]
- `https://forbes.ua/innovations/lyudina-ne-z-komandi-fedorova-oksana-ferchuk-nova-ministerka-tsifrovoi-transformatsii-shcho-pro-nei-vidomo-i-yak-na-priznachennya-reaguyut-u-mintsifri-17072026-40490` [search]
- `https://interfax.com.ua/news/general/1185566.html` (new composition of the government) [search]
- `https://dou.ua/lenta/articles/ferchuk-100-days-in-mintsyfry/` [search]

**Role of the ministry per project**
- UNITED24 ("at the initiative of the President"): `https://www.kmu.gov.ua/news/z-iniciativi-prezidenta-ukrayini-volodimira-zelenskogo-zapushcheno-globalnu-iniciativu-dlya-dopomogi-ukrayini-united24` [search]
- Ukrainian Startup Fund / Innovation Development Fund: `https://www.kmu.gov.ua/news/fond-rozvytku-innovatsii-perekhodyt-v-upravlinnia-mintsyfry-rishennia-uriadu` [search]
- CodeUA: `https://www.kmu.gov.ua/news/mintsyfry-zapuskaiemo-codeua-natsionalnyi-marketpleis-dlia-ukrainskykh-it-kompanii`, `https://mezha.ua/2024/11/13/marketpleys-tekhnokompaniy-codeua/` [search]
- UNITED24 Media: `https://imi.org.ua/en/news/ministry-of-digital-transformation-announces-the-creation-of-an-english-language-media-about-ukraine-i46862` [search]
- Brave1: `https://armyinform.com.ua/2023/04/26/v-ukrayini-zapustyly-klaster-z-rozvytku-oboronnyh-tehnologij-brave1/`; report on a move to the Ministry of Defence: `https://dou.ua/goto/6l69` [search]
- Digital State UA: `https://www.kmu.gov.ua/news/platforma-tsyfrovoi-ukrainy-mintsyfry-zapuskaie-digital-state-ua`, `https://dou.ua/lenta/news/launch-digital-state-ua/`, pre-announcement `https://dev.ua/news/v-ukraini-nezabarom-zapratsiuie-platforma-digital-state-ua-iaka-obiednaie-vsi-tsyfrovi-proiekty-krainy-1732030256` [search]

**European Integration**
- `https://thedigital.gov.ua/projects/yevrointegraciya` (index variant) and `https://thedigital.gov.ua/projects/progress` [search]
- Related: `https://thedigital.gov.ua/news/technologies/tsifrova-integratsiya-z-es-yak-mintsifra-ta-proekt-dt4ua-zminili-derzhposlugi-v-ukraini`, `https://thedigital.gov.ua/news/progress/iak-yes-dopomahaye-ukrayini-buduvaty-tsyfrovu-derzavu-pidsumky-eu4digitalua` [search]

**Further initiatives to screen**
- `https://www.kmu.gov.ua/news/mincifri-zapustit-nacionalnu-veb-platformu-centriv-nadannya-administrativnih-poslug` [search]
- `https://thedigital.gov.ua/news/technologies/mintsifra-doluchilas-do-proektu-radi-evropi-z-protidii-nasilstvu-shchodo-ditey-v-ukraini` [search]
- From media reports only: `https://news.dtkt.ua/state/other/67255-mincifri-zapuskaje-nacplatformu-e-demokratiyi-vzajemodiiu`, `https://thepage.ua/ua/news/mincifra-zapustila-derzhavnu-platformu-zi-shtuchnogo-intelektu-v-ukrayini-detali`, `https://dou.ua/lenta/news/platform-for-public-registries/` [search]

**Access from abroad (risk R2)**
- State Tax Service blocks foreign access: `https://7eminar.ua/news/4261-yak-rozblokuvati-dostup-do-servisiv-dps-z-za-mez-ukrayini` [search]
- data.gov.ua restored after a restriction: `https://news.dtkt.ua/accounting/automation/77755-portal-vidkritix-danix-vidnoviv-svoiu-robotu` [search]

---

## 4. Hosts

These hosts need to be reachable for Phase 0b (in this development environment) and for the collectors (on the server):

- **Ministry:** `thedigital.gov.ua`, `storage.thedigital.gov.ua`, `2years.thedigital.gov.ua`, `5years.thedigital.gov.ua`, `2025.thedigital.gov.ua`, `ai.thedigital.gov.ua`
- **Diia:** `diia.gov.ua`, `guide.diia.gov.ua`, `plan2.diia.gov.ua`, `center.diia.gov.ua`, `osvita.diia.gov.ua`, `e-pidpryemets.diia.gov.ua`, `se.diia.gov.ua`
- **Government and law:** `www.kmu.gov.ua` (and `kmu.gov.ua`), `zakon.rada.gov.ua`, `data.rada.gov.ua`, `data.gov.ua`
- **Archive and social:** `web.archive.org`, `archive.org`, `t.me`
- **Project domains:** `winwin.gov.ua`, `usf.com.ua`, `u24.gov.ua`, `united24media.com`, `codeua.com`, `digitalstate.gov.ua`, `playcity.gov.ua` (plus domains still to be resolved through the ministry pages: Brave1, Mriia, CDTO Campus, Diia.Engine, Diia.Digital Community, uResidency, Virtual Assets)
- **Verification of paper leads:** `interfax.com.ua`, `en.interfax.com.ua`, `forbes.ua`, `www.undp.org`, `kiis.com.ua`
