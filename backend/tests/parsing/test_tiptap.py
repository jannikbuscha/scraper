"""TipTap JSON to text and links (parsing/tiptap.py, docs/COLLECTORS.md §7.3).

The fixture assertions are the ones of §7.3; expected values are read from the fixtures.
"""

from __future__ import annotations

from typing import Any

from mdt.collectors.parsing.texts import collapse_whitespace
from mdt.collectors.parsing.tiptap import OutboundLink, outbound_href, tiptap_to_text
from mdt.collectors.parsing.turbostream import find_route, loader_data
from tests.parsing.helpers import fixture_text


def _entry(collector: str, name: str, key: str) -> dict[str, Any]:
    _, data = find_route(loader_data(fixture_text(collector, name)), (key,))
    entry = data[key]
    assert isinstance(entry, dict)
    return entry


def _nodes(document: Any, kind: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(document, dict):
        if document.get("type") == kind:
            found.append(document)
        for value in document.values():
            found.extend(_nodes(value, kind))
    elif isinstance(document, list):
        for value in document:
            found.extend(_nodes(value, kind))
    return found


def test_brave1_has_the_platform_line_and_its_only_outbound_link() -> None:
    blocks = _entry("ministry_projects", "project_brave1_technologies.html", "project")["blocks"]
    result = tiptap_to_text(blocks)
    assert "Платформа Brave1" in result.text.splitlines()
    assert [link.href for link in result.links] == ["https://brave1.gov.ua/"]
    expected = OutboundLink("https://brave1.gov.ua/", "Платформа Brave1", "linkListItem")
    assert result.links[0] == expected


def test_hromada_has_its_link_and_the_value_card_line() -> None:
    project = _entry(
        "ministry_projects", "project_diiatsyfrova_hromada_additional_rubric.html", "project"
    )
    result = tiptap_to_text(project["blocks"])
    assert "https://hromada.gov.ua/" in [link.href for link in result.links]
    card = _nodes(project["blocks"], "valueCardListItem")[0]["attrs"]
    expected = " ".join(card[key] for key in ("value", "unit", "text") if key in card)
    assert expected.startswith("1353 лідерів та лідерок територіальних громад")
    assert expected in result.text.splitlines()


def test_value_cards_with_a_unit_put_value_unit_and_text_on_one_line() -> None:
    project = _entry(
        "ministry_projects", "project_diiatsyfrova_hromada_additional_rubric.html", "project"
    )
    lines = tiptap_to_text(project["blocks"]).text.splitlines()
    with_unit = [node["attrs"] for node in _nodes(project["blocks"], "valueCardListItem")]
    for attrs in with_unit:
        parts = [attrs[key] for key in ("value", "unit", "text") if key in attrs]
        assert " ".join(parts) in lines


def test_virtual_assets_keeps_the_rada_and_storage_links_but_no_mailto() -> None:
    project = _entry("ministry_projects", "project_virtual_assets_business.html", "project")
    result = tiptap_to_text(project["blocks"])
    hosts = [link.href.split("/")[2] for link in result.links]
    assert hosts.count("w1.c1.rada.gov.ua") == 1
    assert hosts.count("cms.thedigital.gov.ua") == 4
    assert not any(link.href.lower().startswith("mailto:") for link in result.links)
    # The button with the mailto link still gives its text as a line.
    button = _nodes(project["blocks"], "buttonsItem")[0]["attrs"]
    assert button["href"].startswith("mailto:")
    assert button["text"] in result.text.splitlines()


def test_ministry_page_has_the_labels_of_its_tabs_and_sections() -> None:
    page = _entry("ministry_news", "ministry_page.html", "page")
    lines = tiptap_to_text(page["blocks"]).text.splitlines()
    tab_labels = [node["attrs"]["label"] for node in _nodes(page["blocks"], "tabsItem")]
    assert len(tab_labels) == 5
    assert all(label in lines for label in tab_labels)
    section_labels = [
        collapse_whitespace(node["attrs"]["label"]["text"])
        for node in _nodes(page["blocks"], "section")
    ]
    assert section_labels and all(label in lines for label in section_labels)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for part in value.values() for item in _strings(part)]
    if isinstance(value, list):
        return [item for part in value for item in _strings(part)]
    return []


def test_team_members_and_related_documents_give_no_text() -> None:
    page = _entry("ministry_news", "ministry_page.html", "page")
    text = tiptap_to_text(page["blocks"]).text
    for kind in ("teamMembers", "relatedDocuments"):
        nodes = _nodes(page["blocks"], kind)
        assert nodes
        # Names, positions and document titles held in their attributes stay out.
        held = [s for node in nodes for s in _strings(node.get("attrs")) if len(s) > 15]
        assert held
        assert not [value for value in held if value in text]


def _item(text: str) -> dict[str, Any]:
    paragraph = {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    return {"type": "listItem", "content": [paragraph]}


def test_line_ends_breaks_and_link_marks() -> None:
    document = {
        "type": "doc",
        "content": [
            {"type": "heading", "content": [{"type": "text", "text": "Title"}]},
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "See "},
                    {
                        "type": "text",
                        "text": "the ",
                        "marks": [{"type": "link", "attrs": {"href": "https://example.org/a"}}],
                    },
                    {
                        "type": "text",
                        "text": "site",
                        "marks": [
                            {"type": "bold"},
                            {"type": "link", "attrs": {"href": "https://example.org/a"}},
                        ],
                    },
                    {"type": "hardBreak"},
                    {
                        "type": "text",
                        "text": "mail",
                        "marks": [{"type": "link", "attrs": {"href": "mailto:a@example.org"}}],
                    },
                ],
            },
            {"type": "bulletList", "content": [_item("one"), _item("two")]},
        ],
    }
    result = tiptap_to_text(document)
    assert result.text == "Title\nSee the site\nmail\none\ntwo"
    assert result.links == (OutboundLink("https://example.org/a", "the site", "mark"),)


def test_skipped_nodes_attributes_and_tables() -> None:
    document = [
        {"type": "image", "attrs": {"alt": "picture"}, "content": [{"type": "text", "text": "x"}]},
        {"type": "embed", "attrs": {"embed": "<iframe>"}},
        {"type": "section", "attrs": {"label": {"text": "Section label"}}, "content": []},
        {"type": "tabsItem", "attrs": {"label": "Tab label"}},
        {
            "type": "linkListItem",
            "attrs": {"href": "/relative", "text": "Relative", "buttonText": "Go"},
        },
        {"type": "paragraph", "attrs": {"textAlign": "left"}, "content": []},
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {"type": "tableCell", "content": [{"type": "text", "text": "a"}]},
                        {"type": "tableCell", "content": [{"type": "text", "text": "b"}]},
                    ],
                }
            ],
        },
        "not a node",
        {"type": "valueCardListItem", "attrs": {"value": "5"}},
    ]
    result = tiptap_to_text(document)
    assert result.text == "Section label\nTab label\nRelative\na\tb\n5"
    assert result.links == ()


def test_empty_documents() -> None:
    assert tiptap_to_text(None).text == ""
    assert tiptap_to_text([]).links == ()


def test_outbound_href_accepts_absolute_http_urls_only() -> None:
    assert outbound_href(" https://Example.org/Path ") == "https://Example.org/Path"
    assert outbound_href("HTTP://example.org") == "http://example.org"
    for value in ("mailto:a@example.org", "/relative", "ftp://example.org", "https://", 5, None):
        assert outbound_href(value) is None
