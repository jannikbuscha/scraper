"""The generic pass of C2 ``project_sites`` (docs/COLLECTORS.md §8.2, §12.2) on the fixtures
of ``backend/tests/fixtures/project_sites/``: expected values are read from those files.
No network, no database; projects and URLs that are not from a fixture are synthetic."""

from __future__ import annotations

import json
from typing import Any

import pytest

from mdt.collectors.base import FatalRunError, LinkHint, Snapshot
from mdt.collectors.parsing import ParseResult
from mdt.collectors.parsing.html_text import body_of, html_text, parse_html, remove_hidden
from mdt.collectors.parsing.texts import collapse_whitespace
from mdt.collectors.project_sites import (
    SiteUrl,
    is_html,
    official_sites,
    parse_site_page,
    soft_404_patterns,
)
from tests.collectors.conftest import FIXTURES

DIRECTORY = FIXTURES / "project_sites"
PATTERNS = {"usf.com.ua": ("Post not found",)}  # as in sources.yaml
SITE = SiteUrl(
    url="https://example.org",
    key="url:https://example.org/",
    project_ids=("prj_01EXAMPLEPROJECTAAAAAAAAAA", "prj_01EXAMPLEPROJECTBBBBBBBBBB"),
)
#: The generic pages of §8.2 and the host of their final URL.
GENERIC = {
    "usf_home": "usf.com.ua",
    "u24_home": "u24.gov.ua",
    "united24media_home": "united24media.com",
    "playcity_home": "playcity.gov.ua",
    "center_home": "center.diia.gov.ua",
    "osvita_home": "osvita.diia.gov.ua",
    "e_pidpryemets_home": "e-pidpryemets.diia.gov.ua",
    "se_portal_page": "se.diia.gov.ua",
    "usf_about": "usf.com.ua",
    "u24_about": "u24.gov.ua",
    "united24media_about": "united24media.com",
}


def snapshot(name: str, body: bytes | None = None, **changes: Any) -> Snapshot:
    """A parser input from a fixture (optionally with another body or metadata)."""
    meta: dict[str, Any] = json.loads((DIRECTORY / f"{name}.meta.json").read_text("utf-8"))
    content = body if body is not None else (DIRECTORY / meta["body"]).read_bytes()
    values: dict[str, Any] = {
        "raw_snapshot_id": f"raw_{name}",
        "run_id": None,
        "source_id": "project_sites",
        "via": "replay",
        "url": meta["url"],
        "final_url": meta["final_url"],
        "redirects": tuple(meta["redirects"]),
        "http_status": meta["status"],
        "fetched_at": meta["retrieved_at"],
        "headers": meta.get("headers") or {},
        "content_type": None,
        "filename": None,
        "sha256": meta["sha256_stored"],
        "size": len(content),
        "body": content,
    }
    return Snapshot(**{**values, **changes})


def parse(name: str, body: bytes | None = None, **changes: Any) -> ParseResult:
    return parse_site_page(
        snapshot(name, body, **changes),
        SITE,
        soft_404_patterns=PATTERNS,
        default_licence="unknown",
    )


def raw_title(name: str) -> str:
    """The first ``h1`` if it has text, else ``<title>``, read from the fixture
    independently of the parser."""
    soup = parse_html((DIRECTORY / f"{name}.html").read_text("utf-8"))
    remove_hidden(soup)
    for tag_name in ("h1", "title"):
        tag = soup.find(tag_name)
        text = collapse_whitespace(tag.get_text(" ")) if tag is not None else ""
        if text:
            return text
    raise AssertionError(f"{name} has no title")


# --------------------------------------------------------------------------------------
# Input URLs and options
# --------------------------------------------------------------------------------------


def test_input_urls_are_deduplicated_by_canonical_url_and_sorted() -> None:
    projects = [
        {"id": "prj_B", "official_urls": ["https://www.example.org/b/", "https://example.org"]},
        {"id": "prj_A", "official_urls": ["https://example.org/", "https://excluded.example.org"]},
        {"id": "prj_C", "official_urls": []},
        {"id": "prj_D", "official_urls": None},
    ]
    sites = official_sites(projects, frozenset({"excluded.example.org"}))
    assert sites == [
        SiteUrl("https://example.org", "url:https://example.org/", ("prj_A", "prj_B")),
        SiteUrl("https://www.example.org/b/", "url:https://www.example.org/b", ("prj_B",)),
    ]


