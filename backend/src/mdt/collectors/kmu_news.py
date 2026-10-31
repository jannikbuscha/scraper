"""C4b ``kmu_news``: the ministry's news on the Government portal www.kmu.gov.ua
(docs/COLLECTORS.md §8.4, SOURCES S4b).

**Discovery per run:** ``/sitemap.xml`` (a ``urlset`` listing the child sitemaps), then the
Ukrainian post sitemaps ``sitemap-rainlab-blog-models-post-<n>.xml`` and the English ones
under ``/en/``, one GET each. Ukrainian entries whose ``lastmod`` lies in the window
(options ``window_from``, ``window_to``) and whose slug matches a keyword pattern (option
``keywords``) are the candidates; ``lastmod`` only selects the window and never dates a
document. A candidate without an observation is fetched and judged (with ``refetch`` every
candidate is); entries with an observation are sighted.

**Recall sample** (parameters ``recall_sample`` and ``recall_seed``; options ``recall_from``,
``recall_to``): the Ukrainian entries in the recall window that match no keyword, sorted by
URL and shuffled with a generator seeded with ``recall_seed``; the first ``recall_sample`` of
them are fetched and judged like candidates (their observations get
``details.recall_sample``), and ``stats.extra`` records the counts the recall estimate needs.

**Relevance:** a page is kept if its publishing body is the ministry (Ukrainian pages: a
link to thedigital.gov.ua; English: "Ministry of Digital Transformation") or an alias of a
live project or service occurs in its title or text; otherwise no document is created and
its observation (``details.discarded = "not_relevant"``) keeps it from being fetched again.
For a relevant Ukrainian article whose slug the English sitemap lists, ``/en/news/<slug>``
is fetched as a separate document.

**Sightings:** every entry whose key has an observation read in the run (candidates and
sample entries) or whose key is the ``external_id`` of a live document of this collector is
sighted; other observations (e.g. of entries that stopped being candidates when the options
changed) are not looked up and count as missing after complete runs.

**Complete listing:** ``/sitemap.xml`` and every post sitemap parsed. The parsers are in
:mod:`mdt.collectors.kmu_news_pages`.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from typing import Any

from mdt.collectors.base import (
    MAX_KEY_CHARS,
    FatalRunError,
    Observation,
    RunContext,
    Snapshot,
    TypeDeclaration,
    focal_org_id,
)
from mdt.collectors.kmu_news_pages import (
    HOST,
    Entry,
    parse_news_page,
    parse_post_sitemap,
    parse_sitemap_index,
    relevance,
)
from mdt.collectors.parsing import ParseError
from mdt.collectors.tagger import AliasIndex

NAME = "kmu_news"
SITEMAP_URL = f"https://{HOST}/sitemap.xml"
NOT_RELEVANT = "not_relevant"

DECLARATION: Mapping[str, TypeDeclaration] = {
    "document": TypeDeclaration(
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
                "license",
            }
        ),
        match_rules=("document",),
    )
}


# --------------------------------------------------------------------------------------
# Options, window, keywords and the recall sample
# --------------------------------------------------------------------------------------


def _day(value: Any, name: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise FatalRunError(f"option {name} must be a date (YYYY-MM-DD)") from exc


@dataclass(frozen=True)
class Options:
    """The collector's options (``sources.yaml``); a malformed option fails the run."""

    window_from: str
    window_to: str | None
    keywords: tuple[re.Pattern[str], ...]
    recall_from: str
    recall_to: str

    @classmethod
    def of(cls, options: Mapping[str, Any]) -> Options:
        """Validate the options."""
        patterns = options.get("keywords")
        if not isinstance(patterns, list) or not patterns:
            raise FatalRunError("option keywords must be a list of regular expressions")
        try:
            keywords = tuple(re.compile(str(pattern)) for pattern in patterns)
        except re.error as exc:
            raise FatalRunError(f"option keywords: invalid regular expression ({exc})") from exc
        window_to = options.get("window_to")
        return cls(
            window_from=_day(options.get("window_from", "2019-08-29"), "window_from"),
            window_to=None if window_to is None else _day(window_to, "window_to"),
            keywords=keywords,
            recall_from=_day(options.get("recall_from", "2019-09-01"), "recall_from"),
            recall_to=_day(options.get("recall_to", "2022-02-23"), "recall_to"),
        )

    def in_window(self, entry: Entry) -> bool:
        """``lastmod`` lies in the discovery window."""
        return (
            entry.day is not None
            and self.window_from <= entry.day
            and (self.window_to is None or entry.day <= self.window_to)
        )

    def in_recall_window(self, entry: Entry) -> bool:
        """``lastmod`` lies in the recall window."""
        return entry.day is not None and self.recall_from <= entry.day <= self.recall_to

    def keyword(self, entry: Entry) -> bool:
        """The slug matches a keyword pattern."""
        return any(pattern.search(entry.slug) for pattern in self.keywords)


