# Codebook (draft)

> **Status:** Phase 0 draft, 2026-10-28, for team review. Phase 3 (2026-10-31, revised the same day after review) adds the coding of evidence in documents (§2.10), the vocabularies `dimension` and `analysis_code` and the portfolio roles of `participation_role` (§3), date bases for participations and indicators and the verbatim value of indicators (§2.6), and the alternative period basis `entry_period` (§2.7); the data rules are in `docs/DATA_MODEL.md` §19–§22. Exports include this file verbatim as the coding rules (`docs/API.md` §8.8.2).
> **Generation:** the vocabulary files `codebook/*.yaml` were derived from this draft (`codebook/README.md`); `mdt seed` loads them into the database, which holds the working copy (Codebook page of the app). From the first release on (Phase 4), this file and `codebook/` are regenerated from the database (`codebook/*.yaml` → database → `docs/CODEBOOK.md`), and every release contains a frozen copy.
> **Codes** are stable identifiers. Labels and definitions may change; a code is never renamed or deleted, only deactivated (`active = false`) and, where applicable, linked to its replacement (`replaced_by`). Every change creates a revision.
> **Examples** come only from the paper's own assignments or, later, from collected and verified data. None comes from model knowledge.
> **Labels:** [paper] from paper.docx · [user] from the assignment · [search] seen in search results · ⚑ needs a team decision (see `PLAN.md` §12).

## 1. Parameters

| Parameter | Value | Source |
|---|---|---|
| `MINISTRY_FOUNDED` | 2019-08-29 | [paper], [user] |
| `FULL_SCALE_INVASION` | 2022-02-24 | [user] (the paper gives the month, February 2022) |
| Time zone for publication dates | Europe/Kyiv | [user] |
| Storage time zone for timestamps | UTC | [user] |

## 2. Coding rules

### 2.1 Unit of analysis

- **Project:** everything that sources identify as a project of the ministry is captured. The primary source is the project list on thedigital.gov.ua [user].
- **Scope is a separate decision:** whether a project enters the analysis is recorded in `in_paper_scope`. Every time it is set or changed, a non-empty `scope_note` with the reason must be given in the same change (the app enforces this) ⚑ D-1.
- **`unit_type`** distinguishes digital products from platforms, programmes, strategies or policy areas and organisations ⚑ D-11. Coding is based on how the sources describe the entry, not on the coder's background knowledge.

### 2.2 Service granularity ⚑ D-6

- **Service:** a distinct offering for a defined user group with its own entry point (a page, an app section, a procedure or an application) and a recognisable result (a document, a decision, a payment, a registration, access, a course, …).
- **Sub-service:** a variant or part of a service that sources present separately, such as a separate application type or a separate result. It is linked through `parent_service_id`.
- **Not a service:** navigation pages, purely informational pages and UI features without their own result. These go into `notes` of the parent service.
- **One service, several channels:** if the same service is offered through several channels (app, portal, physical centre), it is one service with several `channels`. If sources present the channels as separate offerings with different results, it becomes separate (sub-)services.

### 2.3 Classification fields and evidence

- `policy_domains`, `beneficiaries`, `wartime_relevance`, `development_mode`, the primary objectives and D1–D4 are coded **from sources**.
- **Field verification** (`docs/DATA_MODEL.md` §6.4):
  - a field can be marked `verified` only with an evidence record that targets that field (document or URL with retrieval time, plus a verbatim quote); the app enforces this (`docs/DATA_MODEL.md` §6.4);
  - `disputed` requires a note;
  - any later change of the value resets it to `unverified`.
  - Without evidence the field stays `unverified`, and the rationale field explains the coder's reasoning.
