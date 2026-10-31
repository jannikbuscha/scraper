"""C4b ``kmu_news``: the sitemap and page parsers, the discovery rules and the recall
sample (docs/COLLECTORS.md §8.4, §12.2), on the fixtures of
``backend/tests/fixtures/kmu_news/`` (no database, no network). Every expected value is read
from those fixtures."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mdt.collectors.base import Candidate, FatalRunError, Snapshot
from mdt.collectors.kmu_news import COLLECTOR, Options, recall_sample
from mdt.collectors.kmu_news_pages import (
    Entry,
    key_of,
    parse_news_page,
    parse_post_sitemap,
    parse_sitemap_index,
    relevance,
)
from mdt.collectors.parsing import ParseError
from mdt.collectors.tagger import Alias, AliasIndex
from tests.collectors.thedigital_helpers import fixture_snapshot

FOCAL = "org_example_focal"
KEYWORDS = [
    "mincifr",
    "cifrovoyi-transformaciyi",
    "ministerstv[a-z]*-cifrov",
    "mintsyfr",
    "tsyfrovoi-transformatsii",
    "ministerstv[a-z]*-tsyfrov",
    "fedorov",
    r"\bdiia\b",
    r"\bdiya\b",
]
OPTIONS = Options.of({"keywords": KEYWORDS})
SITE = "https://www.kmu.gov.ua"


def snapshot(name: str) -> Snapshot:
    return fixture_snapshot("kmu_news", name)


def parse(snap: Snapshot, focal: str | None = FOCAL) -> tuple[Candidate, list[tuple[str, str]]]:
    result = parse_news_page(snap, focal_org_id=focal, default_licence="unknown")
    (candidate,) = result.candidates
    return candidate, result.warnings


def with_body(name: str, old: str, new: str) -> Snapshot:
    """A fixture page with one text replaced (a derived variant, kept in memory)."""
    base = snapshot(name)
    text = base.body.decode("utf-8")
    assert old in text
    body = text.replace(old, new, 1).encode("utf-8")
    return replace(base, body=body, size=len(body))


def entries(name: str, language: str) -> list[Entry]:
    return parse_post_sitemap(snapshot(name), language)


# --------------------------------------------------------------------------------------
# Sitemaps
# --------------------------------------------------------------------------------------


def test_the_sitemap_index_lists_the_post_sitemaps() -> None:
    ukrainian, english = parse_sitemap_index(snapshot("sitemap_index"))
    assert ukrainian == [f"{SITE}/sitemap-rainlab-blog-models-post-{n}.xml" for n in (1, 2, 3)]
    assert english == [f"{SITE}/en/sitemap-rainlab-blog-models-post-1.xml"]


def test_a_sitemap_index_without_post_sitemaps_is_a_parse_error() -> None:
    npa = snapshot("npa_sitemap_excerpt")  # a urlset of act pages, no child sitemaps
    with pytest.raises(ParseError, match="no Ukrainian post sitemap"):
        parse_sitemap_index(npa)


def test_post_sitemap_entries_keep_their_order_and_lastmod() -> None:
    recent = entries("sitemap_posts_uk_2021_2026_excerpt", "uk")
    older = entries("sitemap_posts_uk_2016_2021_excerpt", "uk")
    english = entries("sitemap_posts_en_excerpt", "en")
    assert (len(recent), len(older), len(english)) == (8, 20, 5)
    first = recent[0]
    assert (
        first.key
        == "uk:redyzain-hrantovoi-prohramy-dlia-pererobnykh-pidpryiemstv-uriad-onovyv-umovy"
    )
    assert first.url == f"{SITE}/news/{first.slug}"
    assert (first.lastmod, first.day) == ("2026-10-28T18:45:00+02:00", "2026-10-28")
    assert (
        english[3].key == "en:uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi"
    )
    assert english[3].url == f"{SITE}/en/news/{english[3].slug}"


def test_entries_of_the_other_language_and_other_pages_are_skipped() -> None:
    assert entries("sitemap_posts_en_excerpt", "uk") == []
    assert entries("sitemap_posts_uk_2016_2021_excerpt", "en") == []
    # Act pages (/npas/, robots-disallowed) are never news entries, so never requested.
    assert entries("npa_sitemap_excerpt", "uk") == []


def test_a_post_sitemap_must_be_a_urlset() -> None:
    index = replace(
        snapshot("sitemap_index"),
        body=b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>',
    )
    with pytest.raises(ParseError, match="urlset"):
        parse_post_sitemap(index, "uk")


# --------------------------------------------------------------------------------------
# Window and keywords
# --------------------------------------------------------------------------------------


def test_keyword_candidates_in_the_window_in_both_transliteration_styles() -> None:
    found = [
        entry.slug
        for name in ("sitemap_posts_uk_2021_2026_excerpt", "sitemap_posts_uk_2016_2021_excerpt")
        for entry in entries(name, "uk")
        if OPTIONS.in_window(entry) and OPTIONS.keyword(entry)
    ]
    assert found == [
        "vid-shi-asystenta-v-dii-do-suputnykovoho-zviazku-ta-oboronnykh-tekhnolohii-pidsumky-mintsyfry-u-2025-rotsi",
        "vidmovitisya-vid-rosijskoyi-muziki-pidtrimati-ukrayinsku-armiyu-mincifri-z-partnerami-zapustili-proekt-dlya-borotbi-z-propagandoyu",
        "wi-fi-v-ukryttiakh-ta-it-kursy-mykhailo-fedorov-pro-osvitni-initsiatyvy-mintsyfry-pid-chas-viiny",
        "mincifri-zapustit-nacionalnu-veb-platformu-centriv-nadannya-administrativnih-poslug",
        "mincifri-z-ukrayinskimi-zirkami-pidtrimali-onlajn-proekt-sluhaj-dlya-pidgotovki-do-zno",
        "uryad-sproshchuye-mehanizmi-nadannya-poslug-vpo-za-dopomogoyu-mobilnogo-zastosunku-diya",
        "mihajlo-fedorov-na-diia-summit-do-2022-roku-na-vsij-teritoriyi-ukrayini-bude-4g-internet",
        "komanda-ministerstva-cifrovoyi-transformaciyi-prezentuvala-proyekti-z-cifrovoyi-osviti-ta-rozvitku-malogo-ta-serednogo-biznesu",
        "uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi",
    ]


def test_diya_matches_only_as_a_word_and_old_entries_are_outside_the_window() -> None:
    older = {entry.slug: entry for entry in entries("sitemap_posts_uk_2016_2021_excerpt", "uk")}
    # "diyalnosti" contains "diya" but not as a word.
    onovleno = next(slug for slug in older if slug.startswith("onovleno-pokazniki"))
    assert "diyalnosti" in onovleno and not OPTIONS.keyword(older[onovleno])
    assert not OPTIONS.in_window(older["248754188"])  # lastmod 2016-01-08
    windowed = Options.of({"keywords": KEYWORDS, "window_to": "2019-12-31"})
    assert windowed.in_window(
        older["uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi"]
    )
    assert not windowed.in_window(
        older[
            "uryad-sproshchuye-mehanizmi-nadannya-poslug-vpo-za-dopomogoyu-mobilnogo-zastosunku-diya"
        ]
    )


def test_an_entry_without_lastmod_is_never_in_a_window() -> None:
    entry = Entry("uk", "example-news", f"{SITE}/news/example-news")
    assert not OPTIONS.in_window(entry) and not OPTIONS.in_recall_window(entry)


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"keywords": []},
        {"keywords": ["("]},
        {"keywords": KEYWORDS, "window_from": "29.08.2019"},
        {"keywords": KEYWORDS, "recall_to": None},
    ],
)
def test_malformed_options_fail_the_run(options: dict[str, object]) -> None:
    with pytest.raises(FatalRunError):
        Options.of(options)


# --------------------------------------------------------------------------------------
# Recall sample
# --------------------------------------------------------------------------------------


def nonkeyword_recall_entries() -> list[Entry]:
    return [
        entry
        for name in ("sitemap_posts_uk_2021_2026_excerpt", "sitemap_posts_uk_2016_2021_excerpt")
        for entry in entries(name, "uk")
        if OPTIONS.in_recall_window(entry) and not OPTIONS.keyword(entry)
    ]


def test_the_recall_population_is_the_non_keyword_window() -> None:
    population = nonkeyword_recall_entries()
    assert len(population) == 14
    assert all("2019-09-01" <= (entry.day or "") <= "2022-02-23" for entry in population)


def test_the_same_seed_draws_the_same_sample_whatever_the_input_order() -> None:
    population = nonkeyword_recall_entries()
    first = recall_sample(population, 5, seed=1)
    assert len(first) == 5 and len({entry.key for entry in first}) == 5
    assert recall_sample(list(reversed(population)), 5, seed=1) == first
    assert recall_sample(population, 3, seed=1) == first[:3]
    others = {tuple(recall_sample(population, 5, seed=seed)) for seed in range(2, 7)}
    assert any(sample != tuple(first) for sample in others)
    assert recall_sample(population, 100, seed=1) == recall_sample(population, 14, seed=1)
    assert recall_sample(population, 0, seed=1) == []


# --------------------------------------------------------------------------------------
# News pages
# --------------------------------------------------------------------------------------


def test_a_ukrainian_page_of_the_ministry() -> None:
    candidate, warnings = parse(snapshot("news_uk_2019_regulation"))
    slug = "uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi"
    assert (candidate.key, candidate.external_id) == (f"uk:{slug}", f"uk:{slug}")
    assert candidate.label == "Уряд затвердив Положення про Міністерство цифрової трансформації"
    assert candidate.fields == {
        "doc_type": "news",
        "title": candidate.label,
        "url": f"{SITE}/news/{slug}",
        "publisher": "www.kmu.gov.ua",
        "publisher_org_id": FOCAL,
        "language": "uk",
        "license": "cc_by_4_0",
        "published": "2019-09-18",
        "published_basis": "stated_in_source",
        "published_text": "опубліковано 18 вересня 2019 року о 15:50",
        "published_at_utc": "2019-09-18T12:50:00.000000Z",  # Kyiv summer time, UTC+3
    }
    assert candidate.details == {
        "publishing_body": "Міністерство цифрової трансформації України",
        "publishing_body_hosts": ["thedigital.gov.ua"],
        "ministry": True,
        "topics": ["Засідання Уряду", "Інновації"],
    }
    assert candidate.extraction_method == "selector"
    assert candidate.text_snapshot_id == candidate.evidence.raw_snapshot_id
    assert candidate.text is not None
    assert candidate.text.startswith("Кабінет Міністрів України затвердив постанову")
    assert "Михайло Федоров" in candidate.text
    assert "Попередня" not in candidate.text  # the navigation is not part of the text
    assert "Creative Commons" not in candidate.text  # nor the footer
    assert warnings == []


def test_an_english_page_of_the_ministry() -> None:
    candidate, _ = parse(snapshot("news_en_2019_regulation"))
    assert (
        candidate.key == "en:uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi"
    )
    assert candidate.label == (
        "Government endorses the Regulation on the Ministry of Digital Transformation"
    )
    assert candidate.fields["language"] == "en"
    assert candidate.fields["license"] == "cc_by_4_0"  # the English footer sentence
    assert candidate.fields["published_text"] == "posted 18 September 2019 15:50"
    assert candidate.fields["published_at_utc"] == "2019-09-18T12:50:00.000000Z"
    assert candidate.fields["publisher_org_id"] == FOCAL
    assert candidate.details["publishing_body"] == "Ministry of Digital Transformation of Ukraine"
    assert candidate.details["publishing_body_hosts"] == []
    assert candidate.details["topics"] == ["Government session", "IT", "Reforms"]


def test_a_page_of_another_body_has_no_focal_publisher() -> None:
    candidate, _ = parse(snapshot("news_uk_2020_other_body"))
    assert candidate.details["publishing_body"] == "Міністерство соціальної політики України"
    assert candidate.details["publishing_body_hosts"] == ["msp.gov.ua"]
    assert candidate.details["ministry"] is False
    assert "publisher_org_id" not in candidate.fields
    assert candidate.fields["published"] == "2020-10-05"


def test_without_a_focal_organisation_no_publisher_org_id_is_set() -> None:
    candidate, _ = parse(snapshot("news_uk_2019_regulation"), focal=None)
    assert "publisher_org_id" not in candidate.fields


def test_the_duplicate_pair_page_dates_its_item() -> None:
    candidate, _ = parse(snapshot("news_uk_2019_komanda_duplicate_pair"))
    assert candidate.fields["published_text"] == "опубліковано 11 жовтня 2019 року о 17:48"
    assert candidate.fields["published_at_utc"] == "2019-10-11T14:48:00.000000Z"


@pytest.mark.parametrize(
    "name",
    ["news_uk_2025_playcity", "news_uk_2025_year_review", "news_en_2025_plans"],
)
def test_recent_pages_parse(name: str) -> None:
    candidate, warnings = parse(snapshot(name))
    assert candidate.details["ministry"] is True and warnings == []
    assert candidate.text and len(candidate.text) > 500


def test_relevance_by_publishing_body_or_alias() -> None:
    ministry, _ = parse(snapshot("news_uk_2019_regulation"))
    other, _ = parse(snapshot("news_uk_2020_other_body"))
    empty = AliasIndex([])
    assert relevance(ministry, empty) == "publishing_body"
    assert relevance(other, empty) is None
    # The title of the page ends with the word "Дія"; an alias with that text keeps it.
    assert relevance(other, AliasIndex([Alias("prj_example", "Дія")])) == "alias_match"
    assert relevance(other, AliasIndex([Alias("prj_example", "Example alias")])) is None


def test_the_volatility_pair_gives_identical_candidates() -> None:
    first = parse(snapshot("news_en_2019_regulation"))
    refetch = parse(snapshot("news_en_2019_regulation_refetch"))
    assert (
        snapshot("news_en_2019_regulation").body != snapshot("news_en_2019_regulation_refetch").body
    )
    assert first == refetch


def test_a_bot_manager_script_never_reaches_the_candidate() -> None:
    # A synthetic stand-in for the inline bot-manager script removed from the excerpts; its
    # token is base64 of "example-id$192.0.2.1" (a documentation address).
    script = (
        '<script>window.__uzdbm_1 = "example-1"; '
        'window.__uzdbm_2 = "ZXhhbXBsZS1pZCQxOTIuMC4yLjE=";</script>\n</body>'
    )
    variant = with_body("news_en_2019_regulation_refetch", "</body>", script)
    candidate, _ = parse(variant)
    assert candidate == parse(snapshot("news_en_2019_regulation"))[0]
    assert "uzdbm" not in repr(candidate)


def test_an_ambiguous_kyiv_time_keeps_the_date_without_utc() -> None:
    variant = with_body(
        "news_uk_2019_regulation",
        "18 вересня 2019\n                року о\n                15:50",
        "31 жовтня 2021 року о 03:30",
    )
    candidate, warnings = parse(variant)
    assert candidate.fields["published"] == "2021-10-31"
    assert "published_at_utc" not in candidate.fields
    assert [code for code, _ in warnings] == ["ambiguous_time"]


def test_a_page_without_a_date_has_no_publication_fields() -> None:
    variant = with_body("news_uk_2020_other_body", "опубліковано", "оновлено")
    candidate, warnings = parse(variant)
    assert not {"published", "published_basis", "published_text"} & set(candidate.fields)
    assert [code for code, _ in warnings] == ["invalid_value"]


def test_a_page_without_header_still_parses_with_a_warning() -> None:
    variant = with_body("news_uk_2020_other_body", 'class="page_title-desc"', 'class="example"')
    candidate, warnings = parse(variant)
    assert candidate.details["publishing_body"] is None and candidate.details["ministry"] is False
    assert [code for code, _ in warnings] == ["invalid_value"]


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('<h1 class="heading-1">', '<h2 class="heading-1">', "no h1"),
        ('class="editor-content"', 'class="example-content"', "no div.editor-content"),
    ],
)
def test_missing_structure_raises_parse_errors(old: str, new: str, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parse(with_body("news_uk_2020_other_body", old, new))


def test_a_404_is_not_found_and_other_urls_are_no_news_pages() -> None:
    gone = replace(snapshot("news_uk_2019_regulation"), http_status=404)
    assert parse_news_page(gone, focal_org_id=None, default_licence=None).not_found
    assert key_of(f"{SITE}/news/example-news") == "uk:example-news"
    assert key_of(f"{SITE}/en/news/example-news") == "en:example-news"
    with pytest.raises(ParseError):
        key_of(f"{SITE}/npas/example-act")
    with pytest.raises(ParseError):
        key_of("https://example.org/news/example-news")


def test_the_collector_supports_the_kmu_parameters() -> None:
    assert COLLECTOR.NAME == "kmu_news"
    assert set(COLLECTOR.PARAMS) == {"limit", "refetch", "recall_sample", "recall_seed"}
    assert COLLECTOR.DECLARATION["document"].match_rules == ("document",)
    assert "source_record_at" not in COLLECTOR.DECLARATION["document"].writes
