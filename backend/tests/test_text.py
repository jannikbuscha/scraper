"""Search normalisation, folding and sort keys (DATA_MODEL §10)."""

from __future__ import annotations

import sys
import unicodedata

import pytest

from mdt.domain.text import (
    APOSTROPHE,
    UKRAINIAN_ALPHABET,
    UNICODE_SPACES,
    fold,
    normalize_for_search,
    sortkey,
    sql_fold,
    sql_sortkey,
)

MODIFIER_APOSTROPHE = "\N{MODIFIER LETTER APOSTROPHE}"


@pytest.mark.parametrize(
    "apostrophe",
    [
        "'",
        "\N{RIGHT SINGLE QUOTATION MARK}",
        "\N{LEFT SINGLE QUOTATION MARK}",
        "`",
        "\N{ACUTE ACCENT}",
        "\N{MODIFIER LETTER PRIME}",
        MODIFIER_APOSTROPHE,
    ],
    ids=["ascii", "right-quote", "left-quote", "grave", "acute", "prime", "modifier"],
)
def test_every_apostrophe_variant_becomes_the_modifier_letter(apostrophe: str) -> None:
    assert normalize_for_search(f"з{apostrophe}явилася") == f"з{MODIFIER_APOSTROPHE}явилася"
    assert APOSTROPHE == MODIFIER_APOSTROPHE


def test_nfc_is_applied_first() -> None:
    composed_yi = "\N{CYRILLIC CAPITAL LETTER YI}"
    decomposed_yi = "\N{CYRILLIC CAPITAL LETTER BYELORUSSIAN-UKRAINIAN I}\N{COMBINING DIAERESIS}"
    assert normalize_for_search(composed_yi) == composed_yi
    assert normalize_for_search(decomposed_yi) == composed_yi
    # GREEK NUMERAL SIGN is canonically equivalent to MODIFIER LETTER PRIME (a variant).
    assert normalize_for_search("a\N{GREEK NUMERAL SIGN}b") == f"a{MODIFIER_APOSTROPHE}b"


def test_every_unicode_space_separator_becomes_a_space() -> None:
    separators = {
        chr(code)
        for code in range(sys.maxunicode + 1)
        if unicodedata.category(chr(code)) == "Zs" and code != 0x20
    }
    assert separators == set(UNICODE_SPACES)
    for char in separators:
        assert normalize_for_search(f"a{char}b") == "a b"


def test_soft_hyphen_is_removed() -> None:
    assert normalize_for_search("ex\N{SOFT HYPHEN}am\N{SOFT HYPHEN}ple") == "example"


@pytest.mark.parametrize(
    "dash",
    [
        "\N{HYPHEN}",
        "\N{NON-BREAKING HYPHEN}",
        "\N{FIGURE DASH}",
        "\N{EN DASH}",
        "\N{EM DASH}",
        "\N{HORIZONTAL BAR}",
        "\N{MINUS SIGN}",
        "\N{FULLWIDTH HYPHEN-MINUS}",
    ],
)
def test_dash_variants_become_hyphen_minus(dash: str) -> None:
    assert normalize_for_search(f"2019{dash}2022") == "2019-2022"


def test_other_text_is_unchanged() -> None:
    guillemets = "\N{LEFT-POINTING DOUBLE ANGLE QUOTATION MARK}text"
    guillemets += "\N{RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK}"
    assert normalize_for_search(f"Example {guillemets}.") == f"Example {guillemets}."


def test_fold_is_case_insensitive_for_cyrillic() -> None:
    assert fold("ПРИКЛАД.Тест") == fold("приклад.тест") == "приклад.тест"
    assert fold("Ґанок") == "ґанок"
    assert fold("Straße") == "strasse"
    assert fold("З\N{RIGHT SINGLE QUOTATION MARK}ЯВИЛАСЯ") == f"з{MODIFIER_APOSTROPHE}явилася"


def test_sortkey_orders_ukrainian_alphabetically_after_latin() -> None:
    words = ["яблуко", "Ґанок", "гора", "Єнот", "ера", "іній", "Їжак", "иній", "zebra", "Apple"]
    assert sorted(words, key=sortkey) == [
        "Apple",
        "zebra",
        "гора",
        "Ґанок",
        "ера",
        "Єнот",
        "иній",
        "іній",
        "Їжак",
        "яблуко",
    ]


def test_sortkey_maps_the_33_letters_to_consecutive_private_code_points() -> None:
    assert len(UKRAINIAN_ALPHABET) == 33
    keys = [sortkey(letter) for letter in UKRAINIAN_ALPHABET]
    assert keys == [chr(0xE000 + index) for index in range(33)]
    assert sortkey("Ь") == sortkey("ь")


def test_sql_functions_keep_null_and_stringify_other_values() -> None:
    assert sql_fold(None) is None
    assert sql_sortkey(None) is None
    assert sql_fold(12) == "12"
    assert sql_sortkey("Б") == chr(0xE001)
