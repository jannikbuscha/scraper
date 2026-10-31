"""``codebook/collector_mappings.yaml`` (collectors/mappings.py, docs/COLLECTORS.md §7.9)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from mdt.collectors.base import FatalRunError
from mdt.collectors.mappings import (
    MappingError,
    MappingResult,
    active_codes,
    label_key,
    load_mapping,
    load_mappings,
    mapping_for_run,
    parse_mappings,
)

CODEBOOK = Path(__file__).resolve().parents[3] / "codebook"


def _vocabulary_codes(name: str) -> set[str]:
    data = yaml.safe_load((CODEBOOK / f"{name}.yaml").read_text("utf-8"))
    return {term["code"] for term in data["terms"] if term.get("active", True)}


def test_every_target_code_is_an_active_term_of_the_real_codebook() -> None:
    for mapping in load_mappings(CODEBOOK).values():
        mapping.check_codes(_vocabulary_codes(mapping.vocabulary))


def test_the_document_kinds() -> None:
    kinds = load_mapping(CODEBOOK, "ministry_document_kinds")
    assert (kinds.collector, kinds.vocabulary, kinds.fallback) == (
        "ministry_news",
        "doc_type",
        "other",
    )
    assert len(kinds.labels) == 36
    assert kinds.lookup("regulation") == MappingResult("other", "mapped")
    assert kinds.lookup("decision") == MappingResult("legal_act", "mapped")
    assert kinds.lookup("plan") == MappingResult("strategy_policy", "mapped")
    assert kinds.lookup("dashbord") == MappingResult("statistics", "mapped")
    assert kinds.lookup("audit-report") == MappingResult("report", "mapped")
    assert kinds.lookup("a-new-kind") == MappingResult("other", "fallback")


def test_the_diia_channels() -> None:
    channels = load_mapping(CODEBOOK, "diia_portal_channels")
    assert (channels.collector, channels.vocabulary, channels.fallback) == (
        "diia_catalog",
        "channel",
        None,
    )
    assert channels.lookup("Онлайн") == MappingResult("portal", "mapped")
    assert channels.lookup("  ОФЛАЙН ") == MappingResult("physical", "mapped")
    assert channels.lookup("Результат") == MappingResult(None, "ignored")
    assert channels.lookup("Телефоном") == MappingResult(None, "unmapped")


def test_label_keys_fold_and_collapse() -> None:
    assert label_key(" Як  отримати ПОСЛУГУ ") == "як отримати послугу"


def _file(**mapping: Any) -> dict[str, Any]:
    entry = {"collector": "example", "vocabulary": "doc_type", "codes": {"news": ["News"]}}
    entry.update(mapping)
    return {"version": 1, "mappings": {"example_mapping": entry}}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ("text", "expected a mapping"),
        ({"version": 2, "mappings": {}}, "version must be 1"),
        ({"version": 1, "vocabulary": "x", "mappings": {}}, "vocabulary key"),
        ({"version": 1, "mappings": {}}, "non-empty mapping"),
        ({"version": 1, "mappings": {"Bad Name": {}}}, "not a mapping name"),
        ({"version": 1, "mappings": {"m": []}}, "must be a mapping"),
        (_file(extra=1), "unknown keys"),
        (_file(collector=""), "collector"),
        (_file(vocabulary="Doc Type"), "vocabulary"),
        (_file(fallback="Other"), "fallback must be a code"),
        (_file(codes={}), "codes must map"),
        (_file(codes={"Bad": ["x"]}), "is not a code"),
        (_file(codes={"news": []}), "non-empty list"),
        (_file(codes={"news": [" "]}), "non-empty strings"),
        (_file(codes={"news": ["News"], "other": ["NEWS"]}), "mapped twice"),
        (_file(ignore="News"), "non-empty list"),
        (_file(ignore=["news"]), "both mapped and ignored"),
    ],
)
def test_malformed_files_are_refused(data: Any, message: str) -> None:
    with pytest.raises(MappingError, match=message):
        parse_mappings(data)


def test_inactive_or_missing_codes_are_refused() -> None:
    mapping = parse_mappings(_file(fallback="other"))["example_mapping"]
    assert mapping.target_codes == {"news", "other"}
    mapping.check_codes({"news", "other", "report"})
    with pytest.raises(MappingError, match="not active terms of doc_type: other"):
        mapping.check_codes({"news"})


def test_missing_broken_and_unknown_mappings(tmp_path: Path) -> None:
    with pytest.raises(MappingError, match="missing"):
        load_mappings(tmp_path)
    (tmp_path / "collector_mappings.yaml").write_text("mappings: [", encoding="utf-8")
    with pytest.raises(MappingError, match="invalid YAML"):
        load_mappings(tmp_path)
    (tmp_path / "collector_mappings.yaml").write_text(yaml.safe_dump(_file()), encoding="utf-8")
    with pytest.raises(MappingError, match="no mapping nothing"):
        load_mapping(tmp_path, "nothing")


class TermsContext:
    """A run context that knows the vocabulary terms and a codebook directory."""

    def __init__(self, terms: Sequence[dict[str, Any]], codebook: Path) -> None:
        self.terms = list(terms)
        self.settings = SimpleNamespace(codebook_path=codebook)

    def live_records(self, entity_type: str, fields: Sequence[str]) -> list[dict[str, Any]]:
        assert entity_type == "vocabulary_term"
        return [dict(term) for term in self.terms]


def test_active_codes_come_from_term_records() -> None:
    terms = [
        {"vocabulary": "doc_type", "code": "news", "active": True},
        {"vocabulary": "doc_type", "code": "old", "active": False},
        {"vocabulary": "channel", "code": "portal", "active": True},
    ]
    assert active_codes(terms, "doc_type") == {"news"}


def test_mapping_for_run_checks_the_terms(tmp_path: Path) -> None:
    (tmp_path / "collector_mappings.yaml").write_text(yaml.safe_dump(_file()), encoding="utf-8")
    good = TermsContext([{"vocabulary": "doc_type", "code": "news", "active": True}], tmp_path)
    mapping = mapping_for_run(good, "example_mapping")  # type: ignore[arg-type]
    assert mapping.lookup("news").code == "news"
    inactive = TermsContext([{"vocabulary": "doc_type", "code": "news", "active": False}], tmp_path)
    with pytest.raises(FatalRunError, match="not active terms"):
        mapping_for_run(inactive, "example_mapping")  # type: ignore[arg-type]
    with pytest.raises(FatalRunError, match="no mapping"):
        mapping_for_run(good, "other_mapping")  # type: ignore[arg-type]