def test_invalid_urls_are_skipped() -> None:
    assert official_sites([{"id": "prj_A", "official_urls": ["not a url"]}], frozenset()) == []


def test_soft_404_patterns_are_read_per_normalised_host() -> None:
    options = {"soft_404_patterns": {"Example.ORG.": [" Page not found "]}}
    assert soft_404_patterns(options) == {"example.org": ("Page not found",)}
    assert soft_404_patterns({}) == {}


@pytest.mark.parametrize(
    "value",
    [["usf.com.ua"], {"example.org": "Post not found"}, {"example.org": [""]}, {"bad host": ["x"]}],
)
def test_malformed_soft_404_patterns_fail_the_run(value: Any) -> None:
    with pytest.raises(FatalRunError, match="soft_404_patterns"):
        soft_404_patterns({"soft_404_patterns": value})


# --------------------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(GENERIC))
def test_generic_pages_give_a_document_candidate(name: str) -> None:
    result = parse(name)
    [candidate] = result.candidates
    meta = json.loads((DIRECTORY / f"{name}.meta.json").read_text("utf-8"))
    assert result.not_found is False
    assert candidate.entity_type == "document"
    assert candidate.key == SITE.key
    assert candidate.url == meta["final_url"]
    assert candidate.label == raw_title(name)
    assert candidate.fields["title"] == raw_title(name)
    assert candidate.fields["url"] == meta["final_url"]
    assert candidate.fields["publisher"] == GENERIC[name]
    assert candidate.fields["doc_type"] == "project_page"
    assert "published" not in candidate.fields
    assert candidate.extraction_method == "html"
    assert candidate.text_snapshot_id == f"raw_{name}"
    assert candidate.evidence.raw_snapshot_id == f"raw_{name}"
    assert candidate.links == [
        LinkHint(snippet="Official URL of the project", subject_id=project_id)
        for project_id in SITE.project_ids
    ]
    soup = parse_html((DIRECTORY / f"{name}.html").read_text("utf-8"))
    remove_hidden(soup)
    assert candidate.text == html_text(body_of(soup))


def test_footer_statements_stay_in_the_text() -> None:
    [center] = parse("center_home").candidates
    assert center.text is not None
    assert (
        "Платформа Дія Центрів розроблена Vintage Web Production у співпраці з Міністерством "
        "цифрової трансформації України" in center.text
    )
    assert "© 2026. Усі права захищені." in center.text
    [usf] = parse("usf_home").candidates
    assert usf.text is not None and "Український Фонд Стартапів © 2026" in usf.text


@pytest.mark.parametrize(
    ("name", "licence"),
    [
        ("center_home", "all_rights_reserved"),  # "Усі права захищені."
        ("osvita_home", "all_rights_reserved"),  # "Усі права захищено"
        ("playcity_home", "all_rights_reserved"),  # "Всі права захищені."
        ("united24media_home", "all_rights_reserved"),  # "All rights reserved."
        ("usf_home", "unknown"),  # "©" only: the default of sources.yaml
        ("u24_home", "unknown"),
        ("e_pidpryemets_home", "unknown"),  # no footer at all
    ],
)
def test_the_licence_comes_from_the_page_or_the_default(name: str, licence: str) -> None:
    [candidate] = parse(name).candidates
    assert candidate.fields["license"] == licence


@pytest.mark.parametrize(
    ("name", "language"),
    [
        ("center_home", "uk"),
        ("usf_about", "uk"),
        ("se_portal_page", "en"),
        ("united24media_home", "en"),
        ("osvita_home", None),  # mixed letters: no value rather than a guess
    ],
)
def test_the_language_is_detected_from_title_and_text(name: str, language: str | None) -> None:
    [candidate] = parse(name).candidates
    assert candidate.fields.get("language") == language


