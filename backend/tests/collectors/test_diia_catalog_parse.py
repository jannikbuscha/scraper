"""Parsers of C3 ``diia_catalog`` (docs/COLLECTORS.md §8.3, §12.2) on the fixtures of
``backend/tests/fixtures/diia_catalog/``: every expected value is read from those files.
No network, no database."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
import yaml
from bs4 import BeautifulSoup

from mdt.collectors.base import Candidate, LinkHint, Snapshot
from mdt.collectors.diia_catalog import (
    CatalogContext,
    ListedService,
    Subcategory,
    heading_key,
    parse_audience_page,
    parse_catalogue,
    parse_service_page,
    parse_services_sitemap,
    parse_sitemap_index,
    parse_subcategory_page,
    read_service_page,
    redirect_target,
    service_slug,
    service_url,
)
from mdt.collectors.mappings import load_mapping
from mdt.collectors.parsing import ParseError
from mdt.collectors.parsing.texts import normalize_document_text
from mdt.config import REPO_ROOT
from tests.collectors.conftest import FIXTURES

DIRECTORY = FIXTURES / "diia_catalog"
CODEBOOK = REPO_ROOT / "codebook"
SERVICE_PAGES = {
    "reyestraciya-fop": "service_reyestraciya_fop",
    "vityag-pro-nesudimist": "service_vityag_pro_nesudimist",
    "poshkodzhene-majno": "service_poshkodzhene_majno",
}
PROJECT_ID = "prj_01EXAMPLEEXAMPLEEXAMPLEEXA"  # synthetic


def snapshot(name: str, body: bytes | None = None, raw_snapshot_id: str | None = None) -> Snapshot:
    """A parser input from a fixture (optionally with another body)."""
    meta: dict[str, Any] = json.loads((DIRECTORY / f"{name}.meta.json").read_text("utf-8"))
    content = body if body is not None else (DIRECTORY / meta["body"]).read_bytes()
    return Snapshot(
        raw_snapshot_id=raw_snapshot_id or f"raw_{name}",
        run_id=None,
        source_id="diia_catalog",
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
        size=len(content),
        body=content,
    )


def fixture_html(name: str) -> str:
    return (DIRECTORY / f"{name}.html").read_text("utf-8")


def channel_order() -> dict[str, int]:
    """The order of the channel vocabulary in the codebook (by sort_order)."""
    data = yaml.safe_load((CODEBOOK / "channel.yaml").read_text("utf-8"))
    terms = sorted(data["terms"], key=lambda term: (term["sort_order"], term["code"]))
    return {term["code"]: position for position, term in enumerate(terms)}


def context(**changes: Any) -> CatalogContext:
    base = CatalogContext(
        project_id=PROJECT_ID,
        channels=load_mapping(CODEBOOK, "diia_portal_channels"),
        channel_order=channel_order(),
        default_licence="unknown",
        listed={},
        categories=None,
    )
    return replace(base, **changes)


def candidates(slug: str, ctx: CatalogContext | None = None) -> tuple[Candidate, Candidate]:
    result = parse_service_page(snapshot(SERVICE_PAGES[slug]), slug, ctx or context())
    service, document = result.candidates
    return service, document


# --------------------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------------------


def test_service_slugs_keep_their_case_and_the_host_is_normalised() -> None:
    assert service_slug("https://diia.gov.ua/services/RD4U") == "RD4U"
    assert service_slug("https://DIIA.gov.ua./services/reyestraciya-fop/") == "reyestraciya-fop"
    assert service_url("RD4U") == "https://diia.gov.ua/services/RD4U"


@pytest.mark.parametrize(
    "url",
    [
        "https://diia.gov.ua/services",
        "https://diia.gov.ua/services/categories",
        "https://diia.gov.ua/services/categories/biznesu",
        "https://diia.gov.ua/services/a/b",
        "https://guide.diia.gov.ua/services/example",
        "https://example.org/services/example",
        "mailto:someone@example.org",
    ],
)
def test_other_urls_are_no_service_pages(url: str) -> None:
    assert service_slug(url) is None


# --------------------------------------------------------------------------------------
# Listing and category pages
# --------------------------------------------------------------------------------------


def test_the_catalogue_list_gives_the_slugs_in_page_order() -> None:
    entries = parse_catalogue(snapshot("catalog_root"))
    assert [entry.slug for entry in entries] == [
        "zaiava-v-katehorii-a11-vymushene-vnutrishnie-peremishchennia",
        "zaiava-v-katehorii-a12-vymushene-peremishchennia-za-mezhi-ukrainy",
        "a210-inshi-porushennia-mizhnarodnoho-prava-prav-liudyny-mizhnarodnoho-humanitarnoho-"
        "prava-abo-zakoniv-i-zvychaiv-viiny",
        "reiestratsiia-hromadskoi-orhanizatsii-na-pidstavi-modelnoho-statutu",
        "reyestraciya-potuzhnostej-operatora-rinku",
        "RD4U",
    ]
    rd4u = entries[-1]
    assert rd4u == ListedService("RD4U", label="Репарації: міжнародний реєстр збитків")
    # Neither the footer's category grid nor the "Що таке Дія" link is a service.
    assert all("categories" not in entry.slug for entry in entries)


def test_the_sitemap_index_names_the_services_sitemap() -> None:
    result = parse_sitemap_index(snapshot("sitemap_index"))
    assert result.next_urls == ["https://diia.gov.ua/sitemap-kitsoftservicesmodelsservice-1.xml"]
    assert result.candidates == []


def test_the_services_sitemap_gives_slugs_with_lastmod_as_written() -> None:
    entries = {entry.slug: entry for entry in parse_services_sitemap(snapshot("sitemap_services"))}
    assert list(entries) == [
        "b16-inshi-vtraty-maina",
        "b32-rozkradannia-ta-pryvlasnennia-pryrodnikh-resursiv",
        "b31-ekolohichna-shkoda",
        "vityag-pro-nesudimist",
        "poshkodzhene-majno",
        "reyestraciya-fop",
    ]
    assert entries["reyestraciya-fop"].lastmod == "2019-11-13T10:16:59+02:00"
    assert entries["vityag-pro-nesudimist"].lastmod == "2023-04-24T11:31:09+03:00"
    # /services/RD4U is listed only in the catalogue root: discovery needs both.
    assert "RD4U" not in entries


def test_neither_the_category_sitemap_nor_an_index_lists_service_pages() -> None:
    with pytest.raises(ParseError, match="no service page"):
        parse_services_sitemap(snapshot("sitemap_categories"))
    with pytest.raises(ParseError, match="no services sitemap"):
        parse_sitemap_index(snapshot("sitemap_categories"))


def test_an_audience_page_links_its_subcategory_tiles() -> None:
    result = parse_audience_page(snapshot("category_gromadyanam"))
    assert result.next_urls == [
        "https://diia.gov.ua/services/categories/gromadyanam/yevidnovlennia",
        "https://diia.gov.ua/services/categories/gromadyanam/veteran-pro",
        "https://diia.gov.ua/services/categories/gromadyanam/reparatsii-mizhnarodnyi-reiestr-zbytkiv",
    ]
    # The link inside a tile's description (rd4u.coe.int) is no tile.
    assert "rd4u.coe.int" in fixture_html("category_gromadyanam")
    assert all("rd4u" not in url for url in result.next_urls)


def test_a_subcategory_page_gives_its_audience_label_and_memberships() -> None:
    page = parse_subcategory_page(snapshot("subcategory_biznesu_pidpriyemnictvo"))
    assert page == Subcategory(
        url="https://diia.gov.ua/services/categories/biznesu/pidpriyemnictvo",
        audience="Бізнесу",
        label="Бізнесу / Підприємництво",
        slugs=(
            "zapochatkuvannia-ta-masshtabuvannia-vlasnoi-spravy",
            "litsenziia-na-provadzhennia-diialnosti-z-nadannia-posluh-u-sferi-azartnykh-ihor",
            "e-pidpriyemec",
            "reyestraciya-fop",
        ),
        snapshot_id="raw_subcategory_biznesu_pidpriyemnictvo",
    )
    # The "Від А до Я" accordion repeats services with other markup; it is not read.
    assert "avtomatichne-zakrittya-fop" in fixture_html("subcategory_biznesu_pidpriyemnictvo")
    assert "avtomatichne-zakrittya-fop" not in page.slugs


@pytest.mark.parametrize(
    ("parser", "name", "message"),
    [
        (parse_catalogue, "category_gromadyanam", "no service list"),
        (parse_audience_page, "catalog_root", "no subcategory tiles"),
        (parse_subcategory_page, "category_gromadyanam", "no breadcrumb link"),
        (read_service_page, "catalog_root", "no h1.service-type_title"),
    ],
)
def test_pages_without_the_expected_structure_raise(parser: Any, name: str, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parser(snapshot(name))


def test_a_subcategory_without_services_is_an_empty_page_not_a_parse_error() -> None:
    # Derived from the fixture: the service links removed and the accordion's link box
    # emptied, as two live subcategory pages answered on 2026-10-30.
    soup = BeautifulSoup(fixture_html("subcategory_biznesu_pidpriyemnictvo"), "html.parser")
    for link in soup.select("a.service-acc_item-service"):
        link.decompose()
    for box in soup.select(".service-acc_item-link-box"):
        box.clear()
    page = parse_subcategory_page(
        snapshot("subcategory_biznesu_pidpriyemnictvo", str(soup).encode())
    )
    assert page.slugs == () and page.label == "Бізнесу / Підприємництво"


def test_a_subcategory_page_without_service_links_raises() -> None:
    html = fixture_html("subcategory_biznesu_pidpriyemnictvo").replace(
        "service-acc_item-service", "example-renamed-class"
    )
    with pytest.raises(ParseError, match="lists no service"):
        parse_subcategory_page(snapshot("subcategory_biznesu_pidpriyemnictvo", html.encode()))


# --------------------------------------------------------------------------------------
# Service pages
# --------------------------------------------------------------------------------------


REDIRECT_PAGE = (
    '<!DOCTYPE html><html><head><meta charset="UTF-8" />'
    '<meta http-equiv="refresh" content="0;url=\'https://diia.gov.ua/services/categories/'
    "example-audience/example-subcategory'\" /><title>Redirecting</title></head>"
    "<body>Redirecting to an example page.</body></html>"
)


def test_a_service_page_that_only_redirects_gives_a_warning_and_no_candidate() -> None:
    # Synthetic, shaped like the live answer of /services/RD4U on 2026-10-30 (HTTP 200).
    page = snapshot("service_reyestraciya_fop", REDIRECT_PAGE.encode())
    target = "https://diia.gov.ua/services/categories/example-audience/example-subcategory"
    assert redirect_target(page) == target
    result = parse_service_page(page, "example-slug", context())
    assert result.candidates == []
    url = "https://diia.gov.ua/services/example-slug"
    assert result.warnings == [
        ("unsupported_content", f"{url}: not a service page; it redirects to {target}")
    ]
    assert redirect_target(snapshot("service_reyestraciya_fop")) is None
    with pytest.raises(ParseError, match=r"no h1\.service-type_title"):
        parse_service_page(snapshot("catalog_root"), "example-slug", context())


def test_the_service_name_is_the_h1_not_the_meta_title() -> None:
    html = fixture_html("service_reyestraciya_fop")
    assert '<meta content="Відкриття ФОП" name="title"/>' in html
    service, document = candidates("reyestraciya-fop")
    assert service.fields["name_uk"] == "Автоматична реєстрація ФОП"
    assert (
        service.label == document.label == document.fields["title"] == "Автоматична реєстрація ФОП"
    )


def test_service_candidate_fields_of_the_fop_page() -> None:
    listed = {
        "reyestraciya-fop": ListedService("reyestraciya-fop", lastmod="2019-11-13T10:16:59+02:00")
    }
    service, _ = candidates("reyestraciya-fop", context(listed=listed))
    assert service.entity_type == "service"
    assert service.key == "service:reyestraciya-fop"
    assert service.external_id == "reyestraciya-fop"
    assert service.url == "https://diia.gov.ua/services/reyestraciya-fop"
    assert service.fields == {
        "project_id": PROJECT_ID,
        "name_uk": "Автоматична реєстрація ФОП",
        "description_uk": (
            "Тут ви можете зареєструвати фізичну особу підприємцем, обрати загальну чи "
            "спрощену систему оподаткування.\n"
            "Реєстрація відбувається в автоматичному режимі без участі державного реєстратора."
        ),
        "urls": ["https://diia.gov.ua/services/reyestraciya-fop"],
        "channels": ["portal"],  # "Онлайн"; "Результат" is ignored
    }
    assert service.details == {"lastmod": "2019-11-13T10:16:59+02:00"}
    assert service.field_snapshots == {}
    assert service.evidence.raw_snapshot_id == "raw_service_reyestraciya_fop"
    assert service.evidence.source_url == "https://diia.gov.ua/services/reyestraciya-fop"
    assert service.text is None and service.links == []


@pytest.mark.parametrize(
    ("slug", "description", "channels"),
    [
        (
            "vityag-pro-nesudimist",
            "Витяг про несудимість може знадобитися: під час оформлення на роботу, для "
            "оформлення візи для виїзду за кордон, для участі в тендері, для усиновлення, "
            "встановле…",
            ["portal"],
        ),
        (
            "poshkodzhene-majno",
            "Повідомте про пошкодження або знищення своєї нерухомості внаслідок військової "
            "агресії Російської Федерації.",
            ["portal", "physical"],  # "Онлайн" and "Офлайн"
        ),
    ],
)
def test_descriptions_and_channel_leads(slug: str, description: str, channels: list[str]) -> None:
    service, _ = candidates(slug)
    assert service.fields["description_uk"] == description
    assert service.fields["channels"] == channels
    assert service.details == {"lastmod": None}  # not listed in the context


def test_channels_follow_the_vocabulary_order_not_the_page_order() -> None:
    service, _ = candidates(
        "poshkodzhene-majno", context(channel_order={"physical": 0, "portal": 1})
    )
    assert service.fields["channels"] == ["physical", "portal"]


def test_an_unmapped_channel_lead_is_skipped_with_a_warning() -> None:
    html = fixture_html("service_reyestraciya_fop").replace(
        '<div class="col-12 service-acc_simple-lead">Результат</div>',
        '<div class="col-12 service-acc_simple-lead">Example lead</div>'
        '<div class="col-12 service-acc_simple-lead">Результат</div>',
    )
    result = parse_service_page(
        snapshot("service_reyestraciya_fop", html.encode()), "reyestraciya-fop", context()
    )
    assert result.candidates[0].fields["channels"] == ["portal"]
    [(code, message)] = result.warnings
    assert code == "unmapped_label" and "'Example lead'" in message


def test_pages_without_description_or_channel_section_leave_the_fields_out() -> None:
    html = fixture_html("service_vityag_pro_nesudimist")
    html = html.replace("Опис послуги:", "Example label:").replace(
        "Як отримати послугу", "Example heading"
    )
    result = parse_service_page(
        snapshot("service_vityag_pro_nesudimist", html.encode()), "vityag-pro-nesudimist", context()
    )
    service = result.candidates[0]
    assert "description_uk" not in service.fields
    assert "channels" not in service.fields
    assert result.warnings == []


def test_a_channel_section_with_only_the_result_lead_gives_no_channels() -> None:
    html = fixture_html("service_vityag_pro_nesudimist").replace(
        '<div class="col-12 service-acc_simple-lead">Онлайн</div>', ""
    )
    result = parse_service_page(
        snapshot("service_vityag_pro_nesudimist", html.encode()), "vityag-pro-nesudimist", context()
    )
    assert "channels" not in result.candidates[0].fields
    assert result.warnings == []


def test_services_of_a_later_run_carry_no_project_when_none_is_given() -> None:
    service, _ = candidates("reyestraciya-fop", context(project_id=None))
    assert "project_id" not in service.fields


def test_document_candidate_of_a_service_page() -> None:
    _, document = candidates("reyestraciya-fop")
    assert document.entity_type == "document"
    assert document.key == "page:reyestraciya-fop"
    assert document.external_id == "reyestraciya-fop"
    assert document.url == "https://diia.gov.ua/services/reyestraciya-fop"
    assert document.fields == {
        "title": "Автоматична реєстрація ФОП",
        "url": "https://diia.gov.ua/services/reyestraciya-fop",
        "publisher": "diia.gov.ua",
        "doc_type": "project_page",
        "language": "uk",
        "license": "all_rights_reserved",  # "2019 - 2026. Всі права захищені."
    }
    assert document.extraction_method == "selector"
    assert document.text_snapshot_id == "raw_service_reyestraciya_fop"
    assert document.links == [
        LinkHint(snippet="Service page on diia.gov.ua", subject_key="service:reyestraciya-fop")
    ]
    assert document.details == {}


def test_the_document_text_is_the_main_content() -> None:
    _, document = candidates("reyestraciya-fop")
    text = document.text
    assert text is not None and text == normalize_document_text(text)
    lines = text.split("\n")
    assert lines[:4] == [
        "Автоматична реєстрація ФОП",
        "Подання заяви: ~ 10 хвилин",
        "Реєстрація: до хвилини",
        "Вартість: безоплатно",
    ]
    assert lines[4].startswith("Опис послуги: Тут ви можете зареєструвати фізичну особу")
    for heading in (
        "Як отримати послугу",
        "Онлайн",
        "Результат",
        "Наступні кроки",
        "Часті питання та відповіді",
        "Пов’язані послуги",
        "Пов’язані закони й накази",
    ):
        assert heading in lines
    # Legal acts stay references in the text (their link texts), nothing is followed.
    assert (
        "Закон України «Про державну реєстрацію юридичних осіб, фізичних осіб-підприємців та "
        "громадських формувань»" in lines
    )
    # Header links, the e-mail button and the footer are not main content.
    for outside in ("На головну", "Відправити на email", "2019 - 2026. Всі права захищені."):
        assert outside not in text


def test_the_licence_falls_back_to_the_default_without_a_statement() -> None:
    html = fixture_html("service_vityag_pro_nesudimist").replace(
        "<p>2019 - 2026. Всі права захищені.</p>", ""
    )
    result = parse_service_page(
        snapshot("service_vityag_pro_nesudimist", html.encode()),
        "vityag-pro-nesudimist",
        context(default_licence="unknown"),
    )
    assert result.candidates[1].fields["license"] == "unknown"


def test_categories_are_aggregated_over_the_subcategory_pages() -> None:
    real = parse_subcategory_page(snapshot("subcategory_biznesu_pidpriyemnictvo"))
    synthetic = Subcategory(
        url="https://diia.gov.ua/services/categories/example-audience/example-subcategory",
        audience="Example audience",
        label="Example audience / Example subcategory",
        slugs=("reyestraciya-fop",),
        snapshot_id="raw_example",
    )
    service, _ = candidates(
        "reyestraciya-fop", context(categories={"reyestraciya-fop": [synthetic, real]})
    )
    assert service.fields["source_categories"] == [  # sorted by URL
        {
            "source": "diia_catalog",
            "label": "Бізнесу / Підприємництво",
            "url": "https://diia.gov.ua/services/categories/biznesu/pidpriyemnictvo",
        },
        {
            "source": "diia_catalog",
            "label": "Example audience / Example subcategory",
            "url": "https://diia.gov.ua/services/categories/example-audience/example-subcategory",
        },
    ]
    assert service.fields["source_audiences"] == ["Example audience", "Бізнесу"]
    pages = ["raw_subcategory_biznesu_pidpriyemnictvo", "raw_example"]
    assert service.field_snapshots == {"source_categories": pages, "source_audiences": pages}


def test_without_complete_categories_both_fields_are_left_out() -> None:
    service, _ = candidates("reyestraciya-fop", context(categories=None))
    assert "source_categories" not in service.fields
    assert "source_audiences" not in service.fields
    unlisted, _ = candidates("reyestraciya-fop", context(categories={}))
    assert "source_categories" not in unlisted.fields


def test_heading_variants_compare_equal() -> None:
    assert heading_key("Пов’язані закони й накази") == heading_key("Пов'язані закони та накази")
    assert heading_key("Повʼязані закони та накази:") == heading_key("Пов’язані  закони та накази")
    assert heading_key("Опис послуги:") == heading_key("опис послуги")
    assert heading_key("Як отримати послугу") != heading_key("Наступні кроки")


@pytest.mark.parametrize("slug", sorted(SERVICE_PAGES))
def test_volatile_parts_never_reach_the_candidates(slug: str) -> None:
    """Derived volatility pair (docs/COLLECTORS.md §12.2): csrf token, nonces and inline
    scripts changed in memory give identical candidates."""
    name = SERVICE_PAGES[slug]
    html = fixture_html(name)

    def variant(token: str) -> bytes:
        head = (
            f'<meta name="csrf-token" content="{token}"/>'
            f'<script nonce="{token}">window.csrfToken = "{token}";</script></head>'
        )
        body = (
            f'<body><script nonce="{token}">var renderedAt = "{token}";</script>'
            f'<input type="hidden" name="_token" value="{token}"/>'
        )
        return html.replace("</head>", head, 1).replace("<body>", body, 1).encode()

    first = parse_service_page(snapshot(name, variant("example-token-1"), "raw_x"), slug, context())
    second = parse_service_page(
        snapshot(name, variant("example-token-2"), "raw_x"), slug, context()
    )
    assert first == second
    assert first.candidates == candidates_of(name, slug)


def candidates_of(name: str, slug: str) -> list[Candidate]:
    """The candidates of the unchanged fixture with the snapshot ID of the variants."""
    return parse_service_page(snapshot(name, raw_snapshot_id="raw_x"), slug, context()).candidates


def test_the_trailing_dot_host_variant_in_a_sitemap_counts_as_diia_gov_ua() -> None:
    body = (
        (DIRECTORY / "sitemap_services.xml")
        .read_bytes()
        .replace(
            b"https://diia.gov.ua/services/reyestraciya-fop",
            b"https://diia.gov.ua./services/reyestraciya-fop",
        )
    )
    entries = parse_services_sitemap(snapshot("sitemap_services", body))
    assert "reyestraciya-fop" in [entry.slug for entry in entries]


def test_undecodable_bytes_give_a_warning_with_the_candidates() -> None:
    name = SERVICE_PAGES["poshkodzhene-majno"]
    body = (DIRECTORY / f"{name}.html").read_bytes().replace(b"</footer>", b"\xff</footer>")
    result = parse_service_page(snapshot(name, body), "poshkodzhene-majno", context())
    assert len(result.candidates) == 2
    [(code, message)] = result.warnings
    assert code == "invalid_value"
    assert message.startswith("https://diia.gov.ua/services/poshkodzhene-majno: ")