def recall_sample(entries: Iterable[Entry], size: int, seed: int) -> list[Entry]:
    """The recall sample: ``entries`` sorted by URL, shuffled with a generator seeded with
    ``seed``, the first ``size`` of them (the same seed draws the same sample)."""
    population = sorted(entries, key=lambda entry: entry.url)
    random.Random(seed).shuffle(population)
    return population[:size]


def _date_number(day: str) -> int:
    """A ``YYYY-MM-DD`` date as the integer ``YYYYMMDD`` (stats hold integers only)."""
    return int(day.replace("-", ""))


# --------------------------------------------------------------------------------------
# The collector
# --------------------------------------------------------------------------------------


def _fetch[T](ctx: RunContext, url: str, parse: Callable[[Snapshot], T]) -> T | None:
    """GET ``url`` and parse the response; None when the request failed (the client wrote
    the run message) or the parser raised :class:`ParseError` (``parse_error``)."""
    result = ctx.client.get(url)
    if not result.ok:
        return None
    snapshot = result.snapshot
    if snapshot is None:
        ctx.message("error", "parse_error", f"{url}: the response has no body", url=url)
        return None
    try:
        parsed = parse(snapshot)
    except ParseError as exc:
        ctx.message(
            "error", "parse_error", f"{url}: {exc}", url=url, snapshot_id=snapshot.raw_snapshot_id
        )
        return None
    ctx.count("pages_parsed")
    return parsed


@dataclass
class _Listing:
    """What the sitemaps gave: entries (deduplicated by key, in listing order) and whether
    every post sitemap was parsed."""

    ukrainian: list[Entry] = field(default_factory=list)
    english: list[Entry] = field(default_factory=list)
    complete: bool = True


def read_listing(ctx: RunContext) -> _Listing | None:
    """``/sitemap.xml`` and every post sitemap it lists; None when ``/sitemap.xml`` could
    not be read or the run was cancelled. A complete listing tells the client, so that later
    failures of the host only make the run partial (docs/COLLECTORS.md §4.7)."""
    index = _fetch(ctx, SITEMAP_URL, parse_sitemap_index)
    if index is None:
        return None
    listing = _Listing()
    sitemaps = [(url, "uk") for url in index[0]] + [(url, "en") for url in index[1]]
    seen: set[str] = set()
    for url, language in sitemaps:
        if ctx.cancelled():
            return None
        entries = _fetch(ctx, url, partial(parse_post_sitemap, language=language))
        if entries is None:
            listing.complete = False
            continue
        target = listing.english if language == "en" else listing.ukrainian
        for entry in entries:
            if entry.key not in seen:
                seen.add(entry.key)
                target.append(entry)
    if listing.complete:
        ctx.client.listing_done()
    return listing


@dataclass
class _Run:
    """The state of one run: options, the keys handled so far and their judgements."""

    ctx: RunContext
    options: Options
    refetch: bool
    limit: int | None
    focal_org_id: str | None
    known: frozenset[str]  # external IDs of this collector's live documents
    fetched: int = 0
    handled: set[str] = field(default_factory=set)
    judged: dict[str, str] = field(default_factory=dict)  # key -> relevant | discarded
    _aliases: AliasIndex | None = None

    def stopped(self) -> bool:
        """A cancel was requested or ``limit`` pages were fetched."""
        return self.ctx.cancelled() or (self.limit is not None and self.fetched >= self.limit)

    @property
    def aliases(self) -> AliasIndex:
        """The alias index of the live projects and services (built once per run)."""
        if self._aliases is None:
            names = ["aliases", "name_en", "name_uk"]
            records = self.ctx.live_records("project", names)
            records += self.ctx.live_records("service", names)
            self._aliases = AliasIndex.from_records(records)
        return self._aliases

    def sight(self, entry: Entry, observation: Observation | None = None) -> None:
        """A sighting of an entry judged in an earlier run (a known document's entry, or
        one with an observation); notes that judgement."""
        self.handled.add(entry.key)
        discarded = observation is not None and observation.details.get("discarded") == NOT_RELEVANT
        self.judged[entry.key] = "discarded" if discarded else "relevant"
        self.ctx.observe("document", entry.key, url=entry.url, details={"lastmod": entry.lastmod})

    def visit(self, entry: Entry, discovery: str, extra: Mapping[str, Any] | None = None) -> None:
        """Sight an entry judged before (unless ``refetch``), else fetch and judge it;
        ``discovery`` and ``extra`` go into its observation's details."""
        if entry.key in self.handled or self.stopped():
            return
        if len(entry.key) > MAX_KEY_CHARS:
            self.handled.add(entry.key)
            self.ctx.message("warning", "invalid_value", f"{entry.url}: the slug is too long")
            return
        known = entry.key in self.known
        observation = None if known else self.ctx.observation(entry.key)
        if (known or observation is not None) and not self.refetch:
            self.sight(entry, observation)
            return
        self.handled.add(entry.key)
        self.fetched += 1
        self._judge(entry, {"discovery": discovery, "lastmod": entry.lastmod, **(extra or {})})

    def _judge(self, entry: Entry, details: dict[str, Any]) -> None:
        """Fetch a page; reconcile it when relevant, else observe it as discarded."""
        ctx = self.ctx
        licence = ctx.client.config.licence.code
        parse = partial(parse_news_page, focal_org_id=self.focal_org_id, default_licence=licence)
        parsed = _fetch(ctx, entry.url, parse)
        if parsed is None or not parsed.candidates:
            return  # the run message is written; the next run tries again
        candidate = parsed.candidates[0]
        snapshot_id = candidate.evidence.raw_snapshot_id
        for code, text in parsed.warnings:
            ctx.message("warning", code, text, url=entry.url, snapshot_id=snapshot_id)
        if entry.language == "en":
            reason: str | None = "english_version"
        else:
            reason = relevance(candidate, self.aliases)
        if reason is not None:
            self.judged[entry.key] = "relevant"
            candidate.details.update(details, relevance=reason, discarded=None)
            ctx.reconcile(candidate)
            return
        self.judged[entry.key] = "discarded"
        ctx.count("discarded")
        ctx.observe(
            "document",
            entry.key,
            url=candidate.url,
            label=candidate.label,
            details={**candidate.details, **details, "discarded": NOT_RELEVANT},
        )
        body = candidate.details.get("publishing_body") or "not stated"
        ctx.message(
            "info",
            "discarded",
            f"{entry.url}: not relevant (publishing body: {body}; no alias match)",
            url=entry.url,
            snapshot_id=snapshot_id,
        )


