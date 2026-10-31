"""HTML to text, titles, licences, links and the client-shell rule (parsing/html_text.py)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from mdt.collectors.base import Snapshot
from mdt.collectors.parsing.html_text import (
    PageLink,
    body_of,
    decode_html,
    extract_links,
    html_text,
    licence_of,
    page_title,
    parse_html,
    read_page,
    remove_hidden,
)
from mdt.collectors.parsing.texts import collapse_whitespace
from tests.parsing.helpers import FIXTURES, fixture_bytes, fixture_text


def fixture_snapshot(collector: str, name: str) -> Snapshot:
    """A parser input built from a fixture body and its meta file."""
    body = fixture_bytes(collector, name)
    meta: dict[str, Any] = json.loads(
        (FIXTURES / collector / f"{name.rsplit('.', 1)[0]}.meta.json").read_text("utf-8")
    )
    return Snapshot(
        raw_snapshot_id="raw_fixture",
        run_id=None,
        source_id="test",
        via="replay",
        url=meta["url"],
        final_url=meta["final_url"],
        redirects=tuple(meta["redirects"]),
        http_status=meta["status"],
        fetched_at=meta["retrieved_at"],
        headers=meta.get("headers") or {},
        content_type=None,
        filename=None,
        sha256=meta["sha256_stored"],
        size=len(body),
        body=body,
    )


def _text(html: str) -> str:
    soup = parse_html(html)
    remove_hidden(soup)
    return html_text(body_of(soup))


def test_hidden_and_non_text_elements_are_dropped() -> None:
    html = (
        "<html><head><title>T</title><style>p{}</style></head><body>"
        "<p>Visible <span aria-hidden='true'>icon</span>text</p>"
        "<div hidden>secret</div><script>var a=1;</script><noscript>no js</noscript>"
        "<template>tpl</template><svg><title>svg title</title><text>svg</text></svg>"
        "<iframe>frame</iframe><form><input value='v'><button>Send</button>"
        "<select><option>opt</option></select><textarea>area</textarea>Form text</form>"
        "<p aria-hidden='false'>shown</p><!-- comment -->"
        "</body></html>"
    )
    assert _text(html) == "Visible text\nForm text\nshown"


def test_block_elements_end_lines_and_whitespace_collapses_within_lines() -> None:
    html = (
        "<body><h1> Head\n line </h1><div>a<p>b</p>c</div><ul><li>one</li><li>two</li></ul>"
        "x<br>y<table><tr><td>c1</td><td>c2</td></tr></table>"
        "<section>s</section><article>a</article><header>h</header><footer>f</footer></body>"
    )
    # A block element starts and ends a line; empty lines are dropped.
    assert _text(html) == "Head line\na\nb\nc\none\ntwo\nx\ny\nc1 c2\ns\na\nh\nf"


def test_a_fragment_without_body_is_read_whole() -> None:
    assert _text("<p>one</p><p>two</p>") == "one\ntwo"


@pytest.mark.parametrize(
    ("collector", "name"),
    [("project_sites", "center_home.html"), ("project_sites", "usf_home.html")],
)
def test_footers_stay_in_the_generic_text(collector: str, name: str) -> None:
    page = read_page(fixture_snapshot(collector, name))
    raw = parse_html(fixture_text(collector, name))
    footer = raw.find("footer")
    assert footer is not None
    for line in footer.get_text("\n").splitlines():
        if collapse_whitespace(line):
            assert collapse_whitespace(line) in page.text


def test_the_trap_link_of_usf_is_not_in_the_text_or_the_links() -> None:
    raw = parse_html(fixture_text("project_sites", "usf_home.html"))
    traps = [a for a in raw.find_all("a") if a.has_attr("aria-hidden")]
    assert traps and all("/cdn-cgi/" in str(a.get("href")) for a in traps)
    links = extract_links(raw, "https://usf.com.ua/")
    assert not [link for link in links if "/cdn-cgi/" in link.href]


def test_title_prefers_the_first_h1() -> None:
    soup = parse_html("<title> Page | Site </title><h1>First <b>head</b></h1><h1>Second</h1>")
    assert page_title(soup) == "First head"
    assert page_title(parse_html("<title> Page \n title </title><h1> </h1>")) == "Page title"
    assert page_title(parse_html("<p>none</p>")) is None


def test_the_fixture_titles_come_from_h1_or_title() -> None:
    page = read_page(fixture_snapshot("project_sites", "winwin_home_csr_shell.html"))
    raw = parse_html(fixture_text("project_sites", "winwin_home_csr_shell.html"))
    texts = [collapse_whitespace(tag.get_text(" ")) for tag in raw.find_all(["h1", "title"])]
    # The shell's h1 is empty, so the title comes from <title>.
    assert "" in texts
    assert page.title == next(text for text in texts if text)


@pytest.mark.parametrize(
    ("collector", "name", "licence"),
    [
        ("ministry_news", "microsite_2years_report.html", "cc_by_4_0"),
        ("ministry_news", "microsite_2025_report.html", None),
        ("ministry_projects", "projects_page1.html", "cc_by_4_0"),
        ("kmu_news", "news_uk_2019_regulation.html", "cc_by_4_0"),
        ("kmu_news", "news_en_2019_regulation.html", "cc_by_4_0"),
        ("project_sites", "center_home.html", "all_rights_reserved"),
        ("project_sites", "osvita_home.html", "all_rights_reserved"),
        ("project_sites", "playcity_home.html", "all_rights_reserved"),
        ("project_sites", "united24media_home.html", "all_rights_reserved"),
        ("diia_catalog", "service_reyestraciya_fop.html", "all_rights_reserved"),
    ],
)
def test_licence_phrases_of_the_fixtures(collector: str, name: str, licence: str | None) -> None:
    assert read_page(fixture_snapshot(collector, name)).licence == licence


@pytest.mark.parametrize(
    "phrase",
    ["Всі права захищені", "Усі права захищено", "Усі права захищені", "All rights reserved"],
)
def test_every_reserved_rights_phrase(phrase: str) -> None:
    assert licence_of(f"© 2026 Example. {phrase.upper()}.") == "all_rights_reserved"


def test_cc_by_wins_and_no_statement_gives_none() -> None:
    both = (
        "All rights reserved. All content is available under the Creative Commons "
        "Attribution 4.0 International license unless otherwise noted."
    )
    assert licence_of(both) == "cc_by_4_0"
    assert licence_of("© 2026 Example") is None


def test_the_winwin_shell_is_a_client_rendered_shell() -> None:
    page = read_page(fixture_snapshot("project_sites", "winwin_home_csr_shell.html"))
    assert page.client_shell
    assert len(page.text) < 200


@pytest.mark.parametrize("name", ["u24_home.html", "u24_about.html", "u24_projects.html"])
def test_server_rendered_angular_pages_are_not_shells(name: str) -> None:
    page = read_page(fixture_snapshot("project_sites", name))
    raw = parse_html(fixture_text("project_sites", name))
    assert raw.find("app-root") is not None or raw.find(attrs={"ng-version": True}) is not None
    assert len(page.text) >= 200
    assert not page.client_shell


@pytest.mark.parametrize("name", ["playcity_home.html", "united24media_about.html"])
def test_short_pages_without_an_application_root_are_not_shells(name: str) -> None:
    page = read_page(fixture_snapshot("project_sites", name))
    assert len(page.text) < 200
    assert not page.client_shell


def test_decoding_uses_bom_header_meta_and_utf8_in_that_order() -> None:
    text = "<p>Привіт</p>"
    assert decode_html(b"\xef\xbb\xbf" + text.encode()).text == text
    assert decode_html(text.encode("utf-16")).text == text
    cp1251 = text.encode("cp1251")
    assert decode_html(cp1251, "text/html; charset=windows-1251").text == text
    meta = b'<meta charset="windows-1251">' + cp1251
    assert decode_html(meta).text.endswith(text)
    http_equiv = b'<meta http-equiv="Content-Type" content="text/html; charset=windows-1251">'
    assert decode_html(http_equiv + cp1251).text.endswith(text)
    assert decode_html(text.encode()).text == text


def test_undecodable_bytes_and_unknown_charsets_warn() -> None:
    decoded = decode_html(b"<p>caf\xe9</p>")
    assert decoded.text == "<p>caf�</p>"
    assert [code for code, _ in decoded.warnings] == ["invalid_value"]
    unknown = decode_html(b"<p>x</p>", "text/html; charset=no-such-charset")
    assert unknown.text == "<p>x</p>"
    assert [code for code, _ in unknown.warnings] == ["invalid_value"]


def test_extract_links_resolves_and_filters() -> None:
    soup = parse_html(
        "<a href='/a'>A <b>link</b></a><a href='https://other.example.org/b'>B</a>"
        "<a href='mailto:x@example.org'>mail</a><a href='/cdn-cgi/l/email-protection'>e</a>"
        "<a href='/trap' rel='nofollow' aria-hidden='true'>t</a><a>no href</a>"
        "<a class='svc' href='c'>C</a>"
    )
    assert extract_links(soup, "https://example.org/dir/page") == [
        PageLink("https://example.org/a", "A link"),
        PageLink("https://other.example.org/b", "B"),
        PageLink("https://example.org/dir/c", "C"),
    ]
    assert extract_links(soup, "https://example.org/", "a.svc") == [
        PageLink("https://example.org/c", "C")
    ]
