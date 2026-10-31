"""Alias tagging and event suggestions (collectors/tagger.py, docs/COLLECTORS.md §7.6-§7.7).

All aliases and texts are synthetic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mdt.collectors import registry
from mdt.collectors.base import Outcome
from mdt.collectors.event_patterns import parse_event_patterns
from mdt.collectors.tagger import (
    COLLECTOR,
    Alias,
    AliasIndex,
    AliasMatch,
    LinkSuggestion,
    load_alias_index,
    suggest_events,
)
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.revisions import apply_change, soft_delete
from tests.conftest import Db
from tests.helpers import create_project, create_service

PATTERNS = parse_event_patterns(
    {
        "version": 1,
        "patterns": [
            {"id": "launch_uk", "event_type": "launch", "lang": "uk", "stems": ["запуст"]},
            {"id": "launch_uk_2", "event_type": "launch", "lang": "uk", "stems": ["запрацю"]},
            {
                "id": "beta_uk",
                "event_type": "beta_launch",
                "lang": "uk",
                "all_of": ["тестов", "режим"],
            },
            {"id": "launch_en", "event_type": "launch", "lang": "en", "phrases": ["went live"]},
        ],
    }
)


def _spans(index: AliasIndex, text: str) -> list[tuple[str, str]]:
    return [(match.subject_id, text[match.start : match.end]) for match in index.matches(text)]


def test_the_longest_match_wins_at_the_same_place() -> None:
    index = AliasIndex([Alias("prj_a", "Дія"), Alias("prj_b", "Дія.Бізнес")])
    text = "Нова послуга Дія.Бізнес і застосунок Дія."
    assert _spans(index, text) == [("prj_b", "Дія.Бізнес"), ("prj_a", "Дія")]


def test_overlapping_matches_keep_the_longer_one_wherever_it_starts() -> None:
    index = AliasIndex([Alias("prj_a", "Example City"), Alias("prj_b", "City Portal")])
    assert _spans(index, "the Example City Portal") == [("prj_a", "Example City")]


def test_equal_spans_of_several_subjects_all_count() -> None:
    index = AliasIndex([Alias("prj_a", "Example"), Alias("svc_b", "Example")])
    assert _spans(index, "An Example.") == [("prj_a", "Example"), ("svc_b", "Example")]


def test_case_sensitivity() -> None:
    index = AliasIndex([Alias("prj_a", "Diia"), Alias("prj_b", "engine", case_sensitive=False)])
    assert _spans(index, "diia DIIA Diia ENGINE Engine") == [
        ("prj_a", "Diia"),
        ("prj_b", "ENGINE"),
        ("prj_b", "Engine"),
    ]


def test_matches_need_word_boundaries() -> None:
    index = AliasIndex([Alias("prj_a", "Дія"), Alias("prj_b", "CDTO")])
    text = "Дія2 xДія Дія, (Дія) CDTOs CDTO-кампус"
    assert _spans(index, text) == [("prj_a", "Дія"), ("prj_a", "Дія"), ("prj_b", "CDTO")]


def test_no_match_of_an_inflected_form_without_an_inflection_alias() -> None:
    plain = AliasIndex([Alias("prj_a", "Дія")])
    assert _spans(plain, "У Дії з'явилася послуга") == []
    inflected = AliasIndex([Alias("prj_a", "Дія"), Alias("prj_a", "Дії")])
    assert _spans(inflected, "У Дії з'явилася послуга") == [("prj_a", "Дії")]


def test_exclude_phrases_drop_covered_matches_only() -> None:
    index = AliasIndex(
        [Alias("prj_a", "Example", case_sensitive=False, exclude_patterns=("example city",))]
    )
    text = "The EXAMPLE CITY office and the example app"
    assert _spans(index, text) == [("prj_a", "example")]


def test_an_excluded_match_does_not_block_other_aliases() -> None:
    index = AliasIndex(
        [Alias("prj_a", "City Hall", exclude_patterns=("Old City Hall",)), Alias("prj_b", "Hall")]
    )
    assert _spans(index, "Old City Hall") == [("prj_b", "Hall")]


def test_apostrophe_and_dash_variants_match_after_normalisation() -> None:
    index = AliasIndex([Alias("prj_a", "Зʼєднання"), Alias("prj_b", "Е-послуги")])
    text = "Програма З'єднання та Е–послуги"
    assert [subject for subject, _ in _spans(index, text)] == ["prj_a", "prj_b"]


def test_length_changing_case_folding_keeps_offsets_right() -> None:
    index = AliasIndex([Alias("prj_a", "strasse", case_sensitive=False)])
    text = "Die STRAẞE und die Straße"
    matches = index.matches(text)
    assert [text[match.start : match.end] for match in matches] == ["STRAẞE", "Straße"]


def test_aliases_without_letters_or_digits_are_ignored() -> None:
    index = AliasIndex([Alias("prj_a", " - "), Alias("prj_a", "")])
    assert len(index) == 0
    assert index.matches("a - b") == []


def test_records_give_aliases_and_names() -> None:
    index = AliasIndex.from_records(
        [
            {
                "id": "prj_a",
                "aliases": [
                    {"text": "Ex", "case_sensitive": False, "exclude_patterns": ["ex libris"]}
                ],
                "name_en": "Example Platform",
                "name_uk": "Приклад",
            },
            {"id": "svc_b", "aliases": [], "name_en": None, "name_uk": "Послуга прикладу"},
        ]
    )
    text = "EX, not Ex libris; Example Platform, приклад, Приклад, Послуга прикладу"
    assert _spans(index, text) == [
        ("prj_a", "EX"),
        ("prj_a", "Example Platform"),
        ("prj_a", "Приклад"),
        ("svc_b", "Послуга прикладу"),
    ]


def test_link_suggestions_per_subject() -> None:
    index = AliasIndex([Alias("prj_b", "Example"), Alias("prj_b", "EX"), Alias("prj_a", "Other")])
    text = ("x" * 130) + " Example one, EX two, Example three. Other."
    suggestions = index.suggest_links(text)
    assert [suggestion.subject_id for suggestion in suggestions] == ["prj_a", "prj_b"]
    example = suggestions[1]
    assert example.matched_aliases == ("EX", "Example")
    assert example.match_count == 3
    first = text.index("Example")
    assert example.snippet == " ".join(text[first - 120 : first + 7 + 120].split())
    assert suggestions[0] == LinkSuggestion(
        "prj_a", ("Other",), 1, " ".join(text[text.index("Other") - 120 :].split())
    )


def test_match_offsets_refer_to_the_normalised_text() -> None:
    # normalize_for_search drops the soft hyphen, so the match starts one place earlier.
    index = AliasIndex([Alias("prj_a", "Example")])
    assert index.matches("a\u00ad b Example") == [AliasMatch("prj_a", "Example", 4, 11)]


# Event suggestions ---------------------------------------------------------------------


def test_a_sentence_with_an_alias_and_a_pattern_gives_one_suggestion_per_type() -> None:
    index = AliasIndex([Alias("prj_a", "Дія"), Alias("prj_b", "Дія.City")])
    text = (
        "Вступ без згадки.\n"
        "Дія.City запрацювала, і Дія запустила послугу в тестовому режимі. Інше речення."
    )
    suggestions = suggest_events(text, "uk", index, PATTERNS)
    keys = [(s.subject_id, s.event_type, s.pattern_id, s.matched_alias) for s in suggestions]
    assert keys == [
        ("prj_a", "launch", "launch_uk", "Дія"),
        ("prj_a", "beta_launch", "beta_uk", "Дія"),
        ("prj_b", "launch", "launch_uk", "Дія.City"),
        ("prj_b", "beta_launch", "beta_uk", "Дія.City"),
    ]
    sentence = "Дія.City запрацювала, і Дія запустила послугу в тестовому режимі."
    for suggestion in suggestions:
        assert text[suggestion.char_start : suggestion.char_end] == sentence
        assert suggestion.quote == sentence


def test_a_name_with_a_dot_does_not_split_the_sentence() -> None:
    index = AliasIndex([Alias("prj_c", "Дія.City")])
    text = "Резиденти Дія.City запустили сервіс."
    suggestions = suggest_events(text, "uk", index, PATTERNS)
    assert [(s.char_start, s.char_end) for s in suggestions] == [(0, len(text))]


def test_pattern_and_alias_must_share_a_sentence() -> None:
    index = AliasIndex([Alias("prj_a", "Example")])
    text = "Example is a platform. The team запустила it later."
    assert suggest_events(text, "uk", index, PATTERNS) == []


def test_patterns_apply_to_their_language_and_unknown_languages_get_all() -> None:
    index = AliasIndex([Alias("prj_a", "Example")])
    text = "Example went live. Example запустили."
    assert [s.pattern_id for s in suggest_events(text, "en", index, PATTERNS)] == ["launch_en"]
    assert [s.pattern_id for s in suggest_events(text, "uk", index, PATTERNS)] == ["launch_uk"]
    assert [s.pattern_id for s in suggest_events(text, None, index, PATTERNS)] == [
        "launch_en",
        "launch_uk",
    ]


def test_offsets_point_into_the_stored_text_with_leading_spaces_and_long_sentences() -> None:
    index = AliasIndex([Alias("prj_a", "Example")])
    long_sentence = "Example запустили " + "дуже " * 300 + "довге речення"
    text = f"   {long_sentence}"
    (suggestion,) = suggest_events(text, "uk", index, PATTERNS)
    assert suggestion.char_start == 3
    assert len(suggestion.quote) == 1000
    assert text[suggestion.char_start : suggestion.char_end] == suggestion.quote


# The built-in collector ------------------------------------------------------------------


class FakeTaggingContext:
    """A run context with ``tag_document`` that records the calls."""

    def __init__(self, documents: Sequence[Mapping[str, Any]], params: Mapping[str, Any]):
        self.documents = list(documents)
        self.params = dict(params)
        self.tagged: list[str] = []
        self.counts: dict[str, int] = {}
        self.cancel_after: int | None = None

    def live_records(self, entity_type: str, fields: Sequence[str]) -> list[dict[str, Any]]:
        assert entity_type == "document" and list(fields) == ["text_hash"]
        return [dict(document) for document in self.documents]

    def tag_document(self, document_id: str) -> Outcome:
        self.tagged.append(document_id)
        return Outcome("updated" if document_id.endswith("1") else "unchanged", document_id)

    def cancelled(self) -> bool:
        return self.cancel_after is not None and len(self.tagged) >= self.cancel_after

    def count(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n


DOCUMENTS = [
    {"id": "doc_1", "text_hash": "a"},
    {"id": "doc_2", "text_hash": None},
    {"id": "doc_3", "text_hash": "b"},
]


def test_the_collector_tags_every_document_with_a_text() -> None:
    ctx = FakeTaggingContext(DOCUMENTS, {})
    COLLECTOR.run(ctx)  # type: ignore[arg-type]
    assert ctx.tagged == ["doc_1", "doc_3"]
    assert ctx.counts == {"documents_selected": 2, "documents_tagged": 2, "documents_linked": 1}


def test_the_collector_tags_only_the_requested_documents() -> None:
    ctx = FakeTaggingContext(DOCUMENTS, {"document_ids": ["doc_3", "doc_2", "doc_9"]})
    COLLECTOR.run(ctx)  # type: ignore[arg-type]
    assert ctx.tagged == ["doc_3"]


def test_the_collector_stops_when_cancelled() -> None:
    ctx = FakeTaggingContext(DOCUMENTS, {})
    ctx.cancel_after = 1
    COLLECTOR.run(ctx)  # type: ignore[arg-type]
    assert ctx.tagged == ["doc_1"]


def test_the_collector_satisfies_the_registry() -> None:
    registry.check_collector("tagger", COLLECTOR)
    assert set(COLLECTOR.PARAMS) == {"document_ids"}
    assert registry.resolve("tagger") is COLLECTOR


# The alias index of the database ------------------------------------------------------


def test_load_alias_index_reads_live_projects_and_services(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Example Portal", name_uk=None)
        apply_change(
            session,
            "project",
            project.entity_id,
            {"aliases": [{"text": "EP", "case_sensitive": False}]},
            Actor.ui(),
        )
        service = create_service(session, project.entity_id, name_en="Example Service")
        gone = create_project(session, name_en="Deleted Example")
        soft_delete(session, "project", gone.entity_id, Actor.ui())
        with read_transaction(session):
            index = load_alias_index(session)
    text = "ep, Example Portal, Example Service, Deleted Example"
    subjects = [subject for subject, _ in _spans(index, text)]
    assert subjects.count(project.entity_id) == 2
    assert service.entity_id in subjects
    assert gone.entity_id not in subjects


def test_the_real_codebook_file_loads(tmp_path: Path) -> None:
    from mdt.collectors.event_patterns import load_event_patterns

    codebook = Path(__file__).resolve().parents[3] / "codebook"
    patterns = load_event_patterns(codebook)
    assert {pattern.lang for pattern in patterns.patterns} == {"uk", "en"}
