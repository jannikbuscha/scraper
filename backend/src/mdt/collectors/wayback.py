"""C5 ``wayback``: archive upper bounds from the Wayback Machine's CDX index
(docs/COLLECTORS.md §8.5, docs/DATA_MODEL.md §15.12, SOURCES S5).

**URL set:** (a) the ``prefixes`` option, each queried as a prefix (``matchType=prefix``,
``collapse=urlkey``), page after page while the response ends with a resume key; (b) every
``ministry_urls`` and ``official_urls`` entry of the live projects and every ``urls`` entry
of the live services that no prefix covers, minus the excluded hosts, one single-URL query
(``limit=1``) per archive key. C5 requests no live host itself: a URL whose path the newest
stored robots.txt of its host disallows is never queried (SOURCES §5 item 2); without a stored
robots.txt with rules the URL is queried.

**Parser** (:func:`parse_cdx_json`): the documented JSON format (a header row naming the
columns, then rows of strings; a final ``[]`` followed by a one-element row is the resume
key), gzip-compressed or not; columns are located by name.

**Mapping:** per CDX ``urlkey`` the earliest row counts, over all rows and pages; rows are
compared with the subjects' URLs by archive key (:func:`mdt.domain.reconcile.archive_key`).
A row maps exactly to every subject with a URL of that key, and by slug to the project whose
ministry URL ends in ``/<slug>`` when the row is a pre-relaunch ``/projects/<slug>`` or an
other-rubric ``/projects/<rubric>/<slug>`` URL on the host of that ministry URL. An exact
match of a subject's own ministry or service URL creates a ``first_archived`` event; every
other mapping becomes a ``create_event`` proposal (both through ``ctx.first_archived``).

**Observations:** one unbound sighting (entity type ``event``) per archive key, from the
queried URLs and the CDX urlkeys, key ``url:<archive key>``, with ``details.earliest``
(timestamp or null), ``details.original`` and ``details.subject_ids``.

**Availability:** ``web.archive.org`` is the listing host. A blocked host, an unavailable
robots.txt or a failed first CDX request fails the run with ``Wayback Machine
unavailable``; later failures make it partial. Unavailable is never read as "no captures".
The listing is complete when every page of every prefix and every single-URL query was
answered and parsed.
"""

from __future__ import annotations

import gzip
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

from mdt.collectors.base import (
    MAX_KEY_CHARS,
    Capture,
    FatalRunError,
    RunContext,
    Snapshot,
    TypeDeclaration,
)
from mdt.collectors.client import ACCEPT_JSON, FetchResult, ListingHostUnavailable
from mdt.collectors.parsing import ParseError
from mdt.collectors.parsing.dates import kyiv_date_of_wayback_timestamp
from mdt.collectors.robots import RobotsPolicy, policy_from_response
from mdt.collectors.urls import UrlError, parse_fetch_url
from mdt.domain.reconcile import archive_key

NAME = "wayback"
CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
ARCHIVE = "https://web.archive.org/web"
#: The ``fl`` fields of every query, in this order (docs/COLLECTORS.md §8.5).
CDX_FIELDS = ("urlkey", "timestamp", "original", "statuscode", "mimetype")
#: Columns the parser cannot do without.
REQUIRED_COLUMNS = ("urlkey", "timestamp", "original")
DEFAULT_PAGE_LIMIT = 5000
#: The CDX server's maximum rows per query (SOURCES S5).
MAX_PAGE_LIMIT = 150_000
UNAVAILABLE = "Wayback Machine unavailable"
#: The site-wide rubric slugs of thedigital.gov.ua (SOURCES S1, 2026-10-29) and the
#: pagination segment ``page``: a ``/projects/<slug>`` row with one of them is a listing,
#: never a pre-relaunch project URL.
RUBRICS = frozenset(
    {
        "regions",
        "business",
        "army",
        "technologies",
        "education",
        "how-tos",
        "progress",
        "bezbaryernist",
        "postanovy-uriadu",
        "shtuchnyy-intelekt",
        "istoriyi",
        "zviazok-ta-internet",
    }
)
NOT_SLUGS = RUBRICS | {"page"}
#: Observation entity type: the record a capture becomes (a ``first_archived`` event).
OBSERVED_TYPE = "event"
GZIP_MAGIC = b"\x1f\x8b"
_TIMESTAMP = re.compile(r"\d{14}")
#: Characters left unescaped in the ``url=`` value (existing escapes stay as they are).
_URL_SAFE = "/:,()!*'~@;$%"
#: Resume keys come URL-encoded (``org%2Carchive%29%2F+19980109140106%21``) and are passed
#: back unchanged; only characters that would end the parameter are escaped.
_KEY_SAFE = _URL_SAFE + "+="


