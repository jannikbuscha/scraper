"""Fixture access for the parser tests (no network, no database)."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def fixture_bytes(collector: str, name: str) -> bytes:
    """The body of a fixture, e.g. ``fixture_bytes("ministry_projects", "projects_page1.html")``."""
    return (FIXTURES / collector / name).read_bytes()


def fixture_text(collector: str, name: str) -> str:
    """The body of a fixture decoded as UTF-8."""
    return fixture_bytes(collector, name).decode("utf-8")
