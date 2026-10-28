# Codebook (draft)

> **Status:** Phase 0 draft, 2026-10-28, for team review.
> **Generation:** from Phase 1 on, this file is generated from the vocabulary tables (`codebook/*.yaml` → database → `docs/CODEBOOK.md`), and every release contains a frozen copy.
> **Codes** are stable identifiers. Labels and definitions may change; a code is never renamed or deleted, only deactivated (`active = false`) and, where applicable, linked to its replacement (`replaced_by`). Every change creates a revision.
> **Examples** come only from the paper's own assignments or, later, from collected and verified data. None comes from model knowledge.
> **Labels:** [paper] from paper.docx · [user] from the assignment · [search] seen in search results · ⚑ needs a team decision (see `PLAN.md` §12).

## 1. Parameters

| Parameter | Value | Source |
|---|---|---|
| `MINISTRY_FOUNDED` | 2019-08-29 | [paper], [user] |
| `FULL_SCALE_INVASION` | 2022-02-24 | [paper], [user] |
| Time zone for publication dates | Europe/Kyiv | [user] |
| Storage time zone for timestamps | UTC | [user] |

## 2. Coding rules

### 2.1 Unit of analysis

- **Project:** everything that sources identify as a project of the ministry is captured. The primary source is the project list on thedigital.gov.ua [user].
- **Scope is a separate decision:** whether a project enters the analysis is recorded in `in_paper_scope` with a mandatory `scope_note` ⚑ D-1.
- **`unit_type`** distinguishes digital products from platforms, programmes, strategies or policy areas and organisations ⚑ D-11. Coding is based on how the sources describe the entry, not on the coder's background knowledge.

### 2.2 Service granularity ⚑ D-6

- **Service:** a distinct offering for a defined user group with its own entry point (a page, an app section, a procedure or an application) and a recognisable result (a document, a decision, a payment, a registration, access, a course, …).
- **Sub-service:** a variant or part of a service that sources present separately, such as a separate application type or a separate result. It is linked through `parent_service_id`.
- **Not a service:** navigation pages, purely informational pages and UI features without their own result. These go into `notes` of the parent service.
- **One service, several channels:** if the same service is offered through several channels (app, portal, physical centre), it is one service with several `channels`. If sources present the channels as separate offerings with different results, it becomes separate (sub-)services.

### 2.3 Classification fields and evidence

- `policy_domains`, `beneficiaries`, `wartime_relevance`, `development_mode`, the primary objectives and D1–D4 are coded **from sources**. A field can only be marked `verified` if at least one Evidence record (document + verbatim quote) supports it.
- Without evidence the field stays `unverified`, and the rationale field explains the coder's reasoning.
- Multi-valued fields (`policy_domains`, `beneficiaries`, `channels`) list all values that the sources support, with the main one first.

### 2.4 Wartime relevance (`wartime_relevance`) ⚑ D-4

Code the **stated purpose and target group** according to the sources, relative to needs caused or substantially intensified by the full-scale war (from 2022-02-24).

| Code | Label | Definition | Rule |
|---|---|---|---|
| `direct` | Direct | The primary objective, according to the sources, addresses a need caused or substantially intensified by the war (e.g. defence, war damage, displacement, wartime fundraising, services for affected groups). | Requires evidence naming the war-related need. |
| `indirect` | Indirect | The primary objective is not war-specific, but sources explicitly link the initiative to wartime needs (e.g. continuity of services, economic resilience, recovery). | Requires evidence of the explicit link. |
| `none` | None | The sources state no relation to the war, and none is evident from the stated purpose. | Absence must be checked in at least the project page and one further source. |
| `unclear` | Unclear | After review, the evidence is insufficient or contradictory. | A field that has not been coded yet stays **empty**; `unclear` is a coding decision, not a default. |

### 2.5 Development mode (`development_mode`), after Yoo et al. (2012) [paper]

| Code | Label | Definition |
|---|---|---|
| `new_development` | New development | The sources present the initiative as newly developed, without a predecessor among the ministry's services or platforms. |
| `adaptation_of_existing` | Adaptation of existing | The sources present the initiative as a change, extension or re-purposing of an existing service, platform or organisation. Requires a Relation (`extends`, `builds_on`, `successor_of`) or a rationale explaining why none can be recorded. |
| `unclear` | Unclear | Not determinable from the sources after review. Not-yet-coded fields stay empty. |

