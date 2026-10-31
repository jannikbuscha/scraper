"""C1 ``ministry_projects``: the project list of thedigital.gov.ua (docs/COLLECTORS.md §8.1,
SOURCES S1).

Per run: the listing ``/projects`` and its pages ``/projects/page/<n>`` up to
``pagination.lastPage``, then one project page ``/projects/<rubric>/<slug>`` per entry of
``type = content`` (entries of ``type = link`` get no request: the listing carries their
``externalUrl``). Everything is read from the embedded loader data (§7.2).

* **Projects** (key ``entry:<slug>``, never created directly: an unmatched entry becomes a
  ``create_entity`` proposal) match by the project UUID (``external_id``, project page) or
  by URL (the entry URL in ``ministry_urls``, ``externalUrl`` in ``official_urls``). They
  get ``description_uk`` from the listing's caption, ``ministry_categories`` (the primary
  rubric, then the additional rubrics sorted by code; content entries only when their page
  was read) and the entry URL (content) or ``externalUrl`` (link) as add-only URLs. The
  title is only the name of a ``create_entity`` proposal (names are never rewritten). The
  outbound ``linkListItem`` links of a project page that leave the site and are no legal
  references or files are proposed as ``official_urls``.
* **Project pages** (key ``page:<project.id>``) are created as documents with the caption
  and the page blocks as text and a suggested link to their project.

Parsers are pure functions of a snapshot; :class:`MinistryProjects` does the requests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlsplit

from mdt.collectors.base import Candidate, LinkHint, RunContext, Snapshot, TypeDeclaration
from mdt.collectors.parsing import ParseError, ParseResult
from mdt.collectors.parsing.texts import clip_quote
from mdt.collectors.parsing.tiptap import OutboundLink, tiptap_to_text
from mdt.collectors.thedigital import (
    NOT_FOUND_STATUSES,
    PUBLISHER,
    SITE,
    TURBO_STREAM,
    Pagination,
    SiteValues,
    evidence_of,
    fetch_parsed,
    joined_text,
    last_segment,
    list_of,
    loader_entry,
    mapping_of,
    optional_text,
    page_licence,
    text_of,
)

NAME = "ministry_projects"
LISTING_URL = f"{SITE}/projects"
#: Snippet of the suggested link from a project page to its project (§8.1).
PAGE_LINK_SNIPPET = "Project page on thedigital.gov.ua"
#: Hosts (and their subdomains) whose links are never proposed as official URLs: the site
#: itself, and legal acts, which stay references (SOURCES S6).
NOT_OFFICIAL_DOMAINS = ("thedigital.gov.ua", "rada.gov.ua", "kmu.gov.ua")
#: Paths ending in these extensions are files, never official URLs.
FILE_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")
CONTENT = "content"
LINK = "link"

PROJECTS = TypeDeclaration(
    creates=False,
    writes=frozenset(
        {"name_uk", "description_uk", "ministry_categories", "ministry_urls", "official_urls"}
    ),
    propose_only=frozenset({"official_urls"}),
    match_rules=("external_id", "url_fields"),
    discontinued=True,
)
PROJECT_PAGES = TypeDeclaration(
    creates=True,
    writes=frozenset(
        {"title", "url", "publisher", "publisher_org_id", "doc_type", "language", "license"}
    ),
    match_rules=("document",),
)


# --------------------------------------------------------------------------------------
# Keys, URLs and codes
# --------------------------------------------------------------------------------------


def entry_key(slug: str) -> str:
    """The observation key of an entry: its slug without the rubric segment."""
    return f"entry:{last_segment(slug)}"


def entry_url(slug: str) -> str:
    """The entry URL built from the data's ``<rubric>/<slug>`` (never from the request URL
    or ``<link rel=canonical>``, which echo any accepted path)."""
    return f"{SITE}/projects/{slug.strip('/')}"


def rubric_code(slug: str) -> str:
    """The ``ministry_category`` code of a rubric slug (``how-tos`` → ``how_tos``, §7.9)."""
    return slug.strip().replace("-", "_")


def is_official_link(link: OutboundLink) -> bool:
    """An outbound ``linkListItem`` link that leaves the site and is neither a legal
    reference nor a file (§8.1)."""
    if link.kind != "linkListItem":
        return False
    parts = urlsplit(link.href)
    host = (parts.hostname or "").lower()
    if any(host == domain or host.endswith(f".{domain}") for domain in NOT_OFFICIAL_DOMAINS):
        return False
    return not parts.path.lower().endswith(FILE_EXTENSIONS)


@dataclass(frozen=True)
class _Rubric:
    slug: str
    name: str | None

    @property
    def code(self) -> str:
        return rubric_code(self.slug)

    @property
    def source_label(self) -> str:
        """The label an ``unknown_code`` warning shows: the site label and the slug."""
        return f"{self.name} (rubric {self.slug})" if self.name else f"rubric {self.slug}"


def _rubric(value: Any, where: str) -> _Rubric | None:
    if value is None:
        return None
    data = mapping_of(value, where)
    return _Rubric(text_of(data.get("slug"), f"{where}.slug"), optional_text(data.get("name")))


def _codes(rubrics: Sequence[_Rubric]) -> tuple[list[str], dict[str, str]]:
    """The codes in the given order without repeats, and their source labels."""
    codes: list[str] = []
    labels: dict[str, str] = {}
    for rubric in rubrics:
        if rubric.code not in labels:
            codes.append(rubric.code)
            labels[rubric.code] = rubric.source_label
    return codes, labels


# --------------------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------------------


def parse_listing(snapshot: Snapshot) -> ParseResult:
    """A listing page (loader entry with ``projects`` and ``pagination``): one project
    candidate per entry from the listing alone, in listing order; ``next_urls`` are the
    project pages of the content entries; ``total`` and ``last_page`` from
    ``pagination``."""
    data = loader_entry(snapshot, ("projects",), required=("pagination",))
    pagination = mapping_of(data["pagination"], "pagination")
    result = ParseResult(
        total=_count(pagination.get("total"), "pagination.total"),
        last_page=_count(pagination.get("lastPage"), "pagination.lastPage"),
    )
    for index, item in enumerate(list_of(data["projects"], "projects")):
        candidate = _listing_candidate(mapping_of(item, f"projects[{index}]"), snapshot, index)
        result.candidates.append(candidate)
        if candidate.details["type"] == CONTENT:
            result.next_urls.append(str(candidate.url))
    return result


def _count(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ParseError(f"{where} is not a count")
    return value


def _listing_candidate(item: Mapping[str, Any], snapshot: Snapshot, index: int) -> Candidate:
    where = f"projects[{index}]"
    title = text_of(item.get("title"), f"{where}.title")
    slug = text_of(item.get("slug"), f"{where}.slug")
    kind = item.get("type")
    rubric = _rubric(item.get("rubric"), f"{where}.rubric")
    fields: dict[str, Any] = {"name_uk": title}
    caption = optional_text(item.get("caption"))
    if caption is not None:
        fields["description_uk"] = caption
    details: dict[str, Any] = {"type": kind, "rubric": rubric.slug if rubric else None}
    if kind == CONTENT:
        url = entry_url(slug)
        fields["ministry_urls"] = [url]
    elif kind == LINK:
        url = text_of(item.get("externalUrl"), f"{where}.externalUrl")
        fields["official_urls"] = [url]
        if rubric is not None:
            codes, labels = _codes([rubric])
            fields["ministry_categories"] = codes
            details["code_labels"] = labels
    else:
        raise ParseError(f"{where}.type is neither {CONTENT} nor {LINK}")
    return Candidate(
        entity_type="project",
        key=entry_key(slug),
        evidence=evidence_of(snapshot),
        label=title,
        url=url,
        fields=fields,
        details=details,
    )


def parse_project_page(snapshot: Snapshot, values: SiteValues) -> ParseResult:
    """A project page (loader entry with ``project``): a partial project candidate (the
    project UUID, ``ministry_categories`` and the proposed official URLs, all from this
    page) and the project-page document. A 404 or 410 is ``not_found``."""
    if snapshot.http_status in NOT_FOUND_STATUSES:
        return ParseResult(not_found=True)
    project = mapping_of(loader_entry(snapshot, ("project",))["project"], "project")
    project_id = text_of(project.get("id"), "project.id")
    title = text_of(project.get("title"), "project.title")
    slug = text_of(project.get("slug"), "project.slug")
    rubrics = [rubric] if (rubric := _rubric(project.get("rubric"), "project.rubric")) else []
    additional = [
        found
        for index, item in enumerate(
            list_of(project.get("additionalRubrics") or [], "project.additionalRubrics")
        )
        if (found := _rubric(item, f"project.additionalRubrics[{index}]")) is not None
    ]
    codes, labels = _codes([*rubrics, *sorted(additional, key=lambda item: item.code)])
    body = tiptap_to_text(project.get("blocks"))
    official: dict[str, str] = {}  # URL → link text, in page order
    for link in body.links:
        if is_official_link(link):
            official.setdefault(link.href, link.text)
    licence, warnings = page_licence(snapshot, values.default_licence)
    evidence = evidence_of(snapshot)
    key = entry_key(slug)
    url = entry_url(slug)
    partial = Candidate(
        entity_type="project",
        key=key,
        evidence=evidence,
        label=title,
        url=url,
        external_id=project_id,
        details={"code_labels": labels} if labels else {},
    )
    if codes:
        partial.fields["ministry_categories"] = codes
        partial.field_snapshots["ministry_categories"] = [snapshot.raw_snapshot_id]
    if official:
        partial.proposed["official_urls"] = list(official)
        partial.field_snapshots["official_urls"] = [snapshot.raw_snapshot_id]
        # The page, its link texts as the quote and the URLs as the locator (§8.1).
        partial.field_evidence["official_urls"] = replace(
            evidence,
            quote=clip_quote("; ".join(text for text in official.values() if text)) or None,
            locator="; ".join(official),
        )
    fields: dict[str, Any] = {
        "doc_type": "project_page",
        "title": title,
        "url": url,
        "publisher": PUBLISHER,
        "language": "uk",
    }
    if values.focal_org_id is not None:
        fields["publisher_org_id"] = values.focal_org_id
    if licence is not None:
        fields["license"] = licence
    document = Candidate(
        entity_type="document",
        key=f"page:{project_id}",
        evidence=evidence,
        label=title,
        url=url,
        external_id=project_id,
        fields=fields,
        text=joined_text(optional_text(project.get("caption")), body.text),
        text_snapshot_id=snapshot.raw_snapshot_id,
        extraction_method=TURBO_STREAM,
        links=[LinkHint(snippet=PAGE_LINK_SNIPPET, subject_key=key)],
    )
    return ParseResult(candidates=[partial, document], warnings=warnings)


def with_project_page(entry: Candidate, page: Candidate) -> Candidate:
    """The project candidate of a content entry completed by its page's partial candidate
    (UUID, categories, proposed official URLs); the listing values and evidence stay."""
    labels = {**entry.details.get("code_labels", {}), **page.details.get("code_labels", {})}
    return replace(
        entry,
        external_id=page.external_id,
        fields={**entry.fields, **page.fields},
        proposed={**entry.proposed, **page.proposed},
        field_snapshots={**entry.field_snapshots, **page.field_snapshots},
        field_evidence={**entry.field_evidence, **page.field_evidence},
        details={**entry.details, **({"code_labels": labels} if labels else {})},
    )


# --------------------------------------------------------------------------------------
# The collector
# --------------------------------------------------------------------------------------


class MinistryProjects:
    """C1: the listing, then the project pages, reconciled in listing order."""

    NAME = NAME
    VERSION = 1
    DECLARATION: Mapping[str, TypeDeclaration] = {
        "project": PROJECTS,
        "document": PROJECT_PAGES,
    }
    MODES: tuple[str, ...] = ()
    PARAMS = frozenset({"limit"})

    def run(self, ctx: RunContext) -> None:
        """Read the listing; when every listing page was parsed, the listing host's later
        failures only make the run partial. Then each entry (and its page) is reconciled;
        the listing counts as complete unless a listing page failed (§8.1)."""
        values = SiteValues.of(ctx)
        entries, complete = self._listing(ctx)
        if complete:
            ctx.client.listing_done()
        limit = ctx.params.get("limit")
        for index, entry in enumerate(entries):
            if ctx.cancelled() or (limit is not None and index >= limit):
                return
            self._entry(ctx, entry, values)
        if complete:
            ctx.listing_complete()

    def _listing(self, ctx: RunContext) -> tuple[list[Candidate], bool]:
        """The entries of every listing page (first occurrence per key) and whether every
        page was parsed; an empty listing never counts as complete (a site change must not
        mark every project missing, risk R3)."""
        pages = Pagination(LISTING_URL)
        entries: list[Candidate] = []
        complete = True
        number = 1
        while number <= pages.last_page:
            if ctx.cancelled():
                return entries, False
            page = fetch_parsed(ctx, pages.page_url(number), parse_listing)
            if page is None:
                complete = False
            else:
                pages.update(ctx, page[1], number)
                entries.extend(page[1].candidates)
            number += 1
        return _first_per_key(entries), complete and bool(entries)

    def _entry(self, ctx: RunContext, entry: Candidate, values: SiteValues) -> None:
        """Reconcile one entry: a content entry with what its page adds, then the page."""
        if entry.details["type"] != CONTENT:
            ctx.reconcile(entry)
            return
        assert entry.url is not None
        page = fetch_parsed(ctx, entry.url, lambda snapshot: parse_project_page(snapshot, values))
        if page is None:
            ctx.reconcile(entry)
            return
        snapshot, parsed = page
        partial, document = parsed.candidates
        if partial.key != entry.key:
            ctx.message(
                "error",
                "parse_error",
                f"{entry.url}: the page shows the project {partial.key}, not the listed "
                f"entry {entry.key}",
                url=entry.url,
                snapshot_id=snapshot.raw_snapshot_id,
            )
            ctx.reconcile(entry)
            return
        ctx.reconcile(with_project_page(entry, partial))
        ctx.reconcile(document)


def _first_per_key(candidates: Sequence[Candidate]) -> list[Candidate]:
    """The candidates without later repeats of a key (an entry that moved to the next
    page while the listing was read)."""
    seen: set[str] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        if candidate.key not in seen:
            seen.add(candidate.key)
            unique.append(candidate)
    return unique


COLLECTOR = MinistryProjects()