- **Record-level `verification_status`** is the reviewer's judgement of the whole record, independent of the field statuses. Setting it to `verified` or `disputed` requires a note.
- **Multi-valued fields** (`policy_domains`, `beneficiaries`, `channels`) list all values that the sources support, with the main one first. The first value is used for sorting.

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
- **Archive captures** (Wayback Machine) only show that something existed *by* that date. They are recorded only as `first_archived` events with basis `archive_upper_bound` (the app rejects any other combination) and are never a start date.
- A dated event needs a date basis.
- **Participations and indicators** (Phase 3): the start and end of a participation and the reference date (`as_of`) of an indicator also need a basis, `stated_in_source` or `inferred` (never `archive_upper_bound`, which belongs to `first_archived` events only); the verbatim period text of a participation goes into `period_text`. A role that changes is a new participation; the old one gets an end date.
- **Indicator values** (Phase 3): `value` is the number as the source states it; a qualifier ("more than", "about", "up to") is never dropped but kept, verbatim together with the number, in `value_text`.

### 2.7 Derived fields (read-only, marked `derived_` in exports)

Cut-off dates as in §1. Disputed events and participations are ignored. An interval *straddles* a cut-off date if it starts before the date and ends on or after it. The rules below and the definitions of `period`, `war_trajectory` and `derived_reason` in §3 use the **launch interval**, not the displayed candidate: launch events dated "2022" and "2022-03" display "2022-03", but their launch interval [2022-01-01, 2022-03-31] straddles `FULL_SCALE_INVASION`. The exact algorithm is in `docs/DATA_MODEL.md` §8; in short:

| Field | Definition |
|---|---|
| `launch` | **Launch interval** = [earliest start, earliest end] over the dated `launch` events (or, if there are none, the dated `beta_launch` events); the earliest launch provably lies in it. **Displayed:** the candidate with the earliest end, with precision, basis and event. |
| `existed_by` | Earliest **end** of the `first_archived` events: an upper bound, displayed as "≤ date (archive)". |
| `period` | From the launch interval [start, end]: end < `MINISTRY_FOUNDED` → `pre_ministry`; start ≥ `MINISTRY_FOUNDED` and end < `FULL_SCALE_INVASION` → `pre_invasion`; start ≥ `FULL_SCALE_INVASION` → `full_scale_war`; otherwise `unknown`. Without a launch: `existed_by` < `MINISTRY_FOUNDED` → `pre_ministry`, otherwise `unknown`. ⚑ D-3 |
| `period_reason` | `no_date`, `imprecise_date` (the launch interval straddles a cut-off date), `archive_bound_only` |
| `existed_before_invasion` | true if the launch interval ends before `FULL_SCALE_INVASION` **or** `existed_by` < `FULL_SCALE_INVASION`. False means only *not shown* (new in war, a date that straddles the invasion, or no date), never "did not exist"; the app labels it "Shown to exist before the invasion". |
| `war_trajectory` | Rules in this order: (1) launch interval start ≥ invasion, but an archive bound shows the item existed before it → `unknown` (`conflicting_dates`); (2) launch interval start ≥ invasion → `new_in_war`; (3) existed before the invasion and a modification event starts on or after it → `adapted_in_war`; (4) existed before the invasion and every modification event ends before it, or there is none → `prewar_unchanged` ("no modification on or after the invasion recorded up to release X"); (5) otherwise `unknown`. The deciding event is linked. |
| `trajectory_reason` | `no_date`, `imprecise_date`, `imprecise_modification_date`, `conflicting_dates`, `archive_bound_only` (the only date is an archive upper bound on or after the invasion) |
| `portfolio_entry` | Earliest start of a Participation of the focal organisation (the ministry) in a **portfolio role** (the `participation_role` terms with `attributes.portfolio_role`: `initiator`, `owner`, `operator`), with the participation linked. A service's entry comes from its own participations, never from its project's ⚑ D-10 |
| `entry_period` | (Phase 3) The period rules of `period` applied to the portfolio-entry interval (the start interval of that participation), without an archive fallback: the alternative basis of D-10 (launch of the initiative vs. entry into the ministry's portfolio). `entry_period_reason`: `no_date` (no such participation with a start) or `imprecise_date` (the interval straddles a cut-off date). There is no trajectory on this basis. ⚑ D-10 |
| `period` of events, documents and participations | (Phase 3) The period of an event's date, a document's publication date or a participation's start by the same interval rule (an archive bound counts as an interval ending on its date); undated or straddling → `unknown`. Evidence gets `document_period` (the cited document's period) and `case_period` (the derived `period`, on the launch basis, of the project or service it concerns). Used to count and compare by period; it does not feed the derived values above. |