The coded mode complements the derived `war_trajectory` (§2.7), which only looks at dates. Combining existing components into something new is recorded separately through `recombines` relations (D4).

### 2.6 Dates

- Store what the source says, with **precision** (`day`, `month`, `quarter`, `year`) and **basis** (`stated_in_source`, `inferred`, `archive_upper_bound`); keep the verbatim date text.
- **Never guess.** A date without a year stays without a year until a reliable source supplies it. Inference rules must be documented and are marked `inferred`.
- **The date of an announcement is not automatically the date of the event.** If only the announcement date is known, code `inferred` and quote the announcement.
- **Archive captures** (Wayback Machine) only show that something existed *by* that date (`first_archived`, `archive_upper_bound`). They are never a start date.

### 2.7 Derived fields (read-only, marked `derived_` in exports)

Cut-off dates as in §1. Events marked `disputed` are ignored.

| Field | Definition |
|---|---|
| `launch` | Earliest `launch` event; if there is none, the earliest `beta_launch`. Keeps the interval, precision, basis and event. |
| `existed_by` | Earliest `first_archived` event. An upper bound, displayed as "≤ date (archive)". |
| `period` | From the launch interval [start, end]: end < `MINISTRY_FOUNDED` → `pre_ministry`; start ≥ `MINISTRY_FOUNDED` and end < `FULL_SCALE_INVASION` → `pre_invasion`; start ≥ `FULL_SCALE_INVASION` → `full_scale_war`; otherwise `unknown`. Without a launch: `existed_by` < `MINISTRY_FOUNDED` → `pre_ministry`, otherwise `unknown`. ⚑ D-3 |
| `period_reason` | `no_date`, `imprecise_date` (the interval straddles a cut-off), `archive_bound_only` |
| `existed_before_invasion` | true if the launch ends before `FULL_SCALE_INVASION` **or** `existed_by` < `FULL_SCALE_INVASION` |
| `war_trajectory` | `new_in_war` (launch start ≥ invasion) · `adapted_in_war` (existed before the invasion and at least one modification event starting ≥ invasion) · `prewar_unchanged` (existed before the invasion and every modification event ends before it, or there is none: "no modification recorded up to release X") · `unknown` |
| `trajectory_reason` | `no_date`, `imprecise_date`, `imprecise_modification_date` |
| `portfolio_entry` | Earliest start of a Participation of the focal organisation (the ministry) as `initiator`, `owner` or `operator` ⚑ D-10 |

### 2.8 Screening of documents

- `screening_status`: `unscreened` → `included` / `excluded`, with an exclusion reason (vocabulary `exclusion_reason`) and an optional note.
- Only `included` documents go into the QDA export.
- Counts per status and reason are reported (PRISMA-style flow).

### 2.9 Automatic suggestions (never facts)

- **Project tags** come from curated aliases (including inflected forms and exclusions) and are always `suggested` until a person confirms them.
- **Event proposals** come from phrases near a project or service mention (list in §4) and are always proposals.

---

## 3. Vocabularies

### `paper_cluster` (single-valued)

Cluster names and assignments as in the paper [paper]; the definitions are drafts.

| Code | Label | Draft definition | Projects assigned in the paper |
|---|---|---|---|
| `digital_public_services_infrastructure` | Digital public services & infrastructure | Primary purpose: delivering public services digitally, or the infrastructure these services run on. | Diia, Diia.Engine, Diia.Center |
| `business_economic_development` | Business & economic development | Primary purpose: supporting businesses, entrepreneurship, investment or the IT sector. | Diia.City, Diia.Business, uResidency, CodeUA |
| `education_digital_capabilities` | Education & digital capabilities | Primary purpose: digital skills, education or capabilities of citizens and public servants. | Diia.Education, Mriia, CDTO Campus |
| `defense_technology_innovation` | Defense technology & innovation | Primary purpose: developing, funding or scaling (defence) technology and innovation. | Brave1, WINWIN, Ukrainian Startup Fund |
| `fundraising_international_communication` | Fundraising & international communication | Primary purpose: raising funds or communicating with international audiences. | UNITED24, UNITED24 Media |
| `digital_regulation` | Digital regulation | Primary purpose: regulating, licensing or supervising digital markets. | PlayCity, Virtual Assets |
| `broader_digital_transformation` | Broader digital transformation | Primary purpose: supporting digital transformation across government or society, beyond single services. | Diia.Digital Community, Digital State UA |

