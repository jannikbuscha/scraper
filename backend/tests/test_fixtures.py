"""Format and hygiene of the captured test fixtures (``tests/fixtures/``, see its README.md).

Every fixture is a body file plus ``<name>.meta.json``. The checks keep the fixtures traceable
(source URL, retrieval time, SHA-256 of the original capture and of the stored file) and free of
the data lead's contact address: the polite fetcher sent it in its User-Agent, so no meta file may
carry a User-Agent field or a ``mailto:`` address, and no body may echo the User-Agent.

Synthetic fixtures (written by hand, never captured; docs/COLLECTORS.md §8.5) follow their own
rules, checked below: a ``synthetic_`` name together with ``"synthetic": true``, a ``capture``
that starts with ``synthetic:`` and names its documentation, the fixed licence phrase, no
trimming, and bodies whose URLs use only reserved example hosts and whose CDX digests and lengths
are obviously made up, so no synthetic row can be mistaken for an archive fact about a real site.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

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
# Synthetic fixtures (README.md, "Synthetic fixtures").
SYNTHETIC_PREFIX = "synthetic_"
SYNTHETIC_LICENCE = "synthetic test data written for this repository"
RESERVED_HOSTS = frozenset({"example.org", "www.example.org", "example.com"})
# SURT host prefixes of the reserved hosts as they open a CDX urlkey (``org,example)/…``).
RESERVED_URLKEYS = ("org,example)", "com,example)")
URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]+")
GZIP_MAGIC = b"\x1f\x8b"


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
    # The body is the fixture name plus its extension(s), e.g. ``.json.gz``.
    assert meta["body"].partition(".")[0] == meta["fixture"]
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


def is_synthetic(meta: dict[str, Any]) -> bool:
    return str(meta["fixture"]).startswith(SYNTHETIC_PREFIX) or "synthetic" in meta


SYNTHETIC_PARAMS = [
    pytest.param(path, id=rel(path)) for path in meta_files() if is_synthetic(load_meta(path))
]


def decoded_body(data: bytes) -> str:
    """A body as text, decompressed first when it is gzip (the CDX server's default)."""
    return (gzip.decompress(data) if data.startswith(GZIP_MAGIC) else data).decode("utf-8")


def reserved_url(url: str) -> bool:
    """An http(s) URL on a reserved example host."""
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and (parts.hostname or "") in RESERVED_HOSTS


def described_urls(meta: dict[str, Any]) -> list[str]:
    """The source URLs a synthetic fixture's request names: the ``url=`` value of a CDX
    query (prefix forms without a scheme count as http) or the original URL of a capture
    URL (``/web/<timestamp>[id_]/<original>``)."""
    found: list[str] = []
    for url in [meta["url"], meta["final_url"]]:
        parts = urlsplit(url)
        for value in parse_qs(parts.query).get("url", []):
            found.append(value if "://" in value else f"http://{value}")
        capture = re.match(r"/web/\d{14}(?:id_)?/(.+)", parts.path)
        if capture:
            found.append(capture.group(1))
    return found


def cdx_rows(text: str) -> list[list[str]] | None:
    """The rows of a CDX JSON body (header first), or None for other bodies."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, list) and all(isinstance(row, list) for row in data):
        return data
    return None


def test_synthetic_fixtures_exist() -> None:
    assert SYNTHETIC_PARAMS, "the synthetic C5 fixtures of docs/COLLECTORS.md §8.5 are missing"


@pytest.mark.parametrize("path", SYNTHETIC_PARAMS)
def test_synthetic_fixture_meta_follows_the_rules(path: Path) -> None:
    meta = load_meta(path)
    where = rel(path)
    assert str(meta["fixture"]).startswith(SYNTHETIC_PREFIX), f"{where}: name must start synthetic_"
    assert meta.get("synthetic") is True, f'{where}: synthetic fixtures carry "synthetic": true'
    assert meta["capture"].startswith("synthetic:"), f"{where}: capture must start synthetic:"
    assert "docs/SOURCES.md" in meta["capture"], f"{where}: capture must cite its documentation"
    assert meta["licence"] == SYNTHETIC_LICENCE, where
    assert meta["trimmed"] is False, f"{where}: a synthetic body is never trimmed"
    urls = described_urls(meta)
    assert urls, f"{where}: the request names no source URL"
    assert all(reserved_url(url) for url in urls), f"{where}: {urls}"


@pytest.mark.parametrize("path", SYNTHETIC_PARAMS)
def test_synthetic_fixture_body_names_only_reserved_hosts(path: Path) -> None:
    meta = load_meta(path)
    where = rel(path)
    text = decoded_body((path.parent / meta["body"]).read_bytes())
    urls = URL_IN_TEXT.findall(text)
    assert all(reserved_url(url) for url in urls), f"{where}: {urls}"
    rows = cdx_rows(text)
    if not rows:
        return
    header, data = rows[0], rows[1:]
    if len(data) >= 2 and data[-2] == [] and len(data[-1]) == 1:  # resume key
        assert unquote(data[-1][0].replace("+", " ")).startswith(RESERVED_URLKEYS), where
        data = data[:-2]
    column = {name: index for index, name in enumerate(header)}
    for row in data:
        assert row[column["urlkey"]].startswith(RESERVED_URLKEYS), f"{where}: {row}"
        assert reserved_url(row[column["original"]]), f"{where}: {row}"
        if "digest" in column:
            assert row[column["digest"]].startswith("SYNTHETIC"), f"{where}: digest {row}"
        if "length" in column:
            assert row[column["length"]] == "0", f"{where}: length {row}"


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
