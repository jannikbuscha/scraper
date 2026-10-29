"""URL normalisation (DATA_MODEL §1.2) and canonical URLs (§3.4)."""

from __future__ import annotations

import pytest

from mdt.domain.urls import UrlError, canonical_url, normalize_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.org/path?q=1#frag", "https://example.org/path?q=1#frag"),
        ("  https://example.org  ", "https://example.org"),
        # The scheme is stored lower-case; ASCII host labels keep their case (IDNA).
        ("HTTPS://Example.ORG/Path", "https://Example.ORG/Path"),
        ("https://example.org/\u00a0", "https://example.org/"),  # trimmed
        ("http://example.org:8080/x", "http://example.org:8080/x"),
        ("https://приклад.укр/шлях", "https://xn--80aikifvh.xn--j1amh/шлях"),
        ("https://example.org.", "https://example.org."),
        ("https://[2001:db8::1]/x", "https://[2001:db8::1]/x"),
    ],
)
def test_valid_urls(value: str, expected: str) -> None:
    assert normalize_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "ftp://example.org/file",
        "javascript:alert(1)",
        "java\tscript:alert(1)",
        "data:text/html,hi",
        "mailto:someone@example.org",
        "https://",
        "https:///path",
        "https:example.org",
        "//example.org/path",
        "https://user@example.org/",
        "https://user:secret@example.org/",
        "https://example.org/a b",
        "https://example.org/a\u00a0b",
        "https://example.org/\x00",
        "https://example.org/a\x85b",
        "https://example.org/a\u2028b",
        "https://example.org/\x7f",
        "https://example.org:99999/",
        "https://example.org:/",
        "https://example.org:\uff18\uff10/",
        "https://exa mple.org/",
        "https://example..org/",
        "https://example.org\\@evil.example/",
        "https://[::1/",
        "https://example.org/" + "a" * 2000,
    ],
)
def test_invalid_urls(value: str) -> None:
    with pytest.raises(UrlError):
        normalize_url(value)


def test_maximum_length_is_2000_characters() -> None:
    url = "https://example.org/" + "a" * (2000 - len("https://example.org/"))
    assert normalize_url(url) == url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Example.ORG./path/", "https://example.org/path"),
        ("https://example.org:443/a", "https://example.org/a"),
        ("http://example.org:80/a", "http://example.org/a"),
        ("http://example.org:8080/a/", "http://example.org:8080/a"),
        ("https://example.org/a#section", "https://example.org/a"),
        ("https://example.org/", "https://example.org/"),
        ("https://example.org", "https://example.org/"),
        (
            "https://example.org/a?utm_source=x&id=7&UTM_Medium=y",
            "https://example.org/a?id=7",
        ),
        ("https://example.org/a?utm_source=x", "https://example.org/a"),
        ("https://example.org/a//", "https://example.org/a"),
    ],
)
def test_canonical_url(value: str, expected: str) -> None:
    assert canonical_url(value) == expected