European Integration is not assigned in the paper [user]; its cluster is left empty until D-1 is decided.

### `ministry_category` (multi-valued, as observed on thedigital.gov.ua)

| Code (URL segment) | Label (uk) | Status |
|---|---|---|
| `technologies` | to be captured by C1 | observed in seed URLs [user] |
| `business` | to be captured by C1 | observed [user] |
| `regions` | to be captured by C1 | observed [user] |
| `education` | to be captured by C1 | observed [user] |
| `progress` | "Досягнення" (page title [search], to be confirmed) | observed [user] |

### `unit_type` ⚑ D-11

| Code | Label | Definition |
|---|---|---|
| `digital_product` | Digital product or service | Used directly by end users (app, portal, e-service, website with its own function). |
| `platform` | Platform or infrastructure | Mainly used by other services or organisations to build or deliver their offerings. |
| `programme` | Programme | A support, funding, education or regulatory programme with defined participants or recipients. |
| `strategy_policy_area` | Strategy or policy area | A strategy, policy workstream or umbrella brand without one specific product. |
| `organisation` | Organisation | A separate legal entity or agency (e.g. a fund, an agency, an editorial office). |
| `other` | Other | Explain in `notes`. |

### `policy_domain` (multi-valued) ⚑ D-7

**Proposal:** use the divisions of the UN Classification of the Functions of Government (**COFOG**) as the top level, because it is a citable international standard and makes the results comparable. Subcodes are proposed from the collected data in Phase 2/3; the team finalises them. *The labels below still have to be checked against the official COFOG publication before adoption.*

| Code | Label (COFOG division) |
|---|---|
| `general_public_services` | 01 General public services |
| `defence` | 02 Defence |
| `public_order_safety` | 03 Public order and safety |
| `economic_affairs` | 04 Economic affairs |
| `environmental_protection` | 05 Environmental protection |
| `housing_community` | 06 Housing and community amenities |
| `health` | 07 Health |
| `recreation_culture_religion` | 08 Recreation, culture and religion |
| `education` | 09 Education |
| `social_protection` | 10 Social protection |

### `beneficiary` (multi-valued) ⚑ D-7

**Grounded in the paper** [paper]:

| Code | Label | Basis in the paper |
|---|---|---|
| `citizens` | Citizens / general population | D1 question; KIIS figures |
| `businesses` | Businesses | D1 question; business cluster |
| `public_institutions` | Public institutions | D1 question ("institutions") |
| `veterans` | Veterans | KIIS figures |
| `idps` | Internally displaced persons | KIIS figures |
| `startups` | Startups | Brave1 description; "startups and innovation" |
| `foreign_investors` | Foreign investors | "foreign investments" |
| `international_partners` | International partners | Brave1 description |

**Candidates**, to be confirmed or rejected with data: `military_personnel`, `military_families`, `residents_frontline_occupied`, `ukrainians_abroad`, `children_youth`, `students_learners`, `educators`, `civil_servants`, `local_governments`, `it_companies`, `defense_tech_developers`, `donors`, `international_audiences`.

### `wartime_relevance`: see §2.4 (`direct`, `indirect`, `none`, `unclear`)

### `development_mode`: see §2.5 (`new_development`, `adaptation_of_existing`, `unclear`)

### `service_kind`

| Code | Label | Definition |
|---|---|---|
| `e_service` | E-service | An administrative procedure that can be completed online (application, registration, notification, payment). |
| `e_document` | E-document | A digital document or certificate that can be shown or shared. |
| `physical_service` | Physical service | Provided in person (e.g. at a service centre). |
| `program_grant` | Programme or grant | Financial or in-kind support with eligibility criteria. |
| `platform_feature` | Platform feature | A function of a platform without its own administrative result (e.g. notifications, sharing, signing). |
| `registry_regulation` | Registry or regulation | A register, licence or regulatory procedure. |
| `fundraising_campaign` | Fundraising campaign | A fundraising direction or campaign. |
| `course_training` | Course or training | An educational offering. |
| `media` | Media | Editorial content, an outlet or a series. |
| `other` | Other | Explain in `notes`. |

### `channel` (multi-valued)