def test_a_redirected_page_is_recorded_under_its_final_url() -> None:
    [candidate] = parse("center_map_wartime").candidates
    final = "https://center.diia.gov.ua/mapa-centriv-so-pracuut-pid-cas-vijni-2"
    assert candidate.url == candidate.fields["url"] == candidate.evidence.source_url == final
    assert candidate.fields["publisher"] == "center.diia.gov.ua"
    assert candidate.key == SITE.key  # the key stays the input URL's


@pytest.mark.parametrize("name", ["playcity_home", "united24media_about"])
def test_short_pages_without_an_application_root_are_documents(name: str) -> None:
    [candidate] = parse(name).candidates
    assert candidate.text is not None and len(candidate.text) < 200


def test_the_hidden_trap_link_of_usf_is_not_in_the_text() -> None:
    html = (DIRECTORY / "usf_home.html").read_text("utf-8")
    assert "/cdn-cgi/" in html
    [candidate] = parse("usf_home").candidates
    assert candidate.text is not None and "cdn-cgi" not in candidate.text


# --------------------------------------------------------------------------------------
# Observed only
# --------------------------------------------------------------------------------------


def test_a_client_rendered_shell_gives_no_document() -> None:
    result = parse("winwin_home_csr_shell")
    assert result.candidates == []
    [(code, message)] = result.warnings
    assert code == "no_server_rendered_content"
    assert message.startswith("https://winwin.gov.ua/:")


def test_a_soft_404_gives_no_document() -> None:
    result = parse("usf_sitemap_soft404")
    assert result.candidates == []
    assert result.not_found is True
    [(code, message)] = result.warnings
    assert code == "soft_404" and "'Post not found'" in message


def test_soft_404_patterns_apply_only_to_their_host() -> None:
    result = parse_site_page(
        snapshot("usf_sitemap_soft404"),
        SITE,
        soft_404_patterns={"example.org": ("Post not found",)},
        default_licence="unknown",
    )
    [candidate] = result.candidates
    assert candidate.fields["title"] == "Post not found"


def test_a_response_that_is_not_html_gives_no_document() -> None:
    result = parse(
        "usf_home",
        b"%PDF-1.4 example",
        headers={"content-type": "application/pdf"},
    )
    assert result.candidates == []
    [(code, message)] = result.warnings
    assert code == "unsupported_content" and "application/pdf" in message


def test_html_is_recognised_by_content_type_or_by_its_first_byte() -> None:
    assert is_html(snapshot("usf_home"))
    assert is_html(snapshot("usf_home", content_type="application/xhtml+xml"))
    assert is_html(snapshot("usf_home", headers={}))  # starts with "<"
    assert not is_html(snapshot("usf_home", b'{"example": true}', headers={}))
    assert not is_html(snapshot("usf_home", headers={"content-type": "text/plain"}))


def test_undecodable_bytes_give_a_warning_but_still_a_document() -> None:
    body = (DIRECTORY / "playcity_home.html").read_bytes().replace(b"</footer>", b"\xff</footer>")
    result = parse("playcity_home", body)
    assert len(result.candidates) == 1
    assert [code for code, _ in result.warnings] == ["invalid_value"]


# --------------------------------------------------------------------------------------
# Volatility (docs/COLLECTORS.md §12.2, derived variants)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["usf_home", "se_portal_page", "united24media_home"])
def test_nonces_tokens_and_inline_scripts_never_reach_the_candidate(name: str) -> None:
    html = (DIRECTORY / f"{name}.html").read_text("utf-8")

    def variant(token: str) -> bytes:
        head = (
            f'<meta name="csrf-token" content="{token}"/>'
            f'<script nonce="{token}">window.__state = {{"token": "{token}"}};</script></head>'
        )
        changed = html.replace("</head>", head, 1)
        return changed.replace(
            "</body>",
            f'<script nonce="{token}">var renderedAt = "{token}";</script>'
            f'<noscript><img src="/pixel?v={token}"/></noscript></body>',
            1,
        ).encode()

    first = parse(name, variant("example-token-1"))
    second = parse(name, variant("example-token-2"))
    assert first == second == parse(name)