class KmuNews:
    """The C4b collector (module docstring)."""

    NAME = NAME
    VERSION = 1
    DECLARATION = DECLARATION
    MODES: tuple[str, ...] = ()
    PARAMS: frozenset[str] = frozenset({"limit", "refetch", "recall_sample", "recall_seed"})

    def run(self, ctx: RunContext) -> None:
        """Discover; fetch and judge the candidates, the recall sample and the English
        versions; sight the entries judged before."""
        options = Options.of(ctx.options)
        documents = ctx.live_records("document", ["source_id", "external_id"])
        run = _Run(
            ctx,
            options,
            refetch=bool(ctx.params.get("refetch", False)),
            limit=ctx.params.get("limit"),
            focal_org_id=focal_org_id(ctx),
            known=frozenset(
                str(record["external_id"])
                for record in documents
                if record["source_id"] == NAME and record["external_id"]
            ),
        )
        listing = read_listing(ctx)
        if listing is None:
            return
        for entry in listing.ukrainian:
            if ctx.cancelled():
                return
            if options.in_window(entry) and options.keyword(entry):
                ctx.count("keyword_candidates")
                run.visit(entry, "keyword")
            elif entry.key in run.known and entry.key not in run.handled:
                run.sight(entry)
        size = int(ctx.params.get("recall_sample", 0))
        seed = int(ctx.params.get("recall_seed", 1))
        sample = self._sample(run, listing.ukrainian, size, seed) if size else []
        self._english(run, listing)
        if ctx.cancelled():
            return
        if size:
            self._recall_stats(run, listing.ukrainian, sample, seed)
        if listing.complete and not run.stopped():
            ctx.listing_complete()

    @staticmethod
    def _sample(run: _Run, entries: Sequence[Entry], size: int, seed: int) -> list[Entry]:
        """Draw and visit the recall sample."""
        options = run.options
        population = [
            entry
            for entry in entries
            if options.in_recall_window(entry) and not options.keyword(entry)
        ]
        sample = recall_sample(population, size, seed)
        for entry in sample:
            run.visit(entry, "recall_sample", {"recall_sample": seed})
        return sample

    @staticmethod
    def _english(run: _Run, listing: _Listing) -> None:
        """The English versions of the relevant Ukrainian articles, then sightings of the
        other known English documents."""
        english = {entry.slug: entry for entry in listing.english}
        for entry in listing.ukrainian:
            version = english.get(entry.slug)
            if version is not None and run.judged.get(entry.key) == "relevant":
                run.visit(version, "english_version")
        for version in listing.english:
            if run.ctx.cancelled():
                return
            if version.key in run.known and version.key not in run.handled:
                run.sight(version)

    @staticmethod
    def _recall_stats(
        run: _Run, entries: Sequence[Entry], sample: Sequence[Entry], seed: int
    ) -> None:
        """The counts of the recall estimate in ``stats.extra`` (the window as integers
        ``YYYYMMDD``, because run statistics hold integers only)."""
        options = run.options
        window = [entry for entry in entries if options.in_recall_window(entry)]
        keyword = [run.judged.get(entry.key) for entry in window if options.keyword(entry)]
        counts = {
            "recall_seed": seed,
            "recall_from": _date_number(options.recall_from),
            "recall_to": _date_number(options.recall_to),
            "window_entries": len(window),
            "keyword_entries": len(keyword),
            "nonkeyword_entries": len(window) - len(keyword),
            "keyword_relevant": keyword.count("relevant"),
            "keyword_discarded": keyword.count("discarded"),
            "sample_size": len(sample),
            "sample_relevant": [run.judged.get(entry.key) for entry in sample].count("relevant"),
        }
        for name, value in counts.items():
            run.ctx.count(name, value)


COLLECTOR = KmuNews()