| Code | Definition |
|---|---|
| `app` | Mobile application |
| `portal` | The central government services portal |
| `web` | Other website or web application |
| `physical` | In person (office, centre) |
| `chatbot` | Messenger bot or chat assistant |
| `api` | Machine interface for other systems |

### `status`

| Code | Definition |
|---|---|
| `active` | Available or operating according to the most recent source. |
| `planned` | Announced or in preparation, not yet available. |
| `pilot` | Test, beta or pilot operation. |
| `suspended` | Temporarily unavailable or halted. |
| `discontinued` | Ended or permanently unavailable. |
| `unknown` | No current evidence. |

### `event_type`

`counts_as_modification` decides what counts as a modification for `adapted_in_war` ⚑ D-2.

| Code | Definition | Counts as modification |
|---|---|---|
| `announced` | Publicly announced, not yet available. | no |
| `legal_basis_adopted` | A legal act establishing or changing the basis was adopted. | no |
| `beta_launch` | Available as beta, test or pilot. | no |
| `launch` | Available to the intended users. | no |
| `expansion` | Extended to new user groups, regions, channels or functions. | **yes** |
| `major_update` | Substantial functional change. | **yes** |
| `rebrand` | Renamed or rebranded. | **yes** |
| `governance_change` | Change of owner, operator, coordinating authority or subordination; also institutional context events of the ministry. | **yes** |
| `suspension` | Temporarily halted or closed. | **yes** |
| `discontinuation` | Permanently ended. | no |
| `first_archived` | Earliest archive capture (upper bound, `archive_upper_bound`). | no |

### `date_precision`

`day`, `month`, `quarter`, `year`.

### `date_basis`

`stated_in_source`, `inferred`, `archive_upper_bound`.

### `doc_type`

| Code | Definition |
|---|---|
| `news` | News item of an organisation |
| `announcement` | Short announcement or post (e.g. Telegram) |
| `project_page` | Page describing a project or service |
| `legal_act` | Law, resolution, order |
| `strategy_policy` | Strategy, concept, policy document, work plan |
| `report` | Annual report, evaluation, study |
| `statistics` | Statistics or dataset |
| `interview_media` | Interview or press article |
| `other` | Other |

### `screening_status` and `exclusion_reason`

`unscreened`, `included`, `excluded`.

| `exclusion_reason` | Definition |
|---|---|
| `not_about_portfolio` | Does not concern a project or service of the portfolio. |
| `insufficient_content` | Too little substantive content (e.g. a teaser). |
| `duplicate` | Duplicate of another document (linked). |
| `outside_period` | Outside the observation window. |
| `not_a_document` | Navigation, list or error page. |
| `inaccessible` | Content not retrievable (also not archived). |
| `other` | Explain in the note. |

### `org_type`

| Code | Definition |
|---|---|
| `ministry` | Ministry |
| `central_executive_body` | Agency, service, inspectorate or other central executive body |
| `government_office` | Cabinet of Ministers, Office of the President and similar bodies |
| `parliament` | Parliament and its bodies |
| `local_government` | Local self-government or regional administration |
| `state_enterprise` | State-owned enterprise |
| `state_fund_institution` | State fund or state institution |
| `international_organisation` | International organisation |
| `foreign_government_agency` | Foreign government or its agency |
| `ngo_civil_society` | NGO, association, cluster |
| `company` | Private company |
| `startup` | Startup |
| `academic_institution` | University, research institute |
| `media_outlet` | Media organisation |
| `other` | Other |

### `participation_role`

| Code | Definition |
|---|---|
| `initiator` | Initiated the project or service. |
| `owner` | Holds formal responsibility or ownership. |
| `developer` | Builds or develops it technically. |
| `funder` | Provides funding. |
| `partner` | Cooperates without one of the other roles. |
| `operator` | Runs it day to day. |
| `regulator` | Sets rules or policy for it, or supervises it. |
| `coordinator` | ➕ Draft addition: coordinates the activities of a body (e.g. coordination of an agency through a minister); suggested by the PlayCity leads [search]. |

### `relation_type` (read as "from — type — to")

| Code | Definition |
|---|---|
| `builds_on` | Technically uses or depends on the target (e.g. a service built on a platform). |
| `extends` | Adds functions, groups or channels to the target. |
| `recombines` | Combines the target with other components into a new offering (one relation per combined component). |
| `part_of` | Is a component or sub-unit of the target. |
| `successor_of` | Replaces the target. |
| `related_to` | Other documented relation (explain in `note`). |

