"""``codebook/event_patterns.yaml``: loading, validation and matching
(collectors/event_patterns.py, docs/COLLECTORS.md §7.7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from mdt.collectors.event_patterns import (
    EventPatternsError,
    load_event_patterns,
    parse_event_patterns,
    sentence_tokens,
)
from mdt.domain.vocab import load_vocabulary_files

CODEBOOK = Path(__file__).resolve().parents[3] / "codebook"
CODEBOOK_MD = Path(__file__).resolve().parents[3] / "docs" / "CODEBOOK.md"


def _one(**entry: Any) -> dict[str, Any]:
    return {"version": 1, "patterns": [{"id": "p", "event_type": "launch", "lang": "uk", **entry}]}


def test_the_codebook_file_is_valid_and_uses_event_types_of_the_vocabulary() -> None:
    patterns = load_event_patterns(CODEBOOK)
    vocabulary = yaml.safe_load((CODEBOOK / "event_type.yaml").read_text("utf-8"))
    codes = {term["code"] for term in vocabulary["terms"] if term.get("active", True)}
    assert patterns.unknown_event_types(codes) == []
    assert len({pattern.id for pattern in patterns.patterns}) == len(patterns.patterns)


def test_every_pattern_text_comes_from_the_codebook_phrase_list() -> None:
    section = CODEBOOK_MD.read_text("utf-8").split("## 4. Phrase list", 1)[1].split("\n## ", 1)[0]
    raw = yaml.safe_load((CODEBOOK / "event_patterns.yaml").read_text("utf-8"))
    for entry in raw["patterns"]:
        for key in ("stems", "phrases", "all_of"):
            for text in entry.get(key) or ():
                assert text.removesuffix("-") in section, text


def test_the_seed_does_not_read_the_file_as_a_vocabulary() -> None:
    names = {vocabulary.source_file for vocabulary in load_vocabulary_files(CODEBOOK)}
    assert "event_patterns.yaml" not in names
    assert "collector_mappings.yaml" not in names
    assert "event_type.yaml" in names


def test_tokens_are_folded_words_and_single_symbols() -> None:
    assert sentence_tokens("Уряд ухвалив Постанову № 12, Дія.City — З'явилася!") == [
        "уряд",
        "ухвалив",
        "постанову",
        "№",
        "12",
        ",",
        "дія",
        ".",
        "city",
        "-",
        "зʼявилася",
        "!",
    ]


@pytest.mark.parametrize(
    ("entry", "sentence", "expected"),
    [
        ({"stems": ["запуст"]}, "Мінцифри запустило сервіс", True),
        ({"stems": ["запуст"]}, "сервіс перезапустили", False),
        ({"stems": ["зʼявил"]}, "У Дії з'явилася послуга", True),
        ({"phrases": ["нова версія"]}, "Вийшла Нова версія застосунку", True),
        ({"phrases": ["нова версія"]}, "нова, версія", False),
        ({"phrases": ["доступн- для"]}, "Послуга доступна для ФОП", True),
        ({"phrases": ["доступн- для"]}, "доступна всім для", False),
        ({"phrases": ["постанова №"]}, "згідно з постанова № 5", True),
        ({"phrases": ["бета"]}, "Запустили бета-версію", True),
        ({"phrases": ["бета"]}, "Бетаверсія", False),
        ({"phrases": ["went live"]}, "The portal went live today", True),
        ({"phrases": ["went live"]}, "went to live", False),
        ({"all_of": ["тестов", "режим"]}, "працює в тестовому режимі", True),
        ({"all_of": ["тестов", "режим"]}, "тестові дані", False),
    ],
)
def test_matching_semantics(entry: dict[str, Any], sentence: str, expected: bool) -> None:
    patterns = parse_event_patterns(_one(**entry))
    assert bool(patterns.matching(sentence, "uk")) is expected


def test_patterns_are_filtered_by_language() -> None:
    patterns = parse_event_patterns(
        {
            "version": 1,
            "patterns": [
                {"id": "a", "event_type": "launch", "lang": "uk", "stems": ["запуст"]},
                {"id": "b", "event_type": "launch", "lang": "en", "phrases": ["launched"]},
            ],
        }
    )
    assert [p.id for p in patterns.for_language("en")] == ["b"]
    assert [p.id for p in patterns.for_language(None)] == ["a", "b"]
    assert [p.id for p in patterns.matching("запустили, launched", None)] == ["a", "b"]
    assert patterns.matching("запустили", "en") == []


def test_unknown_event_types_are_listed() -> None:
    patterns = parse_event_patterns(_one(stems=["x"]))
    assert patterns.unknown_event_types({"launch"}) == []
    assert patterns.unknown_event_types({"beta_launch"}) == ["launch"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "expected a mapping"),
        ({"version": 2, "patterns": []}, "version must be 1"),
        ({"version": 1, "vocabulary": "x", "patterns": []}, "vocabulary key"),
        ({"version": 1, "patterns": []}, "non-empty list"),
        ({"version": 1, "patterns": ["x"]}, "must be a mapping"),
        (_one(stems=["x"], extra=1), "unknown keys"),
        (
            {"version": 1, "patterns": [{"id": "Bad Id", "event_type": "launch", "lang": "uk"}]},
            "id must be a code",
        ),
        (_one(), "needs stems, phrases or all_of"),
        (_one(stems=["two words"]), "single word"),
        (_one(stems="запуст"), "list of non-empty strings"),
        (_one(stems=[" "]), "list of non-empty strings"),
        (_one(all_of=["тестов"]), "at least two"),
        (_one(phrases=["- -"]), "has no words"),
        (_one(phrases=["-x-"]), "single word"),
        (
            {
                "version": 1,
                "patterns": [
                    {"id": "p", "event_type": "launch", "lang": "uk", "stems": ["a"]},
                    {"id": "p", "event_type": "launch", "lang": "uk", "stems": ["b"]},
                ],
            },
            "duplicate ids",
        ),
    ],
)
def test_malformed_files_are_refused(data: Any, message: str) -> None:
    with pytest.raises(EventPatternsError, match=message):
        parse_event_patterns(data)


def test_a_missing_or_broken_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(EventPatternsError, match="missing"):
        load_event_patterns(tmp_path)
    (tmp_path / "event_patterns.yaml").write_text("patterns: [", encoding="utf-8")
    with pytest.raises(EventPatternsError, match="invalid YAML"):
        load_event_patterns(tmp_path)


def test_a_changed_file_is_read_again(tmp_path: Path) -> None:
    path = tmp_path / "event_patterns.yaml"
    path.write_text(yaml.safe_dump(_one(stems=["a"])), encoding="utf-8")
    assert load_event_patterns(tmp_path).patterns[0].stems == ("a",)
    path.write_text(yaml.safe_dump(_one(stems=["bb"])), encoding="utf-8")
    assert load_event_patterns(tmp_path).patterns[0].stems == ("bb",)
