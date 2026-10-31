"""Duplicate detection (collectors/duplicates.py, docs/COLLECTORS.md §7.8).

The calibration pair is read from the fixtures: the 2019 item of www.kmu.gov.ua and the same
item on thedigital.gov.ua (17:48 and 13:21, different slugs, both Ukrainian).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import insert

from mdt.collectors.duplicates import (
    DocumentInfo,
    DuplicatePair,
    ServiceInfo,
    containment,
    document_duplicates,
    document_pair,
    find_document_duplicates,
    find_service_duplicates,
    service_duplicates,
    title_key,
    word_shingles,
)
from mdt.collectors.parsing.dates import find_posted_datetime, from_iso_offset
from mdt.collectors.parsing.html_text import html_text, parse_html, remove_hidden
from mdt.collectors.parsing.texts import normalize_document_text, text_hash
from mdt.collectors.parsing.tiptap import tiptap_to_text
from mdt.collectors.parsing.turbostream import find_route, loader_data
from mdt.db.models import DocumentText
from mdt.db.session import read_transaction, write_transaction
from mdt.domain.actor import Actor
from mdt.domain.clock import utc_now
from mdt.domain.revisions import apply_change, soft_delete
from tests.conftest import Db
from tests.helpers import create_project, create_service
from tests.parsing.helpers import fixture_text


def _kmu(name: str) -> DocumentInfo:
    soup = parse_html(fixture_text("kmu_news", name))
    remove_hidden(soup)
    header = soup.select_one("div.page_title-desc")
    body = soup.select_one("div.editor-content")
    h1 = soup.find("h1")
    assert header is not None and body is not None and h1 is not None
    posted = find_posted_datetime(header.get_text(" "))
    assert posted is not None
    return DocumentInfo(
        id=f"doc_kmu_{name}",
        source_id="kmu_news",
        language="uk",
        published_start=posted.date,
        published_end=posted.date,
        title=h1.get_text(" "),
        text=html_text(body),
    )


def _ministry(name: str) -> DocumentInfo:
    _, data = find_route(loader_data(fixture_text("ministry_news", name)), ("article",))
    article = data["article"]
    published = from_iso_offset(article["publishedAt"]["iso8601"])
    assert published is not None
    return DocumentInfo(
        id=f"doc_min_{name}",
        source_id="ministry_news",
        language="uk",
        published_start=published.date,
        published_end=published.date,
        title=article["title"],
        text=tiptap_to_text(article.get("blocks")).text,
    )


KMU_2019 = "news_uk_2019_komanda_duplicate_pair.html"
MINISTRY_2019 = "news_article_2019.html"


def test_the_2019_pair_is_a_possible_duplicate() -> None:
    kmu, ministry = _kmu(KMU_2019), _ministry(MINISTRY_2019)
    pair = document_pair(kmu, ministry)
    assert pair is not None
    assert pair.basis == "title_date"
    assert (pair.subject_id, pair.related_id) == tuple(sorted([kmu.id, ministry.id]))
    assert pair.details == {"days_apart": 0}


def test_the_2019_pair_also_qualifies_by_text_containment() -> None:
    kmu, ministry = _kmu(KMU_2019), _ministry(MINISTRY_2019)
    assert kmu.text and ministry.text
    similarity = containment(word_shingles(kmu.text), word_shingles(ministry.text))
    assert similarity == pytest.approx(0.977, abs=0.001)
    pair = document_pair(kmu, replace(ministry, title="Another title"))
    assert pair is not None and pair.basis == "text" and pair.similarity == 0.977


def test_an_unrelated_pair_is_not_a_duplicate() -> None:
    kmu = _kmu("news_uk_2019_regulation.html")
    ministry = _ministry(MINISTRY_2019)
    # Close enough in time to be compared, but neither title nor text agree.
    ministry = replace(
        ministry, published_start=kmu.published_start, published_end=kmu.published_end
    )
    assert document_pair(kmu, ministry) is None


BASE = DocumentInfo(
    id="doc_a",
    source_id="one",
    language="uk",
    published_start="2020-05-10",
    published_end="2020-05-10",
    title="Example news item",
    text=None,
)


@pytest.mark.parametrize(
    ("other", "expected"),
    [
        (replace(BASE, id="doc_b", source_id="two"), True),
        (
            replace(
                BASE,
                id="doc_b",
                source_id="two",
                published_start="2020-05-11",
                published_end="2020-05-11",
            ),
            True,
        ),
        (
            replace(
                BASE,
                id="doc_b",
                source_id="two",
                published_start="2020-05-12",
                published_end="2020-05-12",
            ),
            False,
        ),
        (
            replace(
                BASE,
                id="doc_b",
                source_id="two",
                published_start="2020-05-01",
                published_end="2020-05-31",
            ),
            True,
        ),
        (replace(BASE, id="doc_b", source_id="one"), False),
        (replace(BASE, id="doc_b", source_id=None), True),
        (replace(BASE, id="doc_b", source_id="two", language="en"), False),
        (
            replace(BASE, id="doc_b", source_id="two", published_start=None, published_end=None),
            False,
        ),
        (replace(BASE, source_id="two"), False),
        (replace(BASE, id="doc_b", source_id="two", title="Example — news item!"), True),
        (replace(BASE, id="doc_b", source_id="two", title="Other news item"), False),
    ],
)
def test_document_preconditions_and_title_rule(other: DocumentInfo, expected: bool) -> None:
    assert (document_pair(BASE, other) is not None) is expected


def test_documents_without_language_are_never_compared() -> None:
    no_language = replace(BASE, language=None)
    assert document_pair(no_language, replace(no_language, id="doc_b", source_id="two")) is None


def test_title_keys_and_shingles() -> None:
    assert title_key("  «Дія.Бізнес»: НОВА   послуга! ") == "діябізнес нова послуга"
    assert title_key("...") == ""
    assert word_shingles("one two") == frozenset()
    assert word_shingles("One, two three FOUR") == {
        ("one", "two", "three"),
        ("two", "three", "four"),
    }
    assert containment(frozenset(), word_shingles("a b c")) == 0.0


def test_only_the_first_5000_words_count() -> None:
    shared = " ".join(f"w{index}" for index in range(5000))
    left = shared + " " + " ".join(f"x{index}" for index in range(3000))
    right = shared + " " + " ".join(f"y{index}" for index in range(3000))
    assert containment(word_shingles(left), word_shingles(right)) == 1.0


def test_empty_titles_never_match_by_title() -> None:
    a = replace(BASE, title="!!!")
    assert document_pair(a, replace(a, id="doc_b", source_id="two")) is None


def test_document_duplicates_lists_each_pair_once() -> None:
    b = replace(BASE, id="doc_b", source_id="two")
    pairs = document_duplicates([BASE, b], [BASE, b])
    assert pairs == [DuplicatePair("doc_a", "doc_b", "title_date", None, {"days_apart": 0})]


def test_services_with_the_same_folded_name_in_one_project() -> None:
    new = [ServiceInfo("svc_c", "prj_1", "Отримання ДОВІДКИ"), ServiceInfo("svc_x", "prj_1", None)]
    others = [
        ServiceInfo("svc_a", "prj_1", "отримання довідки"),
        ServiceInfo("svc_b", "prj_2", "Отримання довідки"),
        ServiceInfo("svc_c", "prj_1", "Отримання ДОВІДКИ"),
        ServiceInfo("svc_d", "prj_1", "Інша послуга"),
    ]
    assert service_duplicates(new, others) == [DuplicatePair("svc_a", "svc_c", "name")]


# Database helpers ---------------------------------------------------------------------


def _document(db: Db, title: str, source_id: str, published: str | None, text: str) -> str:
    normalized = normalize_document_text(text)
    digest = text_hash(normalized)
    with db.session() as session:
        with write_transaction(session):
            session.execute(
                insert(DocumentText)
                .values(
                    text_hash=digest,
                    text=normalized,
                    char_count=len(normalized),
                    created_at=utc_now(),
                )
                .prefix_with("OR IGNORE")
            )
        changes = {
            "title": title,
            "source_id": source_id,
            "language": "lang_a",  # a code of the synthetic test codebook
            "text_hash": digest,
            "published": published,
            "published_basis": "stated_in_source" if published else None,
        }
        return apply_change(session, "document", None, changes, Actor.system()).entity_id


def test_find_document_duplicates_reads_live_candidates(db: Db) -> None:
    text = "Synthetic news text about an example service " * 20
    a = _document(db, "Example item", "one", "2020-05-10", text)
    b = _document(db, "Another heading", "two", "2020-05-11", text)
    c = _document(db, "Example item", "two", "2020-05-13", "unrelated words only here")
    d = _document(db, "Example item", "three", "2020-05-09", "different words")
    e = _document(db, "Example item", "one", "2020-05-10", "same source as a")
    gone = _document(db, "Example item", "four", "2020-05-10", "deleted copy")
    with db.session() as session:
        soft_delete(session, "document", gone, Actor.ui())
        with read_transaction(session):
            pairs = find_document_duplicates(session, [a])
    found = {(pair.subject_id, pair.related_id): pair.basis for pair in pairs}
    assert found == {tuple(sorted([a, b])): "text", tuple(sorted([a, d])): "title_date"}
    assert c not in {id_ for pair in found for id_ in pair}
    assert e not in {id_ for pair in found for id_ in pair}


def test_find_document_duplicates_skips_documents_without_date(db: Db) -> None:
    a = _document(db, "Example item", "one", None, "text")
    _document(db, "Example item", "two", None, "text")
    with db.session() as session, read_transaction(session):
        assert find_document_duplicates(session, [a]) == []


def test_find_service_duplicates_reads_the_project_services(db: Db) -> None:
    with db.session() as session:
        project = create_project(session).entity_id
        other_project = create_project(session).entity_id
        first = create_service(session, project, name_uk="Послуга прикладу").entity_id
        second = create_service(session, project, name_uk="ПОСЛУГА прикладу").entity_id
        create_service(session, other_project, name_uk="Послуга прикладу")
        gone = create_service(session, project, name_uk="Послуга прикладу").entity_id
        soft_delete(session, "service", gone, Actor.ui())
        with read_transaction(session):
            pairs = find_service_duplicates(session, [second])
    assert pairs == [DuplicatePair(*sorted([first, second]), "name")]