### `component_type` (draft)

`data_exchange`, `identification_trust` (identification, signatures), `registry`, `payment`, `cloud_hosting`, `communication` (notifications, messaging), `other`.

### `verification_status`

| Code | Definition |
|---|---|
| `unverified` | Not yet checked by a person (default for collected values). |
| `verified` | Checked by a person against evidence. |
| `disputed` | Contradicting evidence or disagreement; explanation in a comment. |

### Provenance kinds (`field_meta.src`)

`seed` (from the assignment's seed table), `collector:<name>@<run>`, `manual:<name>`, `import:<file>`. A restore keeps the original source and records the restoring person in `by`.

### `language`

`uk` (Ukrainian), `en` (English), `ru` (Russian), `other` (explain in `notes`). ISO 639-1 codes.

### `period` (derived values, §2.7)

| Code | Label | Definition |
|---|---|---|
| `pre_ministry` | Before the ministry | Launch ends before `MINISTRY_FOUNDED`, or the archive bound lies before it. |
| `pre_invasion` | Ministry, before the full-scale invasion | Launch lies within `MINISTRY_FOUNDED` … `FULL_SCALE_INVASION` − 1 day. |
| `full_scale_war` | Full-scale war | Launch starts on or after `FULL_SCALE_INVASION`. |
| `unknown` | Unknown | No launch date, an imprecise date that straddles a cut-off, or only an archive bound after `MINISTRY_FOUNDED`; the reason is given in `period_reason`. |

### `war_trajectory` (derived values, §2.7)

| Code | Label | Definition |
|---|---|---|
| `new_in_war` | New in war | Launched on or after `FULL_SCALE_INVASION`. |
| `adapted_in_war` | Adapted in war | Existed before the invasion; at least one modification event on or after it. |
| `prewar_unchanged` | Pre-war, no recorded change | Existed before the invasion; no modification recorded on or after it (up to the release date). |
| `unknown` | Unknown | Not determinable; the reason is given in `trajectory_reason`. |

### `derived_reason` (reason codes of derived values)

| Code | Definition |
|---|---|
| `no_date` | No dated launch, beta-launch or archive event. |
| `imprecise_date` | The launch date's precision straddles a cut-off date. |
| `archive_bound_only` | Only an archive upper bound is known, which does not determine the period. |
| `imprecise_modification_date` | A modification event is undated or straddles `FULL_SCALE_INVASION`. |

### `license` (draft)

`cc_by_4_0`, `other_open` (link to the license), `all_rights_reserved`, `unknown`.

---

## 4. Phrase list for event proposals (draft)

Matched on normalised text (apostrophes unified to `ʼ`) near a project or service mention. Matches only ever produce proposals, which a person edits and accepts or rejects.

| Suggested `event_type` | Ukrainian stems / phrases | English |
|---|---|---|
| `launch` | `запуст-` (запустили, запустило, запущено), `запрацю-` (запрацювала, запрацював), `зʼявил-` (зʼявилася послуга), `старту-` (стартувала) | launched, now available, went live |
| `beta_launch` | `тестов-` + `режим`, `пілот-`, `бета` | beta, pilot, test mode |
| `announced` | `анонсу-`, `оголоси-`, `презенту-`, `плану-` | announced, presented, plans to |
| `expansion` | `розшир-`, `масштабу-`, `доступн- для` | expanded, scaled, now also available for |
| `major_update` | `оновил-`, `оновлен-`, `нова версія` | updated, new version |
| `rebrand` | `перейменува-`, `ребрендинг` | renamed, rebranded |
| `governance_change` | `перепідпорядкува-`, `передано в управління`, `переходить в управління`, `координац-` | transferred, now coordinated by |
| `suspension` | `призупин-`, `тимчасово недоступ-` | suspended, temporarily unavailable |
| `discontinuation` | `припин-`, `закри-` | discontinued, closed |
| `legal_basis_adopted` | `ухвалив постанову`, `затвердив`, `постанова №` | resolution adopted, approved |

The precision of each pattern (share of accepted proposals) is reported in the collector-run statistics, so the list can be improved on the basis of evidence.
