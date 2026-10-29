"""Format and hygiene of the captured test fixtures (``tests/fixtures/``, see its README.md).

Every fixture is a body file plus ``<name>.meta.json``. The checks keep the fixtures traceable
(source URL, retrieval time, SHA-256 of the original capture and of the stored file) and free of
the data lead's contact address: the polite fetcher sent it in its User-Agent, so no meta file may
carry a User-Agent field or a ``mailto:`` address, and no body may echo the User-Agent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from mdt.config import REPO_ROOT

FIXTURES = Path(__file__).parent / "fixtures"
META_SUFFIX = ".meta.json"
NON_FIXTURE_FILES = {"README.md", ".gitattributes"}
MAX_BODY_BYTES = 1024 * 1024

REQUIRED_KEYS: dict[str, type | tuple[type, ...]] = {
    "fixture": str,
    "body": str,
    "collector": str,
    "source": str,
    "purpose": str,
    "url": str,
    "final_url": str,
    "redirects": list,
    "status": int,
    "retrieved_at": str,
    "content_type": str,
    "headers": dict,
    "sha256_original": str,
    "bytes_original": int,
    "sha256_stored": str,
    "bytes_stored": int,
    "trimmed": bool,
    "trim_note": str,
    "licence": str,
    "attribution": str,
    "capture": str,
}
SHA256 = re.compile(r"[0-9a-f]{64}")
USER_AGENT_KEY = re.compile(r"user[\s_-]*agent", re.IGNORECASE)
# Product token of the polite fetcher's User-Agent; a body containing it echoes the User-Agent.
USER_AGENT_PRODUCT = b"MDT-Portfolio-Research"
# Inline bot-manager token of www.kmu.gov.ua; its value encodes the requesting client's IP address.
BOT_MANAGER_TOKEN = b"__uzdbm"


def meta_files() -> list[Path]:
    return sorted(FIXTURES.rglob(f"*{META_SUFFIX}"))


def is_body(path: Path) -> bool:
    return (
        path.is_file()
        and not path.name.endswith(META_SUFFIX)
        and path.name not in NON_FIXTURE_FILES
    )


def body_files() -> list[Path]:
    return sorted(path for path in FIXTURES.rglob("*") if is_body(path))


def load_meta(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path
    return data


def all_keys(value: Any) -> list[str]:
    """Every dictionary key in a JSON value, recursively."""
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        for item in value.values():
            keys.extend(all_keys(item))
        return keys
    if isinstance(value, list):
        return [key for item in value for key in all_keys(item)]
    return []


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


META_PARAMS = [pytest.param(path, id=rel(path)) for path in meta_files()]
BODY_PARAMS = [pytest.param(path, id=rel(path)) for path in body_files()]


def test_fixtures_exist() -> None:
    assert (FIXTURES / "README.md").is_file()
    assert META_PARAMS, "no fixtures found"


def test_every_body_has_exactly_one_meta_file() -> None:
    bodies = {rel(path) for path in body_files()}
    described: dict[str, str] = {}
    for path in meta_files():
        body_rel = rel(path.parent / str(load_meta(path).get("body", "")))
        assert body_rel not in described, f"{body_rel}: two meta files ({rel(path)})"
        described[body_rel] = rel(path)
    assert sorted(bodies - described.keys()) == [], "bodies without a meta file"
    assert sorted(described.keys() - bodies) == [], "meta files without a body"


@pytest.mark.parametrize("path", META_PARAMS)
def test_meta_has_required_keys_and_types(path: Path) -> None:
    meta = load_meta(path)
    for key, expected in REQUIRED_KEYS.items():
        assert key in meta, f"{rel(path)}: missing {key!r}"
        actual = type(meta[key]).__name__
        assert isinstance(meta[key], expected), f"{rel(path)}: {key!r} has type {actual}"
    # bool is a subclass of int: keep the integer fields honest.
    for key in ("status", "bytes_original", "bytes_stored"):
        assert not isinstance(meta[key], bool), f"{rel(path)}: {key!r} must be an integer"
    assert path.name == f"{meta['fixture']}{META_SUFFIX}"
    assert Path(meta["body"]).stem == meta["fixture"]
    assert meta["collector"] == path.parent.name
    assert meta["url"].startswith("https://")
    assert meta["final_url"].startswith(("https://", "http://"))
    assert all(isinstance(hop, str) for hop in meta["redirects"])
    assert SHA256.fullmatch(meta["sha256_original"]), rel(path)
    assert SHA256.fullmatch(meta["sha256_stored"]), rel(path)
    retrieved = datetime.fromisoformat(meta["retrieved_at"].replace("Z", "+00:00"))
    assert retrieved.utcoffset() is not None and retrieved.utcoffset().total_seconds() == 0
    for key in ("purpose", "trim_note", "licence", "attribution", "capture", "source"):
        assert meta[key].strip(), f"{rel(path)}: {key!r} is empty"


@pytest.mark.parametrize("path", META_PARAMS)
def test_stored_body_matches_meta(path: Path) -> None:
    meta = load_meta(path)
    body = (path.parent / meta["body"]).read_bytes()
    stored, original = meta["sha256_stored"], meta["sha256_original"]
    assert hashlib.sha256(body).hexdigest() == stored, f"{rel(path)}: stored sha256 differs"
    assert len(body) == meta["bytes_stored"]
    if meta["trimmed"]:
        assert stored != original, f"{rel(path)}: trimmed, but equal to the original"
    else:
        assert stored == original, f"{rel(path)}: not trimmed, but differs from the original"
        assert meta["bytes_stored"] == meta["bytes_original"]


@pytest.mark.parametrize("path", META_PARAMS)
def test_meta_has_no_user_agent_and_no_mailto(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    meta = load_meta(path)
    offending = [key for key in all_keys(meta) if USER_AGENT_KEY.search(key)]
    assert offending == [], f"{rel(path)}: User-Agent field(s) {offending}"
    assert "mailto:" not in text.lower(), f"{rel(path)}: contains a mailto: address"


@pytest.mark.parametrize("path", BODY_PARAMS)
def test_body_is_small_and_carries_no_client_data(path: Path) -> None:
    data = path.read_bytes()
    assert len(data) <= MAX_BODY_BYTES, f"{rel(path)}: {len(data)} bytes (limit {MAX_BODY_BYTES})"
    assert USER_AGENT_PRODUCT not in data, f"{rel(path)}: echoes the fetcher's User-Agent"
    assert BOT_MANAGER_TOKEN not in data, f"{rel(path)}: contains the kmu.gov.ua bot-manager token"


def configured_contact_email() -> str | None:
    """CONTACT_EMAIL from the environment or the local .env (absent in CI)."""
    value = os.environ.get("CONTACT_EMAIL", "").strip()
    env_file = REPO_ROOT / ".env"
    if not value and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("CONTACT_EMAIL="):
                value = line.split("=", 1)[1].strip().strip("\"'")
    return value or None


def test_no_fixture_contains_the_configured_contact_email() -> None:
    email = configured_contact_email()
    if not email:
        pytest.skip("no CONTACT_EMAIL configured (the format checks above still apply)")
    needle = email.lower().encode("utf-8")
    files = [path for path in FIXTURES.rglob("*") if path.is_file()]
    hits = [rel(path) for path in files if needle in path.read_bytes().lower()]
    assert hits == []
