"""The polite HTTP client (docs/COLLECTORS.md §4), built on httpx2.

One client per run (and one per manual fetch, fixture capture or source check); the
per-host throttle state is process-wide. In order, every request:

1. is normalised (§4.1) and refused without a request when its host is excluded, its path
   is a ``/cdn-cgi/`` trap, its host was blocked or throttled earlier, or the robots.txt of
   its host is unavailable (``fetch_log.outcome = refused``);
2. is checked against the robots.txt of its origin, fetched once per origin and run (§4.2);
   a disallowed URL is not requested (``robots_disallowed``);
3. waits until the host's interval has passed since its previous request ended and until
   any ``Retry-After`` of the host has run out (§4.3), interruptibly;
4. goes out with our User-Agent and no browser imitation (§4.4), conditional when an
   earlier live snapshot carries validators (§4.8), and streams its body with the size
   limit (§4.4); a watchdog holds the whole exchange, headers included, to the time limit
   and to a cancel request;
5. follows redirects itself, checking every hop as in 1-3 and never following a redirect
   to a challenge host (§4.5, §4.7);
6. is retried after 429, 502, 503, 504 and network errors with ``Retry-After`` or backoff
   (§4.6), never after a challenge page or an undecodable body; a ``Retry-After`` holds for
   the host and every client of the process, and a wait longer than ``max_wait_s``
   throttles the host for the run;
7. is checked for challenge pages and repeated 403/429 answers (§4.7);
8. is recorded: one ``fetch_log`` row per attempt and every final response body stored as a
   raw snapshot before the collector sees it (§4.9).

Persistence goes through a :class:`~mdt.collectors.fetchlog.FetchSink`; the throttle and
its clock are in :mod:`mdt.collectors.throttle`.
"""

from __future__ import annotations

import contextlib
import email.utils
import random
import re
import socket
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args
from urllib.parse import urlsplit

import httpx2
from sqlalchemy.orm import Session

from mdt import __version__
from mdt.collectors.base import FatalRunError, Snapshot
from mdt.collectors.errors import CollectorUnavailableError
from mdt.collectors.fetchlog import DatabaseSink, FetchEntry, FetchSink
from mdt.collectors.replay import REPLAY_EXTENSION, ReplayMiss, ReplayTransport
from mdt.collectors.robots import PRODUCT_TOKEN, RobotsPolicy, policy_from_response
from mdt.collectors.sources import MANUAL, CollectorConfig, load_sources
from mdt.collectors.store import SnapshotMeta, SnapshotRecord, SnapshotStore
from mdt.collectors.throttle import (
    PROCESS_THROTTLE,
    Clock,
    HostDeferred,
    HostThrottle,
    SystemClock,
)
from mdt.collectors.urls import FetchUrl, UrlError, parse_fetch_url, resolve_location
from mdt.config import Settings, contact_email_problem
from mdt.domain.clock import utc_now

DEFAULT_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ACCEPT_JSON = "application/json"
ROBOTS_ACCEPT = "*/*"  # osvita.diia.gov.ua answered Accept: text/plain with HTTP 406
ACCEPT_ENCODING = "gzip, deflate"
RETRY_STATUSES = frozenset({429, 502, 503, 504})
REQUEST_TOTAL_S = 300.0
ROBOTS_MAX_REDIRECTS = 5
TRAP_PREFIX = "/cdn-cgi/"
BLOCK_STREAK = 3
MANUAL_FETCH_BUDGET_S = 60.0
_SIGNATURE_BYTES = 65_536
_MAX_ERROR_CHARS = 500
_BUDGET_TEXT = "time budget of the manual fetch exhausted"
_DEFERRED_TEXT = "host throttled: it asked for a longer wait (Retry-After)"
#: Reasons of an unavailable robots policy that mean "throttled", not "robots.txt
#: unavailable": no ``robots_unavailable`` message, URLs refused as ``throttled``.
_THROTTLED_REASONS = frozenset({_BUDGET_TEXT, _DEFERRED_TEXT})
#: Failures without a usable response that retrying cannot change (§4.6: not network errors).
_PERMANENT_ERRORS = (httpx2.DecodingError, httpx2.LocalProtocolError, httpx2.UnsupportedProtocol)
#: How often the watchdog of an exchange looks at the cancel flag (seconds).
_WATCH_POLL_S = 0.2

FetchOutcome = Literal[
    "ok",
    "not_modified",
    "redirect",
    "http_error",
    "network_error",
    "robots_disallowed",
    "blocked",
    "too_large",
    "refused",
]
FETCH_OUTCOMES: tuple[str, ...] = get_args(FetchOutcome)
#: Why a URL was refused (``refused``) or a request given up; maps to the reasons of
#: ``502 fetch_failed`` through :attr:`FetchResult.reason`.
Refusal = Literal[
    "excluded", "trap", "blocked", "throttled", "robots_unavailable", "no_fixture", "invalid_url"
]
_REFUSAL_TEXT: dict[str, str] = {
    "excluded": "excluded host",
    "trap": "trap path /cdn-cgi/",
    "blocked": "host blocked earlier in this run",
    "throttled": "host throttled earlier in this run",
    "robots_unavailable": "robots.txt unavailable",
    "no_fixture": "no fixture",
    "invalid_url": "invalid URL",
}


class RunCancelled(Exception):
    """A cancel was requested; the run stops before its next request or item."""


