"""API errors of data acquisition (docs/API.md §1.2, §7.2, §7.8). Each class maps to one
error code; the HTTP layer turns them into the error envelope like every
:class:`~mdt.domain.errors.DomainError`."""

from __future__ import annotations

from mdt.domain.errors import DomainError


class RunInProgressError(DomainError):
    """409: another collector run is running (CLI or server)."""

    code = "run_in_progress"
    status = 409
    default_message = "Another collector run is running; try again when it has finished"

    def __init__(self, run_id: str, collector: str | None = None):
        message = None
        if collector:
            message = f"Run {run_id} ({collector}) is running; try again when it has finished"
        super().__init__(message, {"run_id": run_id})
        self.run_id = run_id
        self.collector = collector


class CollectorUnavailableError(DomainError):
    """409: the collector is disabled, or ``CONTACT_EMAIL`` is missing or a placeholder
    (``reason`` = ``disabled`` or ``contact_email_missing``)."""

    code = "collector_unavailable"
    status = 409
    default_message = "The collector cannot be started"

    def __init__(self, reason: str, message: str | None = None):
        super().__init__(message, {"reason": reason})


class FetchFailedError(DomainError):
    """502: a manual fetch failed (docs/API.md §7.8); ``details = {reason, status}`` with the
    reason from :attr:`mdt.collectors.client.FetchResult.reason`."""

    code = "fetch_failed"
    status = 502
    default_message = "The URL could not be fetched"

    def __init__(self, reason: str, http_status: int | None, message: str | None = None):
        super().__init__(message, {"reason": reason, "status": http_status})
