"""``mdt sources check`` (docs/COLLECTORS.md §11): the reachability re-check from the current
machine (geo-blocking, risk R2; docs/SOURCES.md §5 item 1).

Per host of the selected collectors it fetches robots.txt and the collector's check URL
(option ``check_url``, a URL or a list; else the host root) through the polite client, and
reports the robots decision, HTTP status, final URL, block signature and duration. The hosts
of ``project_sites`` are those of the live projects' ``official_urls``. Nothing is recorded
in the database.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import httpx2

from mdt.collectors.client import PoliteHttpClient, user_agent
from mdt.collectors.fetchlog import MemorySink
from mdt.collectors.sources import CollectorConfig
from mdt.collectors.throttle import Clock
from mdt.collectors.urls import UrlError, parse_fetch_url
from mdt.config import Settings

#: The collector whose hosts come from the live projects' official URLs (§8.2).
PROJECT_SITES = "project_sites"


@dataclass(frozen=True)
class HostCheck:
    """One line of the report."""

    collector: str
    host: str
    url: str
    robots: str  # rules, allow_all, blocked, unavailable
    robots_reason: str
    status: int | None
    final_url: str | None
    signature: str | None
    duration_ms: int
    outcome: str

    @property
    def failed(self) -> bool:
        """Blocked or unreachable (robots.txt unavailable, network error, refused)."""
        return self.outcome in ("blocked", "network_error", "refused") or self.robots in (
            "blocked",
            "unavailable",
        )


def check_urls(config: CollectorConfig, official_urls: Callable[[], Iterable[str]]) -> list[str]:
    """The URLs to check for a collector, one per host (the first one listed wins)."""
    configured = config.options.get("check_url")
    urls: list[str] = []
    if isinstance(configured, str):
        urls.append(configured)
    elif isinstance(configured, list):
        urls.extend(str(item) for item in configured)
    urls.extend(f"https://{host}/" for host in sorted(config.host_intervals))
    if config.name == PROJECT_SITES:
        urls.extend(official_urls())
    by_host: dict[str, str] = {}
    for url in urls:
        try:
            target = parse_fetch_url(url)
        except UrlError:
            continue
        if target.host not in config.exclude_hosts:
            by_host.setdefault(target.host, target.url)
    return list(by_host.values())


def check_collector(
    config: CollectorConfig,
    settings: Settings,
    urls: Sequence[str],
    *,
    transport: httpx2.BaseTransport | None = None,
    clock: Clock | None = None,
) -> list[HostCheck]:
    """Check ``urls`` of one collector."""
    client = PoliteHttpClient(
        config,
        MemorySink(),
        user_agent=user_agent(settings.contact_email, settings.project_url),
        transport=transport,
        source_id=config.name,
        clock=clock,
        listing_host=None,
    )
    checks: list[HostCheck] = []
    with client:
        for url in urls:
            target = parse_fetch_url(url)
            policy = client.robots_policy(target.url)
            common = {
                "collector": config.name,
                "host": target.host,
                "url": target.url,
                "robots": policy.state,
                "robots_reason": policy.reason,
            }
            if policy.state in ("blocked", "unavailable"):
                signature = policy.reason if policy.state == "blocked" else None
                checks.append(
                    HostCheck(
                        **common,
                        status=policy.status,
                        final_url=None,
                        signature=signature,
                        duration_ms=0,
                        outcome="refused",
                    )
                )
                continue
            result = client.get(target.url)
            checks.append(
                HostCheck(
                    **common,
                    status=result.status,
                    final_url=result.final_url,
                    signature=result.signature,
                    duration_ms=result.duration_ms,
                    outcome=result.outcome,
                )
            )
    return checks