class ListingHostUnavailable(FatalRunError):
    """The listing host was blocked, throttled or without robots.txt before the listing
    was complete: the run fails (docs/COLLECTORS.md §4.7)."""


# --------------------------------------------------------------------------------------
# Results and helpers
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    """The outcome of one ``get``/``head`` (after redirects and retries)."""

    url: str
    outcome: FetchOutcome
    status: int | None = None
    final_url: str | None = None
    redirects: tuple[str, ...] = ()
    snapshot: Snapshot | None = None
    error: str | None = None
    retry_after_s: float | None = None
    signature: str | None = None
    refusal: Refusal | None = None
    throttled: bool = False
    out_of_budget: bool = False
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        """A usable response (``ok`` or ``not_modified``)."""
        return self.outcome in ("ok", "not_modified")

    @property
    def reason(self) -> str:
        """The ``fetch_failed`` reason of a failed manual fetch (docs/API.md §7.8); a fetch
        out of time is ``throttled`` whatever its last outcome."""
        if self.out_of_budget:
            return "throttled"
        if self.outcome in ("robots_disallowed", "too_large", "network_error", "blocked"):
            return self.outcome
        if self.throttled or self.refusal == "throttled":
            return "throttled"
        if self.refusal in ("blocked", "excluded"):
            return "blocked"
        if self.refusal == "robots_unavailable":
            return "robots_unavailable"
        return "http_error"


def user_agent(contact_email: str | None, project_url: str = "") -> str:
    """``MDT-Portfolio-Research/<version> (+<PROJECT_URL>; mailto:<CONTACT_EMAIL>)``; without
    ``PROJECT_URL`` the part ``+<PROJECT_URL>; `` is left out, and without an address (replay
    mode only) the comment is ``(replay)``."""
    parts = []
    if project_url:
        parts.append(f"+{project_url}")
    if contact_email:
        parts.append(f"mailto:{contact_email.strip()}")
    return f"{PRODUCT_TOKEN}/{__version__} ({'; '.join(parts) or 'replay'})"


_TITLE_RE = re.compile(r"<title[^>]*>\s*Just a moment\.\.\.\s*</title>", re.IGNORECASE)
_MANAGED_RE = re.compile(r"cType\s*:\s*['\"]managed['\"]")
_RADWARE_TITLE_RE = re.compile(r"<title[^>]*>[^<]*(?:Radware|ShieldSquare)[^<]*</title>", re.I)
#: The challenge host of the Radware (ShieldSquare) bot manager on www.kmu.gov.ua: its
#: pages configure ``validate.perfdrive.com`` as the captcha host (docs/SOURCES.md S4b).
CHALLENGE_DOMAINS = ("perfdrive.com",)


def challenge_host(url: str) -> str | None:
    """The host of ``url`` if it is a bot manager's challenge host (or a subdomain)."""
    host = (urlsplit(url).hostname or "").rstrip(".").lower()
    for domain in CHALLENGE_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return host
    return None


def block_signature(
    status: int | None, headers: Mapping[str, str], body: bytes | None
) -> str | None:
    """The challenge or block signature a response matches, if any (§4.7): Cloudflare
    ("Just a moment..." title, ``cType: 'managed'``, ``cf-mitigated: challenge``), Akamai
    (HTTP 403 with an "Access Denied" page) and Radware/ShieldSquare (a redirect to its
    challenge host ``*.perfdrive.com``, or a page titled with the vendor's name). A body that
    only mentions the challenge host (every page of the site configures it) is no
    challenge."""
    lowered = {name.lower(): value for name, value in headers.items()}
    if lowered.get("cf-mitigated", "").strip().lower() == "challenge":
        return "cloudflare: cf-mitigated: challenge"
    location = lowered.get("location", "")
    if status is not None and 300 <= status < 400 and location:
        host = challenge_host(location)
        if host is not None:
            return f"radware: redirect to {host}"
    text = (body or b"")[:_SIGNATURE_BYTES].decode("utf-8", errors="replace")
    if _TITLE_RE.search(text):
        return "cloudflare: Just a moment..."
    if _MANAGED_RE.search(text):
        return "cloudflare: managed challenge"
    if status == 403 and "Access Denied" in text:
        return "akamai: Access Denied"
    if _RADWARE_TITLE_RE.search(text):
        return "radware: challenge page"
    return None