A project's derived values use the project's own events only, not those of its services (proposed default ⚑ D-16): a project whose services were launched or changed in war can still read `prewar_unchanged`; the project fields `services_new_in_war` and `services_adapted_in_war` show that activity, and the dashboard lists such projects as a check.

### 2.8 Screening of documents

- `screening_status`: `unscreened` → `included` / `excluded`, with an exclusion reason (vocabulary `exclusion_reason`) and an optional note. The app requires the reason for `excluded` and allows it only there (`docs/DATA_MODEL.md` §7).
- Only `included` documents go into the QDA export.
- Counts per status and reason are reported (PRISMA-style flow); the dashboard shows them, also per source and per period, with the included documents that are coded (`docs/UI.md` §9.5).
- After screening, the included documents without a dimension citation form the coding queue (§2.10).
- Screening happens in the document view (`docs/UI.md` §9.2): read the text, include or exclude it with a reason, confirm or reject the suggested project links, and decide the event proposals the text raised. A document is screened against the unit of analysis (§2.1) and the observation window, not against how useful it looks for a field.

### 2.9 Automatic suggestions (never facts)

- **Project tags** come from curated aliases (including inflected forms and exclusions) and are always `suggested` until a person confirms them.
- **Event proposals** come from phrases near a project or service mention (list in §4) and are always proposals.

### 2.10 Coding evidence in documents (Phase 3)

The qualitative document analysis codes passages of the collected documents along the paper's analytical framework (Table 1) [paper]. In the app, a coded passage is an **evidence row anchored in the document's text** (`docs/DATA_MODEL.md` §20).