# --------------------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------------------


def _fields_part() -> str:
    return f"output=json&fl={','.join(CDX_FIELDS)}&filter=statuscode:200"


def prefix_query(prefix: str, page_limit: int, resume_key: str | None = None) -> str:
    """The CDX query of one page of a prefix (documented parameters, fixed order)."""
    query = (
        f"{CDX_ENDPOINT}?url={quote(prefix.strip(), safe=_URL_SAFE)}&matchType=prefix"
        f"&collapse=urlkey&{_fields_part()}&limit={page_limit}&showResumeKey=true"
    )
    if resume_key is not None:
        query += f"&resumeKey={quote(resume_key, safe=_KEY_SAFE)}"
    return query


def query_target(url: str) -> str:
    """The ``url=`` value of a single-URL query: the URL without scheme, query and
    fragment (``https://diia.gov.ua/services`` → ``diia.gov.ua/services``). Raises
    :class:`UrlError`."""
    parsed = parse_fetch_url(url)
    netloc = parsed.host if parsed.port is None else f"{parsed.host}:{parsed.port}"
    return netloc + parsed.path


def url_query(url: str) -> str:
    """The single-URL CDX query (earliest capture, ``limit=1``) of a subject URL."""
    target = quote(query_target(url), safe=_URL_SAFE)
    return f"{CDX_ENDPOINT}?url={target}&{_fields_part()}&limit=1"


def archive_capture_url(timestamp: str, original: str) -> str:
    """The capture URL of a CDX row."""
    return f"{ARCHIVE}/{timestamp}/{original}"


def url_form(text: str) -> str:
    """A URL or prefix as the CDX index matches prefixes: host lower-cased without
    ``www.``, trailing dot and default port, then the lower-cased path (``/`` when empty);
    no query. A text without a scheme counts as ``http``."""
    parts = urlsplit(text.strip() if "://" in text else f"http://{text.strip()}")
    host = (parts.hostname or "").rstrip(".").removeprefix("www.")
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None and port != {"http": 80, "https": 443}.get(parts.scheme.lower()):
        host = f"{host}:{port}"
    return host + (parts.path or "/").lower()


def covered(url: str, prefixes: Iterable[str]) -> bool:
    """Whether a prefix query returns the captures of ``url``."""
    form = url_form(url)
    return any(form.startswith(url_form(prefix)) for prefix in prefixes)


# --------------------------------------------------------------------------------------
# The parser
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CdxRow:
    """One capture row: the columns C5 reads and the row as listed (the evidence quote)."""

    urlkey: str
    timestamp: str
    original: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class CdxPage:
    """A parsed CDX response: its rows in order, the resume key and warnings."""

    rows: tuple[CdxRow, ...] = ()
    resume_key: str | None = None
    warnings: tuple[tuple[str, str], ...] = ()


def _decoded(body: bytes) -> Any:
    if body.startswith(GZIP_MAGIC):  # gzip by default, also without Content-Encoding
        try:
            body = gzip.decompress(body)
        except (OSError, EOFError) as exc:
            raise ParseError("the gzip-compressed CDX response cannot be decompressed") from exc
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ParseError("the CDX response is not JSON") from exc


def parse_cdx_json(snapshot: Snapshot) -> CdxPage:
    """Parse a CDX response with ``output=json`` (docs/COLLECTORS.md §8.5).

    ``[]`` and a header-only array mean no captures; a final ``[]`` followed by a
    one-element row is the resume key; further named columns are ignored. A row whose
    length differs from the header's, a timestamp that is not a 14-digit date or a
    missing column raises :class:`ParseError`. A row with a status other than 200 (the
    query filters on it) is skipped with the warning ``invalid_value``.
    """
    data = _decoded(snapshot.body)
    if not isinstance(data, list) or not all(isinstance(row, list) for row in data):
        raise ParseError("the CDX response is not an array of rows")
    if not data:
        return CdxPage()
    header, rows = data[0], data[1:]
    if not header or not all(isinstance(name, str) and name for name in header):
        raise ParseError("the first CDX row is not a list of field names")
    missing = [name for name in REQUIRED_COLUMNS if name not in header]
    if missing:
        raise ParseError(f"the CDX header lacks the columns {', '.join(missing)}")
    resume_key = None
    if len(rows) >= 2 and rows[-2] == [] and len(rows[-1]) == 1:
        key = rows[-1][0]
        if not isinstance(key, str) or not key:
            raise ParseError("the CDX resume key is not a string")
        resume_key, rows = key, rows[:-2]
    column = {name: header.index(name) for name in header}
    parsed: list[CdxRow] = []
    warnings: list[tuple[str, str]] = []
    for number, row in enumerate(rows, start=2):
        if len(row) != len(header) or not all(isinstance(value, str) for value in row):
            raise ParseError(
                f"CDX row {number} has {len(row)} values where the header names {len(header)}"
            )
        timestamp = row[column["timestamp"]]
        if not _TIMESTAMP.fullmatch(timestamp) or kyiv_date_of_wayback_timestamp(timestamp) is None:
            raise ParseError(f"CDX row {number}: {timestamp!r} is not a 14-digit timestamp")
        original, urlkey = row[column["original"]], row[column["urlkey"]]
        if not original or not urlkey:
            raise ParseError(f"CDX row {number} has no original URL or urlkey")
        status = row[column["statuscode"]] if "statuscode" in column else "200"
        if status != "200":
            warnings.append(("invalid_value", f"CDX row {number} has status {status!r}; skipped"))
            continue
        parsed.append(CdxRow(urlkey, timestamp, original, tuple(row)))
    return CdxPage(tuple(parsed), resume_key, tuple(warnings))


