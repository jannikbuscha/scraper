"""Codebook files and parameters (DATA_MODEL §9)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from mdt.config import REPO_ROOT
from mdt.domain.vocab import (
    CodebookError,
    is_fixed_term,
    load_parameters,
    load_vocabulary_files,
    parameters_digest,
)
from tests import synthetic


def test_loader_skips_parameters_and_non_vocabulary_files(tmp_path: Path) -> None:
    synthetic.write_codebook(tmp_path)
    (tmp_path / "notes.yaml").write_text("just: data\n", encoding="utf-8")
    names = [vocabulary.name for vocabulary in load_vocabulary_files(tmp_path)]
    assert sorted(names) == sorted(synthetic.VOCABULARIES)
    assert "parameters" not in names


def test_loaded_terms_have_defaults(tmp_path: Path) -> None:
    (tmp_path / "example.yaml").write_text(
        "vocabulary: example\nterms:\n  - {code: one, label_en: One}\n", encoding="utf-8"
    )
    [vocabulary] = load_vocabulary_files(tmp_path)
    assert (vocabulary.label, vocabulary.multi, vocabulary.fixed_codes) == ("example", False, False)
    assert vocabulary.source_file == "example.yaml"
    assert vocabulary.terms[0]["active"] is True
    assert vocabulary.terms[0]["replaced_by"] is None


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("vocabulary: example\nterms: {code: one}\n", "terms must be a list"),
        ("vocabulary: example\nterms:\n  - just text\n", "must be a mapping"),
        ("vocabulary: example\nterms:\n  - {code: one}\n", "needs a code and label_en"),
        (
            "vocabulary: example\nterms:\n  - {code: one, label_en: One, x: 1}\n",
            "unknown term keys",
        ),
        ("vocabulary: [\n", "invalid YAML"),
    ],
)
def test_malformed_vocabulary_files(tmp_path: Path, content: str, message: str) -> None:
    (tmp_path / "example.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(CodebookError, match=message):
        load_vocabulary_files(tmp_path)


def test_duplicate_vocabularies(tmp_path: Path) -> None:
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text("vocabulary: same\nterms: []\n", encoding="utf-8")
    with pytest.raises(CodebookError, match="defined twice"):
        load_vocabulary_files(tmp_path)


def test_parameters_accept_dates_and_iso_strings(tmp_path: Path) -> None:
    synthetic.write_parameters(tmp_path, date(2011, 7, 15), date(2016, 3, 10))
    parameters = load_parameters(tmp_path)
    assert (parameters.ministry_founded, parameters.full_scale_invasion) == (
        date(2011, 7, 15),
        date(2016, 3, 10),
    )
    assert parameters.publication_timezone == "Europe/Kyiv"
    assert parameters.as_api() == {
        "ministry_founded": "2011-07-15",
        "full_scale_invasion": "2016-03-10",
    }
    (tmp_path / "parameters.yaml").write_text(
        'ministry_founded: "2012-01-02"\nfull_scale_invasion: "2013-04-05"\nunknown_key: 1\n',
        encoding="utf-8",
    )
    reloaded = load_parameters(tmp_path)
    assert reloaded.period.ministry_founded == date(2012, 1, 2)
    assert len(parameters_digest(tmp_path)) == 64


@pytest.mark.parametrize(
    "content",
    [
        "ministry_founded: 2016-03-10\nfull_scale_invasion: 2011-07-15\n",
        "ministry_founded: not a date\nfull_scale_invasion: 2016-03-10\n",
        "full_scale_invasion: 2016-03-10\n",
        "- a list\n",
    ],
)
def test_invalid_parameters(tmp_path: Path, content: str) -> None:
    (tmp_path / "parameters.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(CodebookError):
        load_parameters(tmp_path)


def test_missing_parameters(tmp_path: Path) -> None:
    with pytest.raises(CodebookError, match="missing"):
        load_parameters(tmp_path)


def test_real_codebook_loads() -> None:
    vocabularies = load_vocabulary_files(REPO_ROOT / "codebook")
    assert len(vocabularies) == 26
    assert sum(len(vocabulary.terms) for vocabulary in vocabularies) == 175
    fixed = {vocabulary.name for vocabulary in vocabularies if vocabulary.fixed_codes}
    assert fixed == {
        "verification_status",
        "screening_status",
        "date_basis",
        "date_precision",
        "period",
        "war_trajectory",
        "derived_reason",
    }
    event_types = next(v for v in vocabularies if v.name == "event_type")
    fixed_codes = {t["code"] for t in event_types.terms if t["attributes"].get("fixed") is True}
    assert fixed_codes == {"launch", "beta_launch", "first_archived"}
    parameters = load_parameters(REPO_ROOT / "codebook")
    assert parameters.ministry_founded < parameters.full_scale_invasion


def test_is_fixed_term() -> None:
    assert is_fixed_term(None, {"fixed": True})
    assert not is_fixed_term(None, {"fixed": "yes"})
    assert not is_fixed_term(None, None)


#: docs/CODEBOOK.md marks a draft addition in the definition; the YAML file marks it with
#: ``attributes.draft_addition`` instead (codebook/README.md).
DRAFT_MARKER = "➕ Draft addition: "


def documented_definitions(names: set[str]) -> dict[tuple[str, str], str]:
    """The definitions in the tables of docs/CODEBOOK.md, by (vocabulary, code).

    A table belongs to the vocabulary named in its first header cell, otherwise to the first
    vocabulary named in the heading above it; only tables with a definition column count.
    """
    result: dict[tuple[str, str], str] = {}
    heading: str | None = None
    header: list[str] | None = None
    text = (REPO_ROOT / "docs" / "CODEBOOK.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("#"):
            named = [name for name in re.findall(r"`([a-z_]+)`", line) if name in names]
            heading = named[0] if named else None
            header = None
            continue
        if not line.startswith("|"):
            header = None
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        first = header[0].strip("`")
        vocabulary = first if first in names else heading
        column = next((i for i, cell in enumerate(header) if "definition" in cell.lower()), None)
        code = re.fullmatch(r"`([a-z0-9_]+)`", cells[0])
        if vocabulary is not None and column is not None and code is not None:
            result[(vocabulary, code.group(1))] = cells[column]
    return result


def test_definitions_are_those_of_docs_codebook() -> None:
    # codebook/*.yaml copies its definitions from docs/CODEBOOK.md (codebook/README.md), so a
    # definition is corrected in both places together.
    vocabularies = {v.name: v for v in load_vocabulary_files(REPO_ROOT / "codebook")}
    documented = documented_definitions(set(vocabularies))
    # The derived values are documented completely (CODEBOOK §3).
    for name in ("period", "war_trajectory", "derived_reason"):
        assert {code for vocabulary, code in documented if vocabulary == name} == {
            term["code"] for term in vocabularies[name].terms
        }
    mismatches = []
    for (name, code), text in documented.items():
        term = next((t for t in vocabularies[name].terms if t["code"] == code), None)
        expected = text.replace("**", "")
        if expected.startswith(DRAFT_MARKER):
            expected = expected[len(DRAFT_MARKER) :]
            expected = expected[:1].upper() + expected[1:]
            if term is not None and term["attributes"].get("draft_addition") is not True:
                mismatches.append(f"{name}.{code}: draft addition without the attribute")
        if term is None or term["definition"] != expected:
            found = None if term is None else term["definition"]
            mismatches.append(f"{name}.{code}: CODEBOOK.md {expected!r}, YAML {found!r}")
    assert not mismatches, mismatches