- **A passage, not a paraphrase:** select the passage in the document view; the app stores it verbatim with its character offsets in that text version. Keep it short (at most 1 000 characters; one or a few sentences) and self-contained enough to be cited. A passage may be cited several times (for different records or targets).
- **What a passage supports** (its target):
  - **Record** (`entity`): the passage documents the record as a whole, e.g. the source of an event, a participation, a relation or an indicator.
  - **Field** (`field:<name>`): the passage supports the coded value of one field (e.g. `wartime_relevance`, `development_mode`, `d1_need`, a document's `published`). Set or correct the value in the capture panel while citing, so the evidence records the value it was captured for. Only such evidence can mark a field `verified` (§2.3).
  - **Dimension** (`dimension:D1` … `D4`): the passage is a coded segment for a dimension of Table 1 (vocabulary `dimension`): it answers the dimension's analytical question for the record. Dimension evidence is the material of the thematic analysis; the free-text fields `d1_*` to `d4_*` summarise it per record.
- **Analysis codes** (vocabulary `analysis_code`, optional) refine a dimension citation. The paper and this draft define no codes below the four dimensions, so the vocabulary starts **empty**. The team adds a code on the Codebook page, or with **New code…** in the capture panel, when a theme recurs in the material (inductive coding), with a definition, include and exclude notes, and the dimension it belongs to (`attributes.dimension`, one of `d1`…`d4`); examples come only from coded passages. Codes are never taken from general knowledge. A code that turns out to be wrong is deactivated and, where it applies, replaced by another (see the header of this codebook), never renamed; a code in use keeps its dimension.
- **Subjects:** cite the passage for the record it is about: a project or service (or its organisation, component, event, participation, relation or indicator), or the document itself (e.g. for its publication date). If the record does not exist yet, create it from the passage (an event, participation, relation, indicator, component or organisation), so it is born with its evidence. The project or service a citation concerns is its **case**, by which codings are compared across the periods (`docs/DATA_MODEL.md` §20.5). Citing for a case that the document does not link as confirmed (a link the tagger only suggested, or none) requires confirming or adding the link first, so codings and document links agree.
- **Coded documents:** a document counts as coded once one of its passages is cited for a dimension; citations for a record or a field (e.g. an event's source, the document's own date) do not code it. The included documents without a dimension citation are the coding queue (§2.8).
- **Text changes:** a citation stays bound to the text version it quotes. When a page changes and the passage still makes its point in the new text, cite it there anew.
- **Without a passage:** a document without extractable text, or a source that is not a collected document, is cited as a whole document or by URL with retrieval time and a quote typed verbatim from the source. On a document with text, a typed quote must occur in it exactly once (the app then stores it as that passage); otherwise select the passage.

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
| `other` | Explain in `screening_note`. |

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

**Portfolio roles** (Phase 3): `initiator`, `owner` and `operator` carry `attributes.portfolio_role: true`, the roles in which a participation of the focal organisation decides `portfolio_entry` (§2.7); whether `coordinator` counts is decided under ⚑ D-10. Changing the attribute on the Codebook page recomputes the derived values.

### `dimension` (fixed codes; Phase 3)

The four dimensions of the paper's analytical framework, "Table 1. Proposed Analytical Framework for Digital Innovation in Wartime Government" [paper]. Labels, definitions (the "Analytical focus" column) and theoretical sources are verbatim from the paper. Evidence targets name them as `dimension:D1` … `D4` (code `dn` ↔ target `dimension:Dn`).

| Code | Label | Definition (analytical focus) | Theoretical source |
|---|---|---|---|
| `d1` | Emerging public needs and governmental priorities | What public problem or need motivated the initiative? Which citizens, businesses, or institutions were affected? | Gil-Garcia et al. (2018); Janowski (2015) |
| `d2` | Digital platforms | Were existing platforms or infrastructures used or extended? | Yoo et al. (2012) |
| `d3` | Distributed innovation | Which organizations participated, and what were their roles? | Yoo et al. (2012) |
| `d4` | Combinatorial innovation | Were existing technologies, data, or services recombined? | Yoo et al. (2012) |

### `analysis_code` (multi-valued; Phase 3)

The team's analysis codes within the dimensions (§2.10). **No terms yet:** the vocabulary starts empty and grows on the Codebook page or from the capture panel during coding. Every term needs `attributes.dimension` (`d1`…`d4`), which cannot change once the code is used. The codebook export lists up to three coded passages of each code as anchor examples.

### `relation_type` (read as "from — type — to")

| Code | Definition |
|---|---|
| `builds_on` | Technically uses or depends on the target (e.g. a service built on a platform). |
| `extends` | Adds functions, groups or channels to the target. |
| `recombines` | Combines the target with other components into a new offering (one relation per combined component). |
| `part_of` | Is a component or sub-unit of the target. |
| `successor_of` | Replaces the target. |
| `related_to` | Other documented relation (explain in `description`). |

### `component_type` (draft)

`data_exchange`, `identification_trust` (identification, signatures), `registry`, `payment`, `cloud_hosting`, `communication` (notifications, messaging), `other`.

### `verification_status`

| Code | Definition |
|---|---|
| `unverified` | Not yet checked by a person (default for collected values). |
| `verified` | Checked by a person against evidence. |
| `disputed` | Contradicting evidence or disagreement; explanation in a comment. |

### Provenance kinds (`field_meta.src`)

`seed` (from the assignment's seed table), `collector:<name>@<run>`, `manual` (set in the app; its one user is recorded as `user` in `by`, D-15), `import:<file>`. A restore keeps the original source.

### `language`

`uk` (Ukrainian), `en` (English), `ru` (Russian), `other` (explain in `notes`). ISO 639-1 codes.

### `period` (derived values, §2.7)

| Code | Label | Definition |
|---|---|---|
| `pre_ministry` | Before the ministry | The launch interval ends before `MINISTRY_FOUNDED`, or, without a dated launch or beta-launch event, the archive bound lies before `MINISTRY_FOUNDED`. |
| `pre_invasion` | Ministry, before the full-scale invasion | The launch interval lies within `MINISTRY_FOUNDED` … `FULL_SCALE_INVASION` − 1 day. |
| `full_scale_war` | Full-scale war | The launch interval starts on or after `FULL_SCALE_INVASION`. |
| `unknown` | Unknown | No dated launch, beta-launch or archive event, a launch interval that straddles a cut-off date, or only an archive bound on or after `MINISTRY_FOUNDED`; the reason is given in `period_reason`. |

### `war_trajectory` (derived values, §2.7)

| Code | Label | Definition |
|---|---|---|
| `new_in_war` | New in war | The launch interval starts on or after `FULL_SCALE_INVASION`, and no archive bound lies before `FULL_SCALE_INVASION`. |
| `adapted_in_war` | Adapted in war | Existed before the invasion: the launch interval ends before `FULL_SCALE_INVASION`, or an archive bound lies before `FULL_SCALE_INVASION` and the launch interval, if any, starts before it. At least one modification event starts on or after `FULL_SCALE_INVASION`. |
| `prewar_unchanged` | Pre-war, no recorded change | Existed before the invasion (as for `adapted_in_war`). Every modification event is dated and ends before `FULL_SCALE_INVASION`, or there is none: no modification on or after the invasion is recorded up to the release date. |
| `unknown` | Unknown | Not determinable; the reason is given in `trajectory_reason`. |

### `derived_reason` (reason codes of derived values)

| Code | Definition |
|---|---|
| `no_date` | No dated launch, beta-launch or archive event; for `entry_period_reason`: no participation of the focal organisation in a portfolio role (§2.7) with a start date. |
| `imprecise_date` | The launch interval, taken over all dated launch events or, if there are none, all dated beta-launch events, straddles a cut-off date: it starts before the date and ends on or after it; for `entry_period_reason`: the portfolio-entry interval straddles a cut-off date. |
| `archive_bound_only` | Only an archive upper bound is known (no dated launch or beta-launch event), and it does not decide the value: it lies on or after `MINISTRY_FOUNDED` (`period_reason`) or on or after `FULL_SCALE_INVASION` (`trajectory_reason`). |
| `imprecise_modification_date` | A modification event is undated or straddles `FULL_SCALE_INVASION`. |
| `conflicting_dates` | The launch interval starts on or after `FULL_SCALE_INVASION`, but an archive bound lies before `FULL_SCALE_INVASION`, so the item existed before the invasion. |

**Fixed codes:** the system vocabularies `verification_status`, `screening_status`, `date_basis`, `date_precision`, `period`, `war_trajectory`, `derived_reason` and (Phase 3) `dimension`, as well as the event types `launch`, `beta_launch` and `first_archived`, are used by program logic. Their codes cannot be added to or deactivated; labels and definitions remain editable.

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

The precision of each pattern (the share of accepted, also edited and accepted, among its decided `create_event` proposals) is reported in the review inbox ("Pattern precision", from `GET /api/proposals/summary`; `docs/API.md` §7.4, `docs/UI.md` §8.2), not in the statistics of a run, so the list can be improved on the basis of evidence.

**Implementation:** `codebook/event_patterns.yaml` holds this list (one entry per Ukrainian stem or phrase and one per English cell, nothing added); the matching rules are in `docs/COLLECTORS.md` §7.7. Like `parameters.yaml` it is not a vocabulary.

## 5. Source label mappings (draft)

`codebook/collector_mappings.yaml` maps labels that sources use to codes of this codebook, for the collectors (`docs/COLLECTORS.md` §7.9): the document kinds of thedigital.gov.ua → `doc_type` (unmapped kinds: `other`) and the channel leads of diia.gov.ua service pages → `channel`. The mappings are draft coding rules, open to the team like the vocabularies; a target code must be an active term, and an unmapped label is reported to the collector run (`unmapped_label`).