def parse_retry_after(value: str | None, now: float) -> float | None:
    """``Retry-After`` in seconds (a number of seconds or an HTTP date), or None."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        moment = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return None
    return max(0.0, moment.timestamp() - now)


def _short(text: str) -> str:
    return text if len(text) <= _MAX_ERROR_CHARS else text[: _MAX_ERROR_CHARS - 1] + "…"


class _TooLarge(Exception):
    def __init__(self, size: int) -> None:
        super().__init__(f"body larger than the limit ({size} bytes or more)")
        self.size = size


class _Budget(Exception):
    """A wait does not fit the remaining time budget of a manual fetch."""


class _Undecodable(Exception):
    """A response whose body cannot be decoded (e.g. labelled ``gzip`` but not gzip): the
    server answered, so this is an ``http_error`` with its status, never retried."""

    def __init__(self, sent: _Sent, error: str) -> None:
        super().__init__(error)
        self.sent = sent
        self.error = error


class _Watchdog:
    """Guards one HTTP exchange, status line and headers included (§4.4, §4.6, §6.3): when
    its time limit passes or a cancel is requested, it shuts down the client's sockets, so
    a server that trickles bytes (each read within the read timeout) cannot hold the
    request open. The exchange then fails, and :meth:`check` turns that failure into a
    timeout or a cancellation."""

    def __init__(
        self,
        seconds: float,
        cancel: threading.Event | None,
        sockets: Callable[[], list[socket.socket]],
    ) -> None:
        self.seconds = seconds
        self.cancel = cancel
        self.sockets = sockets
        self.fired: Literal["expired", "cancelled"] | None = None
        self._done = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._watch, name="mdt-fetch-watchdog", daemon=True)

    def __enter__(self) -> _Watchdog:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        with self._lock:
            self._done.set()
        self._thread.join()

    def _watch(self) -> None:
        end = time.monotonic() + self.seconds
        while True:
            remaining = end - time.monotonic()
            if self._done.wait(max(0.0, min(_WATCH_POLL_S, remaining))):
                return
            if self.cancel is not None and self.cancel.is_set():
                self._fire("cancelled")
                return
            if time.monotonic() >= end:
                self._fire("expired")
                return

    def _fire(self, reason: Literal["expired", "cancelled"]) -> None:
        with self._lock:
            if self._done.is_set():
                return
            self.fired = reason
            for sock in self.sockets():
                # The plain socket call, also for TLS sockets (no SSL state changes).
                with contextlib.suppress(OSError):
                    socket.socket.shutdown(sock, socket.SHUT_RDWR)

    def check(self) -> None:
        """Raise the reason the exchange was interrupted, if it was."""
        if self.fired == "cancelled":
            raise RunCancelled()
        if self.fired == "expired":
            raise httpx2.ReadTimeout(f"the request took longer than {self.seconds:g} s")


@dataclass
class _Sent:
    status: int
    headers: dict[str, str]
    body: bytes | None
    replay: Mapping[str, Any] | None
    duration_ms: int


@dataclass
class _Final:
    """The final response of one hop, or how the hop ended without one."""

    outcome: FetchOutcome | None  # None: a response that the caller classifies
    sent: _Sent | None = None
    attempt: int = 1
    at: str = ""
    error: str | None = None
    retry_after_s: float | None = None
    refusal: Refusal | None = None
    throttled: bool = False  # a wait above max_wait_s: the host is throttled for the run
    out_of_budget: bool = False  # a wait that does not fit a manual fetch's budget
    duration_ms: int | None = None  # of an attempt without a response


# --------------------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------------------


class PoliteHttpClient:
    """Politeness, recording and block detection around httpx2 (module docstring)."""

    def __init__(
        self,
        config: CollectorConfig,
        sink: FetchSink,
        *,
        user_agent: str,
        transport: httpx2.BaseTransport | None,
        source_id: str,
        run_id: str | None = None,
        replay: bool = False,
        clock: Clock | None = None,
        throttle: HostThrottle | None = None,
        cancel: threading.Event | None = None,
        budget_s: float | None = None,
        rng: random.Random | None = None,
        listing_host: Literal["first"] | None = "first",
    ) -> None:
        self.config = config
        self.settings = config.settings
        self.sink = sink
        self.user_agent = user_agent
        self.source_id = source_id
        self.run_id = run_id
        self.replay = replay
        self.clock: Clock = clock or SystemClock()
        self.throttle = throttle or PROCESS_THROTTLE
        self.cancel = cancel
        self.rng = rng or random.Random()
        self.deadline = None if budget_s is None else self.clock.monotonic() + budget_s
        self.listing_host: str | None = None
        self._listing_mode = listing_host
        self._listing_done = False
        self._robots: dict[str, RobotsPolicy] = {}
        self._intervals: dict[str, float] = {}
        self._blocked: dict[str, str] = {}
        self._throttled: dict[str, str] = {}
        self._unavailable_reported: set[str] = set()
        self._streaks: dict[str, int] = {}
        self._sockets: list[socket.socket] = []
        self._sockets_lock = threading.Lock()
        # transport None: the network, honouring the environment's proxy settings.
        self._http = httpx2.Client(
            transport=transport,
            follow_redirects=False,
            timeout=httpx2.Timeout(
                connect=self.settings.timeout_connect_s,
                read=self.settings.timeout_read_s,
                write=self.settings.timeout_read_s,
                pool=self.settings.timeout_connect_s,
            ),
        )

    # ----------------------------------------------------------------------------------
    # Public interface
    # ----------------------------------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        accept: str | None = None,
        conditional: bool = True,
        via_for: Callable[[str], str] | None = None,
    ) -> FetchResult:
        """GET ``url`` politely (module docstring). ``via_for`` maps the final URL to the
        snapshot's ``via`` (manual fetches of archived copies: ``wayback:<timestamp>``)."""
        return self._request("GET", url, accept or DEFAULT_ACCEPT, conditional, via_for)

    def head(self, url: str, *, accept: str | None = None) -> FetchResult:
        """HEAD ``url`` (only where a collector needs headers alone)."""
        return self._request("HEAD", url, accept or DEFAULT_ACCEPT, False, None)

    def robots_policy(self, url: str) -> RobotsPolicy:
        """The robots.txt policy of the URL's origin (fetched once per run)."""
        return self._policy(parse_fetch_url(url))

    def set_listing_host(self, host: str | None) -> None:
        """Name the collector's listing host (None: no listing host, e.g. C2)."""
        self._listing_mode = None
        self.listing_host = host

    def listing_done(self) -> None:
        """The listing is complete: later failures of its host only make the run partial."""
        self._listing_done = True

    def close(self) -> None:
        """Close the connections (cookies are dropped with the client)."""
        self._http.close()

    def __enter__(self) -> PoliteHttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ----------------------------------------------------------------------------------
    # Requests
    # ----------------------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        accept: str,
        conditional: bool,
        via_for: Callable[[str], str] | None,
    ) -> FetchResult:
        self._check_cancelled()
        started = self.clock.monotonic()
        try:
            target = parse_fetch_url(url)
        except UrlError as exc:
            entry = self._log(method, url.strip(), "", "content", "refused", f"invalid URL: {exc}")
            self._content_failure(entry, None)
            return FetchResult(url=url, outcome="refused", error=entry.error, refusal="invalid_url")
        if self._listing_mode == "first" and self.listing_host is None:
            self.listing_host = target.host
        base = None
        if conditional and method == "GET" and not self.replay:
            base = self.sink.conditional_base(target.url)
            if base is not None and (
                base.final_url not in (None, base.url)
                or not ({"etag", "last-modified"} & set(base.headers))
            ):
                base = None
        hops: list[str] = []
        current = target
        while True:
            stop = self._admit(method, current, purpose="content")
            if stop is not None:
                return self._finish_refusal(target, current, stop, hops, started)
            validators = self._validators(base) if base is not None and not hops else {}
            final = self._attempts(method, current, accept, "content", validators)
            if (
                final.outcome is None
                and final.sent is not None
                and self._is_redirect(final.sent)
                # a redirect to a bot manager's challenge host blocks this host (§4.7)
                and block_signature(final.sent.status, final.sent.headers, None) is None
            ):
                next_url = resolve_location(current.url, final.sent.headers["location"])
                if len(hops) >= self.settings.max_redirects:
                    return self._too_many_redirects(method, target, current, final, hops, started)
                self._record(method, current, "content", final, "redirect")
                hops.append(f"{final.sent.status} {next_url}")
                try:
                    current = parse_fetch_url(next_url)
                except UrlError as exc:
                    return self._invalid_hop(method, target, next_url, hops, str(exc), started)
                continue
            return self._finish(method, target, current, final, hops, base, via_for, started)

    def _admit(self, method: str, target: FetchUrl, *, purpose: str) -> FetchResult | None:
        """Refusal and robots checks before a request (§4.1, §4.2); None if it may go."""
        refusal = self._refusal(target)
        if refusal is None:
            policy = self._policy(target)
            if policy.state == "blocked":
                refusal = "blocked"
            elif policy.state == "unavailable":
                throttled = policy.reason in _THROTTLED_REASONS
                refusal = "throttled" if throttled else "robots_unavailable"
            elif target.host in self._throttled:
                refusal = "throttled"
            elif not policy.allows(target.url):
                entry = self._log(
                    method,
                    target.url,
                    target.host,
                    purpose,
                    "robots_disallowed",
                    "disallowed by robots.txt",
                )
                self.sink.count("robots_disallowed")
                return FetchResult(url=target.url, outcome="robots_disallowed", error=entry.error)
        if refusal is None:
            return None
        entry = self._log(
            method, target.url, target.host, purpose, "refused", _REFUSAL_TEXT[refusal]
        )
        if purpose == "content":
            self._content_failure(entry, None)
            if refusal in ("blocked", "throttled", "robots_unavailable"):
                reason = {"robots_unavailable": "robots.txt unavailable"}.get(refusal, refusal)
                self._fail_listing(target.host, reason)
        return FetchResult(url=target.url, outcome="refused", error=entry.error, refusal=refusal)

    def _refusal(self, target: FetchUrl) -> Refusal | None:
        if target.host in self.config.exclude_hosts:
            return "excluded"
        if target.path.startswith(TRAP_PREFIX):
            return "trap"
        if target.host in self._blocked:
            return "blocked"
        if target.host in self._throttled:
            return "throttled"
        return None

    def _attempts(
        self,
        method: str,
        target: FetchUrl,
        accept: str,
        purpose: str,
        validators: Mapping[str, str],
    ) -> _Final:
        """One URL with its retries (§4.6); returns its final response or failure.
        robots.txt is not retried after 401, 403 or 429, which block the host (§4.2)."""
        retry_statuses = RETRY_STATUSES if purpose == "content" else RETRY_STATUSES - {429}
        attempt = 0
        while True:
            attempt += 1
            self._check_cancelled()
            at = utc_now()
            started = self.clock.monotonic()
            try:
                with self.throttle.turn(
                    target.host,
                    self._interval(target.host),
                    self.clock,
                    self._wait,
                    self._check_cancelled,
                    max_wait=self.settings.max_wait_s,
                ):
                    sent = self._send(method, target, accept, validators)
            except HostDeferred as exc:  # an earlier Retry-After of the host, not waited
                return _Final(
                    "refused",
                    attempt=attempt,
                    at=at,
                    error=f"host throttled: it asked for a wait of {exc.seconds:.0f} s",
                    retry_after_s=exc.seconds,
                    refusal="throttled",
                    throttled=True,
                )
            except ReplayMiss:
                return _Final(
                    "refused",
                    attempt=attempt,
                    at=at,
                    error=_REFUSAL_TEXT["no_fixture"],
                    refusal="no_fixture",
                )
            except _Budget:
                return _Final(
                    "refused", attempt=attempt, at=at, error=_BUDGET_TEXT, out_of_budget=True
                )
            except _TooLarge as exc:
                self.sink.count("requests")
                return _Final("too_large", attempt=attempt, at=at, error=_short(str(exc)))
            except _Undecodable as exc:
                self.sink.count("requests")
                return _Final("http_error", exc.sent, attempt, at, error=exc.error)
            except _PERMANENT_ERRORS as exc:
                self.sink.count("requests")
                error = _short(f"{type(exc).__name__}: {exc}".rstrip(": "))
                return _Final("http_error", attempt=attempt, at=at, error=error)
            except httpx2.RequestError as exc:
                self.sink.count("requests")
                error = _short(f"{type(exc).__name__}: {exc}".rstrip(": "))
                duration = int((self.clock.monotonic() - started) * 1000)
                wait = self._backoff(attempt)
                if attempt <= self.settings.retries and wait <= self.settings.max_wait_s:
                    if not self._fits(wait):
                        return _Final(
                            "network_error",
                            attempt=attempt,
                            at=at,
                            error=error,
                            out_of_budget=True,
                        )
                    failed = _Final(None, attempt=attempt, at=at, error=error, duration_ms=duration)
                    self._record(method, target, purpose, failed, "network_error")
                    self._wait(wait)
                    continue
                # A manual fetch cut off by its budget is out of time ("throttled").
                return _Final(
                    "network_error",
                    attempt=attempt,
                    at=at,
                    error=error,
                    out_of_budget=not self._fits(0),
                )
            self.sink.count("requests")
            self.sink.count("bytes", len(sent.body or b""))
            retry_after = parse_retry_after(sent.headers.get("retry-after"), self.clock.time())
            # A Retry-After on 429 or 5xx holds for the host and every client of the process,
            # also after the last attempt (RFC 9110 §10.2.3).
            deferred = retry_after if sent.status == 429 or sent.status >= 500 else None
            if deferred is not None:
                self.throttle.defer(target.host, deferred, self.clock)
            # A challenge page is final whatever its status: no retries (§4.2, §4.7).
            challenge = block_signature(sent.status, sent.headers, sent.body) is not None
            if sent.status in retry_statuses and attempt <= self.settings.retries and not challenge:
                wait = retry_after if retry_after is not None else self._backoff(attempt)
                if wait > self.settings.max_wait_s:
                    return _Final(None, sent, attempt, at, retry_after_s=wait, throttled=True)
                if not self._fits(wait):
                    return _Final(None, sent, attempt, at, retry_after_s=wait, out_of_budget=True)
                retried = _Final(None, sent, attempt, at, retry_after_s=retry_after)
                self._record(
                    method,
                    target,
                    purpose,
                    retried,
                    "http_error",
                    error=f"HTTP {sent.status}, retried",
                )
                self._wait(wait)
                continue
            too_long = deferred is not None and deferred > self.settings.max_wait_s
            return _Final(None, sent, attempt, at, retry_after_s=retry_after, throttled=too_long)

    def _send(
        self, method: str, target: FetchUrl, accept: str, validators: Mapping[str, str]
    ) -> _Sent:
        """One HTTP exchange with the size and total time limits (300 s per request, the
        remaining budget of a manual fetch). The limit and a cancel request also cover the
        status line and headers: a watchdog interrupts the exchange (§4.4, §4.6, §6.3)."""
        started = self.clock.monotonic()
        limit = REQUEST_TOTAL_S
        if self.deadline is not None:
            limit = min(limit, max(0.0, self.deadline - started))
        headers = {
            "User-Agent": self.user_agent,
            "Accept": accept,
            "Accept-Encoding": ACCEPT_ENCODING,
            **validators,
        }
        request = self._http.build_request(
            method, target.url, headers=headers, extensions={"trace": self._trace}
        )
        with _Watchdog(limit, self.cancel, self._open_sockets) as watchdog:
            try:
                return self._exchange(method, request, started, limit)
            except httpx2.RequestError:
                watchdog.check()
                raise

    def _exchange(
        self, method: str, request: httpx2.Request, started: float, limit: float
    ) -> _Sent:
        response = self._http.send(request, stream=True)
        try:
            status = response.status_code
            response_headers = {name.lower(): value for name, value in response.headers.items()}
            replay = response.extensions.get(REPLAY_EXTENSION)
            body: bytes | None = None
            if method == "GET" and not self._is_redirect_status(status, response_headers):
                declared = response_headers.get("content-length", "")
                if declared.isdigit() and int(declared) > self.settings.max_bytes:
                    raise _TooLarge(int(declared))
                chunks: list[bytes] = []
                total = 0
                try:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self.settings.max_bytes:
                            raise _TooLarge(total)
                        if self.clock.monotonic() - started > limit:
                            raise httpx2.ReadTimeout(f"the request took longer than {limit:g} s")
                        chunks.append(chunk)
                except httpx2.DecodingError as exc:
                    duration = int((self.clock.monotonic() - started) * 1000)
                    sent = _Sent(status, response_headers, None, replay, duration)
                    raise _Undecodable(sent, _short(f"{type(exc).__name__}: {exc}")) from exc
                body = b"".join(chunks)
            duration = int((self.clock.monotonic() - started) * 1000)
            return _Sent(status, response_headers, body, replay, duration)
        finally:
            response.close()

    def _trace(self, event: str, info: Mapping[str, Any]) -> None:
        """httpcore's ``trace`` extension: remember the socket of every connection the
        client opens, so that the watchdog of an exchange can interrupt it."""
        if not event.endswith(
            (".connect_tcp.complete", ".connect_unix_socket.complete", ".start_tls.complete")
        ):
            return
        extra = getattr(info.get("return_value"), "get_extra_info", None)
        sock = extra("socket") if callable(extra) else None
        if isinstance(sock, socket.socket):
            with self._sockets_lock:
                self._sockets = [known for known in self._sockets if known.fileno() != -1]
                self._sockets.append(sock)

    def _open_sockets(self) -> list[socket.socket]:
        with self._sockets_lock:
            return [sock for sock in self._sockets if sock.fileno() != -1]

    def _finish(
        self,
        method: str,
        target: FetchUrl,
        current: FetchUrl,
        final: _Final,
        hops: list[str],
        base: SnapshotRecord | None,
        via_for: Callable[[str], str] | None,
        started: float,
    ) -> FetchResult:
        """Classify, store and record the final response of a request."""
        duration = int((self.clock.monotonic() - started) * 1000)
        common: dict[str, Any] = {
            "url": target.url,
            "final_url": current.url,
            "redirects": tuple(hops),
            "duration_ms": duration,
        }
        if final.outcome is not None:  # no usable response: too_large, network_error,
            # refused, http_error (an undecodable body)
            entry = self._record(method, current, "content", final, final.outcome)
            self._content_failure(entry, None)
            if final.throttled:
                self._throttle(current.host, f"a wait of {final.retry_after_s:.0f} s", current.url)
            return FetchResult(
                outcome=final.outcome,
                status=final.sent.status if final.sent else None,
                error=final.error,
                retry_after_s=final.retry_after_s,
                refusal=final.refusal,
                throttled=final.throttled,
                out_of_budget=final.out_of_budget,
                **common,
            )
        sent = final.sent
        assert sent is not None
        if sent.status == 304 and base is not None:
            entry = self._record(
                method, current, "content", final, "not_modified", raw_snapshot_id=base.id
            )
            self.sink.count("not_modified")
            return FetchResult(
                outcome="not_modified", status=304, snapshot=self.sink.open(base.id), **common
            )
        signature = block_signature(sent.status, sent.headers, sent.body)
        if signature is None and sent.status in (403, 429):
            streak = self._streaks.get(current.host, 0) + 1
            self._streaks[current.host] = streak
            if streak >= BLOCK_STREAK:
                signature = f"{BLOCK_STREAK} consecutive responses with HTTP 403 or 429"
        else:
            self._streaks[current.host] = 0
        outcome: FetchOutcome
        if signature is not None:
            outcome = "blocked"
        elif 200 <= sent.status < 300:
            outcome = "ok"
        else:
            outcome = "http_error"
        snapshot = None
        if sent.body:
            snapshot = self._store(target, current, sent, hops, via_for)
        entry = self._record(
            method,
            current,
            "content",
            final,
            outcome,
            raw_snapshot_id=snapshot.raw_snapshot_id if snapshot else None,
            error=signature or (f"HTTP {sent.status}" if outcome == "http_error" else None),
        )
        if outcome == "http_error":
            self._content_failure(entry, snapshot)
        if final.throttled:
            self._throttle(current.host, f"a wait of {final.retry_after_s:g} s", current.url)
        if outcome == "blocked":
            assert signature is not None
            self._block(current.host, current.url, sent.status, signature, snapshot)
        return FetchResult(
            outcome=outcome,
            status=sent.status,
            snapshot=snapshot,
            error=entry.error,
            retry_after_s=final.retry_after_s,
            signature=signature,
            throttled=final.throttled,
            out_of_budget=final.out_of_budget,
            **common,
        )

    def _store(
        self,
        target: FetchUrl,
        current: FetchUrl,
        sent: _Sent,
        hops: list[str],
        via_for: Callable[[str], str] | None,
    ) -> Snapshot:
        via = "replay" if sent.replay is not None else "live"
        fetched_at = None
        if sent.replay is not None:
            fetched_at = sent.replay.get("retrieved_at")
        elif via_for is not None:
            via = via_for(current.url)
        snapshot = self.sink.store(
            sent.body or b"",
            SnapshotMeta(
                source_id=self.source_id,
                via=via,
                run_id=self.run_id,
                url=target.url,
                final_url=current.url,
                redirects=tuple(hops),
                http_status=sent.status,
                fetched_at=fetched_at,
                headers=sent.headers,
            ),
        )
        self.sink.count("snapshots")
        return snapshot

    def _finish_refusal(
        self,
        target: FetchUrl,
        current: FetchUrl,
        stop: FetchResult,
        hops: list[str],
        started: float,
    ) -> FetchResult:
        return FetchResult(
            url=target.url,
            outcome=stop.outcome,
            final_url=current.url,
            redirects=tuple(hops),
            error=stop.error,
            refusal=stop.refusal,
            duration_ms=int((self.clock.monotonic() - started) * 1000),
        )

    def _too_many_redirects(
        self,
        method: str,
        target: FetchUrl,
        current: FetchUrl,
        final: _Final,
        hops: list[str],
        started: float,
    ) -> FetchResult:
        error = f"more than {self.settings.max_redirects} redirects"
        entry = self._record(method, current, "content", final, "http_error", error=error)
        self._content_failure(entry, None)
        return FetchResult(
            url=target.url,
            outcome="http_error",
            status=final.sent.status if final.sent else None,
            final_url=current.url,
            redirects=tuple(hops),
            error=error,
            duration_ms=int((self.clock.monotonic() - started) * 1000),
        )

    def _invalid_hop(
        self,
        method: str,
        target: FetchUrl,
        next_url: str,
        hops: list[str],
        problem: str,
        started: float,
    ) -> FetchResult:
        error = f"invalid redirect target: {problem}"
        entry = self._log(method, next_url, "", "content", "refused", error)
        self._content_failure(entry, None)
        return FetchResult(
            url=target.url,
            outcome="refused",
            final_url=next_url,
            redirects=tuple(hops),
            error=entry.error,
            refusal="invalid_url",
            duration_ms=int((self.clock.monotonic() - started) * 1000),
        )

    # ----------------------------------------------------------------------------------
    # robots.txt (§4.2)
    # ----------------------------------------------------------------------------------

    def _policy(self, target: FetchUrl) -> RobotsPolicy:
        cached = self._robots.get(target.origin)
        if cached is not None:
            return cached
        policy = self._fetch_robots(target)
        self._robots[target.origin] = policy
        host = target.host
        if policy.state == "unavailable" and policy.reason not in _THROTTLED_REASONS:
            if host not in self._unavailable_reported:
                self._unavailable_reported.add(host)
                self.sink.message(
                    "error",
                    "robots_unavailable",
                    f"robots.txt of {host} is unavailable ({policy.reason}); nothing is "
                    "requested from the host in this run",
                    url=target.robots_url,
                    snapshot_id=policy.snapshot_id,
                    details={"host": host, "status": policy.status},
                )
        elif policy.state in ("rules", "allow_all"):
            interval = max(
                self.config.min_interval(host),
                policy.crawl_delay() or 0.0,
                policy.request_interval() or 0.0,
            )
            self._intervals[host] = interval
            if interval > self.settings.max_wait_s:
                self._throttle(host, f"robots.txt asks for {interval:g} s", target.robots_url)
        return policy

    def _fetch_robots(self, target: FetchUrl) -> RobotsPolicy:
        current = parse_fetch_url(target.robots_url)
        hops: list[str] = []
        while True:
            if current.host in self.config.exclude_hosts or current.host in self._blocked:
                return policy_from_response(None, None)
            final = self._attempts("GET", current, ROBOTS_ACCEPT, "robots", {})
            if final.out_of_budget:  # a manual fetch ran out of time: throttled
                self._record("GET", current, "robots", final, final.outcome or "http_error")
                return RobotsPolicy("unavailable", _BUDGET_TEXT)
            if final.outcome is not None and final.throttled:  # an earlier Retry-After
                self._record("GET", current, "robots", final, final.outcome)
                reason = f"a wait of {final.retry_after_s:.0f} s"
                self._throttle(target.host, reason, target.robots_url)
                return RobotsPolicy("unavailable", _DEFERRED_TEXT)
            if final.outcome is not None:
                self._record("GET", current, "robots", final, final.outcome)
                return policy_from_response(None, None)
            sent = final.sent
            assert sent is not None
            challenge = block_signature(sent.status, sent.headers, None) is not None
            if not challenge and self._is_redirect(sent) and len(hops) < ROBOTS_MAX_REDIRECTS:
                next_url = resolve_location(current.url, sent.headers["location"])
                self._record("GET", current, "robots", final, "redirect")
                hops.append(f"{sent.status} {next_url}")
                try:
                    current = parse_fetch_url(next_url)
                except UrlError:
                    return policy_from_response(None, None)
                continue
            signature = block_signature(sent.status, sent.headers, sent.body)
            snapshot = None
            if sent.body:
                snapshot = self._store(
                    parse_fetch_url(target.robots_url), current, sent, hops, None
                )
            snapshot_id = snapshot.raw_snapshot_id if snapshot else None
            redirect_status = None if not self._is_redirect(sent) else sent.status
            policy = policy_from_response(
                None if redirect_status else sent.status,
                sent.body,
                challenge=signature is not None,
                snapshot_id=snapshot_id,
            )
            # A 404 or 410 is a normal answer ("no robots.txt"), so it is logged as ok.
            outcome: FetchOutcome = "ok" if policy.state in ("rules", "allow_all") else "http_error"
            if policy.state == "blocked":
                outcome = "blocked"
            self._record(
                "GET",
                current,
                "robots",
                final,
                outcome,
                raw_snapshot_id=snapshot_id,
                error=signature,
            )
            if policy.state == "blocked":
                self._block(
                    target.host, current.url, sent.status, signature or policy.reason, snapshot
                )
            return policy

    # ----------------------------------------------------------------------------------
    # Host states (§4.6, §4.7)
    # ----------------------------------------------------------------------------------

    def _block(
        self, host: str, url: str, status: int | None, signature: str, snapshot: Snapshot | None
    ) -> None:
        if host not in self._blocked:
            self._blocked[host] = signature
            self.sink.message(
                "error",
                "blocked",
                f"{host} blocked the client ({signature}); no further request to it in this run",
                url=url,
                snapshot_id=snapshot.raw_snapshot_id if snapshot else None,
                details={"host": host, "url": url, "status": status, "signature": signature},
            )
        self._fail_listing(host, "blocked")

    def _throttle(self, host: str, reason: str, url: str) -> None:
        if host not in self._throttled:
            self._throttled[host] = reason
            self.sink.message(
                "warning",
                "throttled",
                f"{host} throttled ({reason}, more than {self.settings.max_wait_s:g} s); "
                "no further request to it in this run",
                url=url,
                details={"host": host, "reason": reason},
            )
        self._fail_listing(host, "throttled")

    def _fail_listing(self, host: str, reason: str) -> None:
        if host == self.listing_host and not self._listing_done:
            raise ListingHostUnavailable(f"{host}: {reason}")

    def _content_failure(self, entry: FetchEntry, snapshot: Snapshot | None) -> None:
        """The error message of a content request that ended as ``http_error``,
        ``network_error``, ``too_large`` or ``refused`` (docs/COLLECTORS.md §6.6)."""
        self.sink.message(
            "error",
            "http_error",
            f"{entry.outcome}: {entry.url}" + (f" ({entry.error})" if entry.error else ""),
            url=entry.url or None,
            snapshot_id=snapshot.raw_snapshot_id if snapshot else entry.raw_snapshot_id,
            details={"outcome": entry.outcome, "status": entry.status, "error": entry.error},
        )

    # ----------------------------------------------------------------------------------
    # Small helpers
    # ----------------------------------------------------------------------------------

    def _record(
        self,
        method: str,
        target: FetchUrl,
        purpose: str,
        final: _Final,
        outcome: FetchOutcome,
        *,
        raw_snapshot_id: str | None = None,
        error: str | None = None,
    ) -> FetchEntry:
        sent = final.sent
        entry = FetchEntry(
            at=final.at or utc_now(),
            method=method,
            url=target.url,
            host=target.host,
            purpose=purpose,
            outcome=outcome,
            attempt=final.attempt,
            status=sent.status if sent else None,
            bytes=len(sent.body) if sent and sent.body is not None else None,
            duration_ms=sent.duration_ms if sent else final.duration_ms,
            raw_snapshot_id=raw_snapshot_id,
            retry_after_s=final.retry_after_s,
            error=_short(text) if (text := error or final.error) else None,
        )
        self.sink.record_fetch(entry)
        return entry

    def _log(
        self, method: str, url: str, host: str, purpose: str, outcome: FetchOutcome, error: str
    ) -> FetchEntry:
        """A row for a URL that was not requested (refused, disallowed, invalid)."""
        entry = FetchEntry(
            at=utc_now(),
            method=method,
            url=_short(url),
            host=host,
            purpose=purpose,
            outcome=outcome,
            error=_short(error),
        )
        self.sink.record_fetch(entry)
        return entry

    def _validators(self, base: SnapshotRecord) -> dict[str, str]:
        headers: dict[str, str] = {}
        if "etag" in base.headers:
            headers["If-None-Match"] = base.headers["etag"]
        if "last-modified" in base.headers:
            headers["If-Modified-Since"] = base.headers["last-modified"]
        return headers

    def _interval(self, host: str) -> float:
        if self.replay:
            return 0.0
        return self._intervals.get(host, self.config.min_interval(host))

    def _backoff(self, attempt: int) -> float:
        return float(self.settings.backoff_base_s * 2 ** (attempt - 1) * self.rng.uniform(0.8, 1.2))

    def _fits(self, wait: float) -> bool:
        if self.deadline is None or self.replay:
            return True
        return self.clock.monotonic() + wait <= self.deadline

    def _wait(self, seconds: float) -> None:
        """Wait (interruptibly); raise :class:`_Budget` if it exceeds the budget."""
        if self.replay or seconds <= 0:
            self._check_cancelled()
            return
        if not self._fits(seconds):
            raise _Budget()
        if not self.clock.sleep(seconds, self.cancel):
            raise RunCancelled()

    def _check_cancelled(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise RunCancelled()

    @staticmethod
    def _is_redirect_status(status: int, headers: Mapping[str, str]) -> bool:
        return 300 <= status < 400 and status != 304 and bool(headers.get("location"))

    def _is_redirect(self, sent: _Sent) -> bool:
        return self._is_redirect_status(sent.status, sent.headers)


def manual_fetch_client(
    session: Session,
    settings: Settings,
    *,
    transport: httpx2.BaseTransport | None = None,
    clock: Clock | None = None,
    throttle: HostThrottle | None = None,
) -> PoliteHttpClient:
    """A client for one manual fetch (docs/COLLECTORS.md §10.3): the defaults of
    ``sources.yaml`` with every configured host interval, ``source_id = manual``, no run,
    the 60 s budget, recording into ``fetch_log`` (``run_id`` null) and the snapshot store.

    Raises :class:`CollectorUnavailableError` (``contact_email_missing``) while
    ``CONTACT_EMAIL`` is missing or a placeholder, except in replay mode
    (``COLLECTOR_REPLAY_DIR``), where nothing leaves the machine.
    """
    if transport is None and settings.replay_path is not None:
        transport = ReplayTransport([settings.replay_path])
    replay = isinstance(transport, ReplayTransport)
    problem = contact_email_problem(settings.contact_email)
    if problem is not None and not replay:
        raise CollectorUnavailableError("contact_email_missing", problem)
    return PoliteHttpClient(
        load_sources(settings.sources_path).manual,
        DatabaseSink(session, SnapshotStore(settings.raw_path), run_id=None),
        user_agent=user_agent(None if problem else settings.contact_email, settings.project_url),
        transport=transport,
        source_id=MANUAL,
        replay=replay,
        clock=clock,
        throttle=throttle,
        budget_s=MANUAL_FETCH_BUDGET_S,
        listing_host=None,
    )