# --------------------------------------------------------------------------------------
# Subjects and mapping
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SubjectUrl:
    """A URL of a live project or service. ``own``: the subject's own ministry or service
    URL, whose exact match creates the event directly."""

    subject_id: str
    url: str
    key: str
    own: bool


def subject_urls(
    projects: Iterable[Mapping[str, Any]],
    services: Iterable[Mapping[str, Any]],
    exclude_hosts: Iterable[str],
) -> list[SubjectUrl]:
    """The URLs of ``projects`` (``{id, ministry_urls, official_urls}``) and ``services``
    (``{id, urls}``), minus excluded hosts and invalid URLs."""
    excluded = frozenset(exclude_hosts)
    found: list[SubjectUrl] = []
    lists = [(project, "ministry_urls", True) for project in projects]
    lists += [(project, "official_urls", False) for project in projects]
    lists += [(service, "urls", True) for service in services]
    for record, name, own in lists:
        for url in record.get(name) or ():
            try:
                host = parse_fetch_url(url).host
            except UrlError:
                continue
            if host not in excluded:
                found.append(SubjectUrl(str(record["id"]), url, archive_key(url), own))
    return found


def _segments(key: str) -> tuple[str, list[str]]:
    host, _, path = key.partition("/")
    return host, [part for part in path.split("/") if part]


@dataclass
class SubjectIndex:
    """The subjects' URLs by archive key, and the projects by ministry-URL slug."""

    by_key: dict[str, list[SubjectUrl]] = field(default_factory=dict)
    by_slug: dict[tuple[str, str], list[tuple[str, str]]] = field(default_factory=dict)

    @classmethod
    def of(cls, urls: Iterable[SubjectUrl], project_ids: Iterable[str]) -> SubjectIndex:
        """Index ``urls``; slugs come from the ministry URLs of ``project_ids``."""
        projects = frozenset(project_ids)
        index = cls()
        for item in urls:
            index.by_key.setdefault(item.key, []).append(item)
            host, parts = _segments(item.key)
            ministry_url = item.own and item.subject_id in projects
            if ministry_url and len(parts) == 3 and parts[0] == "projects" and parts[1] in RUBRICS:
                targets = index.by_slug.setdefault((host, parts[2]), [])
                targets.append((item.subject_id, parts[1]))
        return index

    def mappings(self, key: str) -> dict[str, bool]:
        """The subjects a row with archive ``key`` maps to, each with ``exact`` (an own
        URL of the subject has that key)."""
        found: dict[str, bool] = {}
        for item in self.by_key.get(key, ()):
            found[item.subject_id] = found.get(item.subject_id, False) or item.own
        host, parts = _segments(key)
        if not parts or parts[0] != "projects":
            return found
        if len(parts) == 2 and parts[1] not in NOT_SLUGS:
            slug, rubric = parts[1], None
        elif len(parts) == 3 and parts[1] in RUBRICS and parts[2] not in NOT_SLUGS:
            slug, rubric = parts[2], parts[1]
        else:
            return found
        for subject_id, own_rubric in self.by_slug.get((host, slug), ()):
            if subject_id not in found and own_rubric != rubric:
                found[subject_id] = False
        return found


def capture_of(row: CdxRow, snapshot: Snapshot) -> Capture:
    """The :class:`Capture` of a row read from ``snapshot`` (the CDX response)."""
    return Capture(
        timestamp=row.timestamp,
        original=row.original,
        archive_url=archive_capture_url(row.timestamp, row.original),
        cdx_row=row.values,
        request_url=snapshot.url or "",
        raw_snapshot_id=snapshot.raw_snapshot_id,
        fetched_at=snapshot.fetched_at,
    )


