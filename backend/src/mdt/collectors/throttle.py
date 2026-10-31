"""Time and the process-wide per-host throttle of the polite client
(docs/COLLECTORS.md §4.3).

Per host, the next request starts no earlier than the host's interval after the previous
request to that host ended, and no earlier than a server's ``Retry-After`` allows (§4.6).
Every attempt counts (robots.txt, redirect hops, retries). The state is shared by all clients
of the process, so a manual fetch in the server and a running collector take turns and both
honour a ``Retry-After``; waiting is interruptible by a cancel request.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Protocol


class Clock(Protocol):
    """Time source of the client (tests use a fake one)."""

    def monotonic(self) -> float:
        """Seconds of a monotonic clock."""
        ...

    def time(self) -> float:
        """Wall-clock seconds since the epoch (for HTTP-date ``Retry-After``)."""
        ...

    def sleep(self, seconds: float, cancel: threading.Event | None) -> bool:
        """Wait; return False if ``cancel`` was set before the time was up."""
        ...


class SystemClock:
    """The real clock; waiting is interrupted by the cancel event."""

    def monotonic(self) -> float:
        """``time.monotonic()``."""
        return time.monotonic()

    def time(self) -> float:
        """``time.time()``."""
        return time.time()

    def sleep(self, seconds: float, cancel: threading.Event | None) -> bool:
        """Wait up to ``seconds``; False if cancelled meanwhile."""
        if cancel is None:
            if seconds > 0:
                time.sleep(seconds)
            return True
        if seconds <= 0:
            return not cancel.is_set()
        return not cancel.wait(seconds)


@dataclass
class _HostSlot:
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_end: float | None = None
    not_before: float | None = None  # the latest Retry-After of the host (monotonic)


class HostDeferred(Exception):
    """The host asked (``Retry-After``) for a longer wait than the caller may start."""

    def __init__(self, seconds: float) -> None:
        super().__init__(f"the host asked to wait {seconds:g} s")
        self.seconds = seconds


class HostThrottle:
    """Per-host spacing shared by every client of the process: the next request to a host
    starts no earlier than its interval after the previous request to it ended, and not
    before the time a ``Retry-After`` of the host named. A request holds its host's slot
    from the wait to its end, so concurrent clients (a run and a manual fetch) take
    turns."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hosts: dict[str, _HostSlot] = {}

    def _slot(self, host: str) -> _HostSlot:
        with self._lock:
            return self._hosts.setdefault(host, _HostSlot())

    def defer(self, host: str, seconds: float, clock: Clock) -> None:
        """The host answered with ``Retry-After: seconds``: no client of the process sends
        it a request before that time (a later, shorter value never shortens it)."""
        slot = self._slot(host)
        until = clock.monotonic() + max(0.0, seconds)
        with self._lock:
            if slot.not_before is None or until > slot.not_before:
                slot.not_before = until

    @contextmanager
    def turn(
        self,
        host: str,
        interval: float,
        clock: Clock,
        wait: Callable[[float], None],
        poll: Callable[[], None],
        max_wait: float | None = None,
    ) -> Iterator[None]:
        """Hold the host's slot for one request; ``wait`` sleeps (it may raise to give up)
        and ``poll`` is called while another client holds the slot. A wait for a
        ``Retry-After`` longer than ``max_wait`` is not started: :class:`HostDeferred`."""
        slot = self._slot(host)
        while not slot.lock.acquire(timeout=0.2):
            poll()
        requested = False
        try:
            now = clock.monotonic()
            remaining = 0.0 if slot.last_end is None else slot.last_end + interval - now
            deferred = 0.0 if slot.not_before is None else slot.not_before - now
            if max_wait is not None and deferred > max_wait:
                raise HostDeferred(deferred)
            remaining = max(remaining, deferred)
            if remaining > 0:
                wait(remaining)
            requested = True
            yield
        finally:
            if requested:
                slot.last_end = clock.monotonic()
            slot.lock.release()


#: The throttle shared by all clients of this process (docs/COLLECTORS.md §4.3).
PROCESS_THROTTLE = HostThrottle()
