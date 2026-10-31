"""Language detection (parsing/language.py) and sitemaps (parsing/sitemaps.py)."""

from __future__ import annotations

import re

import pytest

from mdt.collectors.parsing import ParseError
from mdt.collectors.parsing.language import detect_language, kmu_language
from mdt.collectors.parsing.sitemaps import SitemapEntry, parse_sitemap
from mdt.collectors.parsing.tiptap import tiptap_to_text
from mdt.collectors.parsing.turbostream import find_route, loader_data
from tests.parsing.helpers import fixture_bytes, fixture_text


def _article_language(name: str) -> tuple[str | None, list[str]]:
    _, data = find_route(loader_data(fixture_text("ministry_news", name)), ("article",))
    article = data["article"]
    text = tiptap_to_text(article.get("blocks")).text
    codes = [item["language"]["code"] for item in article.get("translations") or []]
    return detect_language(article["title"], text), codes


def test_the_english_article_is_english_although_its_translations_say_uk() -> None:
    language, translations = _article_language("news_article_en_2024.html")
    assert translations == ["uk"]
    assert language == "en"


@pytest.mark.parametrize(
    "name", ["news_article_2019.html", "news_article_2022.html", "news_article_redirect_2021.html"]
)
def test_ukrainian_articles_are_ukrainian(name: str) -> None:
    assert _article_language(name)[0] == "uk"


def test_russian_letters_outnumbering_ukrainian_ones_give_ru() -> None:
    assert detect_language("Новости", "Это объявление о работе ещё одного сервиса") == "ru"
    assert detect_language("Новини", "Це оголошення про роботу ще одного сервісу") == "uk"


def test_mixed_or_empty_texts_give_no_language() -> None:
    assert detect_language("Дія Diia", "сервіс service") is None
    assert detect_language(None, None) is None
    assert detect_language("", "1234 — 5678") is None


def test_only_the_first_5000_letters_count() -> None:
    assert detect_language("", "a" * 5000 + "б" * 20000) == "en"
    assert detect_language("", "б" * 5000 + "a" * 20000) == "uk"


def test_modifier_apostrophes_are_not_letters() -> None:
    assert detect_language("", "зʼявилася ʼʼʼʼʼʼʼʼʼʼʼʼʼʼʼʼʼʼʼʼʼʼʼʼ") == "uk"


def test_kmu_language_comes_from_the_url() -> None:
    assert kmu_language("https://www.kmu.gov.ua/en/news/example") == "en"
    assert kmu_language("https://www.kmu.gov.ua/news/example") == "uk"
    assert kmu_language("https://www.kmu.gov.ua/english") == "uk"


def _loc_count(collector: str, name: str) -> int:
    return len(re.findall(r"<loc>", fixture_text(collector, name)))


@pytest.mark.parametrize(
    ("collector", "name", "kind"),
    [
        ("kmu_news", "sitemap_index.xml", "urlset"),
        ("kmu_news", "sitemap_posts_uk_2021_2026_excerpt.xml", "urlset"),
        ("kmu_news", "sitemap_posts_uk_2016_2021_excerpt.xml", "urlset"),
        ("kmu_news", "sitemap_posts_en_excerpt.xml", "urlset"),
        ("kmu_news", "npa_sitemap_excerpt.xml", "urlset"),
        ("diia_catalog", "sitemap_index.xml", "sitemapindex"),
        ("diia_catalog", "sitemap_services.xml", "urlset"),
        ("diia_catalog", "sitemap_categories.xml", "urlset"),
        ("project_sites", "center_sitemap.xml", "urlset"),
        ("ministry_news", "sitemap_latest100.xml", "urlset"),
    ],
)
def test_sitemap_fixtures_parse_every_entry(collector: str, name: str, kind: str) -> None:
    sitemap = parse_sitemap(fixture_bytes(collector, name))
    assert sitemap.kind == kind
    assert len(sitemap.entries) == _loc_count(collector, name)
    assert all(entry.loc.startswith("http") for entry in sitemap.entries)


def test_lastmod_is_kept_as_written() -> None:
    sitemap = parse_sitemap(fixture_bytes("diia_catalog", "sitemap_services.xml"))
    first = sitemap.entries[0]
    text = fixture_text("diia_catalog", "sitemap_services.xml")
    assert first.lastmod is not None and f"<lastmod>{first.lastmod}</lastmod>" in text
    assert first.lastmod_date == first.lastmod[:10]


def test_entries_without_lastmod_and_odd_lastmod_values() -> None:
    sitemap = parse_sitemap(fixture_bytes("diia_catalog", "sitemap_index.xml"))
    assert all(entry.lastmod is None and entry.lastmod_date is None for entry in sitemap.entries)
    assert SitemapEntry("https://example.org/", "2020-02-30").lastmod_date is None
    assert SitemapEntry("https://example.org/", "soon").lastmod_date is None
    assert SitemapEntry("https://example.org/", "2020-02-03").lastmod_date == "2020-02-03"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"<html><body>not found</body></html>", "neither urlset"),
        (b"<urlset><url><lastmod>2020-01-01</lastmod></url></urlset>", "no loc"),
        (b"not xml", "not well-formed"),
    ],
)
def test_malformed_sitemaps_raise(body: bytes, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parse_sitemap(body)


def test_the_usf_soft_404_is_not_a_sitemap() -> None:
    with pytest.raises(ParseError):
        parse_sitemap(fixture_bytes("project_sites", "usf_sitemap_soft404.html"))
