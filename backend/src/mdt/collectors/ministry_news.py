"""C4 ``ministry_news``: the ministry's news, documents, ``/ministry`` page, year-in-review
microsites and linked files (docs/COLLECTORS.md §8.4, SOURCES S4).

Parts (option ``parts``, default all), each read in this order:

* **news:** ``/news`` and ``/news/page/<n>``. ``incremental`` stops after a page whose items
  were all up to date (at least 2 pages); ``full`` reads every page up to
  ``pagination.lastPage``. An article page is fetched when its key ``news:<slug>`` is new,
  when its listing title, ``publishedAt.iso8601`` or URL differ from the observation's
  details, or with ``refetch``; every other listed article is sighted.
* **documents:** every run reads all ``/documents`` pages. ``file`` items (key
  ``file:<md5>``) fetch their storage file once (the MD5 of the body must equal the file
  name); ``content`` items (key ``doc:<group/slug>``) fetch their page when new or changed,
  and each attachment (a link to a storage file) becomes a file document; ``link`` items
  are references without a request. Unchanged items are sighted.
* **ministry:** ``/ministry`` every run: the page as a document and its embedded document
  items, handled like listing items (same keys).
* **microsites:** the three year-in-review sites every run (conditional GET).

Every document is created directly (DATA_MODEL §15.4). The site's ``publishedAt`` dates an
article (``published``) but only the site's record of a listed document
(``source_record_at``, never ``published``, SOURCES S4). When the request of a listed
document fails, the document is reconciled from its listing values alone, and an article is
only sighted; neither records the details its change detection compares, so the next run
tries again. The listing is complete only in ``full`` mode with every part selected and every
news and documents page parsed.

The page parsers are in :mod:`mdt.collectors.ministry_news_pages`; :class:`MinistryNews` does
the requests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from mdt.collectors.base import (
    Candidate,
    FatalRunError,
    Observation,
    RunContext,
    TypeDeclaration,
)
from mdt.collectors.mappings import LabelMapping, mapping_for_run
from mdt.collectors.ministry_news_pages import (
    DOCUMENTS_URL,
    FETCHED,
    FILE,
    LINK,
    MINISTRY_URL,
    NEWS_URL,
    parse_article,
    parse_document_page,
    parse_documents_listing,
    parse_microsite,
    parse_ministry_page,
    parse_news_listing,
    with_file,
)
from mdt.collectors.thedigital import HOST, Pagination, SiteValues, fetch_parsed

NAME = "ministry_news"
#: The year-in-review microsites (SOURCES S4, C-4).
MICROSITES = (
    "https://2years.thedigital.gov.ua/",
    "https://5years.thedigital.gov.ua/",
    "https://2025.thedigital.gov.ua/",
)
PARTS = ("news", "documents", "ministry", "microsites")
#: The mapping of document kinds to ``doc_type`` (codebook/collector_mappings.yaml).
KINDS_MAPPING = "ministry_document_kinds"
#: Observation detail of a content document: the keys of its attachments.
ATTACHMENTS = "attachments"

DOCUMENTS = TypeDeclaration(
    creates=True,
    writes=frozenset(
        {
            "title",
            "url",
            "publisher",
            "publisher_org_id",
            "doc_type",
            "language",
            "published",
            "published_basis",
            "published_text",
            "published_at_utc",
            "source_record_at",
            "license",
        }
    ),
    match_rules=("document",),
)


# --------------------------------------------------------------------------------------
# The collector
# --------------------------------------------------------------------------------------


def listing_only(item: Candidate) -> Candidate:
    """A listed document whose request failed: its listing values without the details
    that change detection compares, so the next run requests it again."""
    return replace(item, details={"type": item.details["type"]})


def up_to_date(observation: Observation | None, item: Candidate) -> bool:
    """Whether an observation already holds the listing values of an item."""
    return observation is not None and all(
        observation.details.get(name) == value for name, value in item.details.items()
    )


@dataclass
class _Run:
    """The state of one run: values, the keys handled so far and the ``limit``."""

    ctx: RunContext
    values: SiteValues
    kinds: LabelMapping | None
    refetch: bool
    limit: int | None
    handled: set[str] = field(default_factory=set)
    reconciled: int = 0

    def stopped(self) -> bool:
        """A cancel was requested or ``limit`` items were reconciled."""
        return self.ctx.cancelled() or (self.limit is not None and self.reconciled >= self.limit)

    def first(self, key: str) -> bool:
        """True the first time ``key`` comes up in the run (DATA_MODEL §15.6: the first
        candidate of a key wins, later ones are skipped)."""
        if key in self.handled:
            return False
        self.handled.add(key)
        return True

    def reconcile(self, candidate: Candidate) -> None:
        """Reconcile one candidate (counted against ``limit``)."""
        self.ctx.reconcile(candidate)
        self.reconciled += 1

    def sight(self, item: Candidate) -> None:
        """A sighting of an item that was not (or not successfully) fetched."""
        self.ctx.observe(item.entity_type, item.key, url=item.url, label=item.label)

    def mapping(self) -> LabelMapping:
        """The kinds mapping (loaded for the documents and ministry parts)."""
        assert self.kinds is not None
        return self.kinds


class MinistryNews:
    """C4: news, documents, ``/ministry`` and the microsites, in this order."""

    NAME = NAME
    VERSION = 1
    DECLARATION: Mapping[str, TypeDeclaration] = {"document": DOCUMENTS}
    MODES: tuple[str, ...] = ("incremental", "full")
    PARAMS = frozenset({"limit", "refetch"})

    def run(self, ctx: RunContext) -> None:
        """Read the selected parts; the listing is complete after a ``full`` run of every
        part whose news and documents pages were all parsed (§8.4)."""
        parts = selected_parts(ctx.options)
        ctx.client.set_listing_host(HOST)
        kinds = None
        if parts & {"documents", "ministry"}:
            kinds = mapping_for_run(ctx, KINDS_MAPPING)
        limit = ctx.params.get("limit")
        run = _Run(ctx, SiteValues.of(ctx), kinds, bool(ctx.params.get("refetch")), limit)
        complete = True
        if "news" in parts:
            complete = self._news(run) and complete
        if "documents" in parts and not run.stopped():
            complete = self._documents(run) and complete
        if "ministry" in parts and not run.stopped():
            self._ministry(run)
        if "microsites" in parts and not run.stopped():
            self._microsites(run)
        full = ctx.mode == "full" and parts == frozenset(PARTS)
        if full and complete and not run.stopped():
            ctx.listing_complete()

    # News ------------------------------------------------------------------------------

    def _news(self, run: _Run) -> bool:
        """The news listing and its articles; True if every listing page was parsed."""
        ctx = run.ctx
        incremental = ctx.mode != "full"
        pages = Pagination(NEWS_URL)
        complete, read, number = True, 0, 1
        while number <= pages.last_page:
            if run.stopped():
                return False
            page = fetch_parsed(ctx, pages.page_url(number), parse_news_listing)
            number += 1
            if page is None:
                complete = False
                if incremental:
                    return False
                continue
            pages.update(ctx, page[1], number - 1)
            current = 0  # items that needed no request (or were handled earlier in the run)
            for item in page[1].candidates:
                if run.stopped():
                    return False
                if not run.first(item.key):
                    current += 1
                    continue
                if up_to_date(ctx.observation(item.key), item):
                    current += 1
                    if not run.refetch:
                        run.sight(item)
                        continue
                self._article(run, item)
            read += 1
            if incremental and read >= 2 and current == len(page[1].candidates):
                return False
        return complete

    def _article(self, run: _Run, item: Candidate) -> None:
        assert item.url is not None
        page = fetch_parsed(run.ctx, item.url, lambda snapshot: parse_article(snapshot, run.values))
        if page is None or not page[1].candidates:
            run.sight(item)
            return
        candidate = page[1].candidates[0]
        candidate.details.update(item.details)
        run.reconcile(candidate)

    # Documents -------------------------------------------------------------------------

    def _documents(self, run: _Run) -> bool:
        """Every documents listing page and its items; True if every page was parsed."""
        pages = Pagination(DOCUMENTS_URL)
        complete, number = True, 1
        while number <= pages.last_page:
            if run.stopped():
                return False
            page = fetch_parsed(
                run.ctx,
                pages.page_url(number),
                lambda snapshot: parse_documents_listing(snapshot, run.mapping()),
            )
            number += 1
            if page is None:
                complete = False
                continue
            pages.update(run.ctx, page[1], number - 1)
            for item in page[1].candidates:
                if run.stopped():
                    return False
                self._item(run, item)
        return complete

    def _item(self, run: _Run, item: Candidate) -> None:
        """One listed document, the first time its key comes up in the run."""
        if not run.first(item.key):
            return
        kind = item.details["type"]
        if kind == FILE:
            self._file(run, item)
            return
        observation = run.ctx.observation(item.key)
        current = up_to_date(observation, item)
        if kind == LINK:
            if current:
                run.sight(item)
            else:
                run.reconcile(item)
        elif current and not run.refetch:
            run.sight(item)
            assert observation is not None
            for key in observation.details.get(ATTACHMENTS) or ():
                if run.first(key):
                    run.ctx.observe("document", key)
        else:
            self._content(run, item)

    def _content(self, run: _Run, item: Candidate) -> None:
        """A content document's page and its attachments. The listing values are recorded
        only when the page and every attachment were read, so a failure is retried."""
        assert item.url is not None
        page = fetch_parsed(
            run.ctx,
            item.url,
            lambda snapshot: parse_document_page(snapshot, run.mapping(), run.values),
        )
        if page is None or not page[1].candidates:
            run.reconcile(listing_only(item))
            return
        document, *attachments = page[1].candidates
        read = [
            self._file(run, attachment) for attachment in attachments if run.first(attachment.key)
        ]
        document.details[ATTACHMENTS] = [attachment.key for attachment in attachments]
        if all(read):
            document.details.update(item.details)
        run.reconcile(document)

    def _file(self, run: _Run, item: Candidate) -> bool:
        """A file document: fetched once; afterwards only its listing values are compared
        (a change is reconciled without a request). Returns False if the file could not
        be read (the document is reconciled from its listing values, and the next run
        fetches the file again)."""
        ctx = run.ctx
        observation = ctx.observation(item.key)
        if observation is not None and observation.details.get(FETCHED):
            if up_to_date(observation, item):
                run.sight(item)
            else:
                run.reconcile(item)
            return True
        assert item.url is not None
        result = ctx.client.get(item.url)
        if not result.ok or result.snapshot is None:
            run.reconcile(listing_only(item))
            return False
        candidate, warnings = with_file(item, result.snapshot)
        for code, text in warnings:
            ctx.message(
                "warning", code, text, url=item.url, snapshot_id=result.snapshot.raw_snapshot_id
            )
        run.reconcile(candidate)
        return True

    # /ministry and microsites ----------------------------------------------------------

    def _ministry(self, run: _Run) -> None:
        page = fetch_parsed(
            run.ctx,
            MINISTRY_URL,
            lambda snapshot: parse_ministry_page(snapshot, run.mapping(), run.values),
        )
        if page is None or not page[1].candidates:
            return
        document, *items = page[1].candidates
        if run.first(document.key):
            run.reconcile(document)
        for item in items:
            if run.stopped():
                return
            self._item(run, item)

    def _microsites(self, run: _Run) -> None:
        for url in MICROSITES:
            if run.stopped():
                return
            page = fetch_parsed(run.ctx, url, parse_microsite)
            if page is None:
                continue
            for candidate in page[1].candidates:
                if run.first(candidate.key):
                    run.reconcile(candidate)


def selected_parts(options: Mapping[str, Any]) -> frozenset[str]:
    """The parts of option ``parts`` (default all); anything else fails the run."""
    value: Any = options.get("parts", list(PARTS))
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(part, str) or part not in PARTS for part in value)
    ):
        raise FatalRunError(f"option parts must be a non-empty list of {', '.join(PARTS)}")
    return frozenset(value)


COLLECTOR = MinistryNews()