def earliest_by_key(pages: Iterable[tuple[CdxPage, Snapshot]]) -> dict[str, Capture]:
    """Per archive key the earliest capture over all rows and pages: the smallest
    timestamp of every CDX urlkey whose original URL has that key (the index's order is
    not relied on; ties keep the first row read)."""
    found: dict[str, Capture] = {}
    for page, snapshot in pages:
        for row in page.rows:
            key = archive_key(row.original)
            known = found.get(key)
            if known is None or row.timestamp < known.timestamp:
                found[key] = capture_of(row, snapshot)
    return found


# --------------------------------------------------------------------------------------
# The collector
# --------------------------------------------------------------------------------------


def prefix_url(prefix: str) -> str:
    """A prefix (without a scheme) as an ``https`` URL, for the robots.txt check. Raises
    :class:`UrlError`."""
    return parse_fetch_url(f"https://{prefix}").url


def _options(ctx: RunContext) -> tuple[list[str], int]:
    """The ``prefixes`` and ``page_limit`` options; a malformed option fails the run."""
    problem = "option prefixes must be a list of URL prefixes without a scheme"
    prefixes = ctx.options.get("prefixes", [])
    if not isinstance(prefixes, list) or not all(
        isinstance(item, str) and item.strip() and "://" not in item for item in prefixes
    ):
        raise FatalRunError(problem)
    for item in prefixes:
        try:
            prefix_url(item.strip())
        except UrlError as exc:
            raise FatalRunError(f"{problem}: {item!r}") from exc
    limit = ctx.options.get("page_limit", DEFAULT_PAGE_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_LIMIT:
        raise FatalRunError(f"option page_limit must be an integer from 1 to {MAX_PAGE_LIMIT}")
    return [item.strip() for item in prefixes], limit


@dataclass(frozen=True)
class SingleUrl:
    """One single-URL query: the archive key, the URL queried and the request."""

    key: str
    url: str
    query: str


def single_urls(urls: Iterable[SubjectUrl], prefixes: Sequence[str]) -> list[SingleUrl]:
    """The single-URL queries: one per archive key that no prefix covers (the smallest
    URL of the key is queried), sorted by archive key."""
    by_key: dict[str, str] = {}
    for item in urls:
        if covered(item.url, prefixes):
            continue
        if item.key not in by_key or item.url < by_key[item.key]:
            by_key[item.key] = item.url
    return [SingleUrl(key, url, url_query(url)) for key, url in sorted(by_key.items())]


@dataclass
class _Run:
    """The state of one run."""

    ctx: RunContext
    limit: int | None
    queries: int = 0
    answered: bool = False  # the first CDX request got a response
    complete: bool = True
    pages: list[tuple[CdxPage, Snapshot]] = field(default_factory=list)
    robots: dict[str, RobotsPolicy | None] = field(default_factory=dict)

    def stopped(self) -> bool:
        """A cancel was requested or ``limit`` queries were sent."""
        if self.ctx.cancelled():
            return True
        if self.limit is not None and self.queries >= self.limit:
            self.complete = False
            return True
        return False

    def allowed(self, url: str) -> bool:
        """Whether the newest stored robots.txt of the URL's host allows its path (no
        stored robots.txt with rules: allowed). A disallowed URL is counted."""
        try:
            target = parse_fetch_url(url)
        except UrlError:
            return False
        if target.robots_url not in self.robots:
            stored = self.ctx.latest_snapshot(target.robots_url)
            self.robots[target.robots_url] = (
                None if stored is None else policy_from_response(stored.http_status, stored.body)
            )
        policy = self.robots[target.robots_url]
        if (
            policy is None
            or policy.state not in ("rules", "allow_all")
            or policy.allows(target.url)
        ):
            return True
        self.ctx.count("robots_skipped")
        return False

    def fetch(self, query: str) -> CdxPage | None:
        """One CDX request and its parse; None when it failed or could not be parsed
        (the listing is then incomplete). The first request decides availability."""
        self.queries += 1
        self.ctx.count("cdx_queries")
        try:
            result = self.ctx.client.get(query, accept=ACCEPT_JSON)
        except ListingHostUnavailable as exc:
            raise FatalRunError(UNAVAILABLE) from exc
        if not self.answered:
            if not result.ok:
                raise FatalRunError(UNAVAILABLE)
            self.answered = True
            self.ctx.client.listing_done()  # later failures only make the run partial
        return self._parsed(query, result)

    def _parsed(self, query: str, result: FetchResult) -> CdxPage | None:
        if not result.ok:
            self.complete = False
            return None
        snapshot = result.snapshot
        if snapshot is None:
            self.complete = False
            self.ctx.message(
                "error", "parse_error", f"{query}: the response has no body", url=query
            )
            return None
        try:
            page = parse_cdx_json(snapshot)
        except ParseError as exc:
            self.complete = False
            self.ctx.message(
                "error",
                "parse_error",
                f"{query}: {exc}",
                url=query,
                snapshot_id=snapshot.raw_snapshot_id,
            )
            return None
        self.ctx.count("pages_parsed")
        for code, text in page.warnings:
            self.ctx.message("warning", code, text, url=query, snapshot_id=snapshot.raw_snapshot_id)
        self.pages.append((page, snapshot))
        return page


class Wayback:
    """The C5 collector (module docstring)."""

    NAME = NAME
    VERSION = 1
    DECLARATION: Mapping[str, TypeDeclaration] = {
        "event": TypeDeclaration(
            creates=True,
            writes=frozenset(
                {"subject_id", "event_type", "date", "date_basis", "date_text", "description_en"}
            ),
        )
    }
    MODES: tuple[str, ...] = ()
    PARAMS: frozenset[str] = frozenset({"limit"})

    def run(self, ctx: RunContext) -> None:
        """Query the prefixes, then the single URLs; map, record and observe."""
        prefixes, page_limit = _options(ctx)
        projects = ctx.live_records("project", ["ministry_urls", "official_urls"])
        services = ctx.live_records("service", ["urls"])
        urls = subject_urls(projects, services, ctx.client.config.exclude_hosts)
        index = SubjectIndex.of(urls, [str(project["id"]) for project in projects])
        run = _Run(ctx, ctx.params.get("limit"))
        for prefix in prefixes:
            self._prefix(run, prefix, page_limit)
        queried: dict[str, str] = {}  # archive key -> the URL queried
        for single in single_urls(urls, prefixes):
            if run.stopped():
                break
            if run.allowed(single.url) and run.fetch(single.query) is not None:
                queried[single.key] = single.url
        if ctx.cancelled():
            return
        found = earliest_by_key(run.pages)
        self._record(ctx, index, found)
        self._observe(ctx, index, found, queried)
        if run.complete and not ctx.cancelled():
            ctx.listing_complete()

    @staticmethod
    def _prefix(run: _Run, prefix: str, page_limit: int) -> None:
        """Every page of one prefix, following the resume keys."""
        if not run.allowed(prefix_url(prefix)):
            return
        seen: set[str] = set()
        resume: str | None = None
        while not run.stopped():
            page = run.fetch(prefix_query(prefix, page_limit, resume))
            if page is None or page.resume_key is None:
                return
            if page.resume_key in seen:
                run.complete = False
                run.ctx.message(
                    "error",
                    "parse_error",
                    f"prefix {prefix}: the resume key {page.resume_key!r} came back twice",
                )
                return
            seen.add(page.resume_key)
            resume = page.resume_key

    @staticmethod
    def _record(ctx: RunContext, index: SubjectIndex, found: Mapping[str, Capture]) -> None:
        """``first_archived`` per subject and archive key, each subject's captures
        earliest first (so that later captures of the same subject are redundant)."""
        work = [
            (subject_id, capture.timestamp, key, exact)
            for key, capture in found.items()
            for subject_id, exact in index.mappings(key).items()
        ]
        for subject_id, _, key, exact in sorted(work):
            if ctx.cancelled():
                return
            ctx.first_archived(subject_id, found[key], exact=exact)
            ctx.count("captures_mapped")

    @staticmethod
    def _observe(
        ctx: RunContext,
        index: SubjectIndex,
        found: Mapping[str, Capture],
        queried: Mapping[str, str],
    ) -> None:
        """One sighting per archive key read in the run, with or without captures."""
        for key in sorted(set(found) | set(queried)):
            if ctx.cancelled():
                return
            observation_key = f"url:{key}"
            if len(observation_key) > MAX_KEY_CHARS:
                ctx.message("warning", "invalid_value", f"archive key too long to observe: {key}")
                continue
            capture = found.get(key)
            ctx.observe(
                OBSERVED_TYPE,
                observation_key,
                url=capture.original if capture is not None else queried[key],
                details={
                    "earliest": capture.timestamp if capture is not None else None,
                    "original": capture.original if capture is not None else None,
                    "subject_ids": sorted(index.mappings(key)),
                },
            )


COLLECTOR = Wayback()
