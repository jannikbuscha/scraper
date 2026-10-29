"""Author names from the X-Author header and actors per channel (DATA_MODEL §6.2, §7)."""

from __future__ import annotations

from urllib.parse import quote

import pytest

from mdt.domain.actor import Actor, parse_author_header, validate_author_name
from mdt.domain.errors import AuthorInvalidError, AuthorRequiredError


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (quote("Alice Example"), "Alice Example"),
        (quote("Олена Приклад"), "Олена Приклад"),
        (quote("  Alice   Example  "), "Alice Example"),
        (quote("Alice\N{NO-BREAK SPACE}Example"), "Alice Example"),
        (quote("e\N{COMBINING ACUTE ACCENT}"), "\N{LATIN SMALL LETTER E WITH ACUTE}"),
        ("Alice", "Alice"),
        (quote("a" * 100), "a" * 100),
        (quote("Seeder"), "Seeder"),
        (quote("Team A: Alice"), "Team A: Alice"),  # not a "<letters>:" prefix
    ],
)
def test_valid_author_names(header: str, expected: str) -> None:
    assert parse_author_header([header]) == expected


def test_missing_header_is_author_required() -> None:
    with pytest.raises(AuthorRequiredError):
        parse_author_header([])


@pytest.mark.parametrize(
    "header",
    [
        "%",  # a bare percent sign
        "Alice%2",
        "Alice%zz",
        "%FF%FE",  # not UTF-8
        "%C3",  # truncated UTF-8 sequence
        quote(""),
        quote("   "),
        quote("a" * 101),
        quote("Alice, Bob"),
        quote("Alice\tExample"),
        quote("Alice\nExample"),
        quote("Alice\N{ZERO WIDTH SPACE}"),
        quote("Alice\N{RIGHT-TO-LEFT OVERRIDE}"),
        quote("Alice\N{ZERO WIDTH JOINER}"),
        quote("Alice\N{LINE SEPARATOR}"),
        quote("Alice\N{PARAGRAPH SEPARATOR}"),
        quote("Alice" + chr(0xE000)),  # private use
        quote("Alice" + chr(0x0378)),  # unassigned
        quote("seed"),
        quote("SYSTEM"),
        quote(" Seed "),
        quote("collector:example"),
        quote("import:file.csv"),
        quote("manual:Alice"),
        quote("x_y:z"),
        quote("Mail: Alice"),
    ],
)
def test_invalid_author_names(header: str) -> None:
    with pytest.raises(AuthorInvalidError):
        parse_author_header([header])


def test_header_must_occur_once() -> None:
    with pytest.raises(AuthorInvalidError):
        parse_author_header(["Alice", "Bob"])


def test_header_is_decoded_exactly_once() -> None:
    # "%2541" decodes once to "%41", which must not be decoded again to "A".
    assert parse_author_header(["Alice%2541"]) == "Alice%41"


def test_lone_surrogate_is_rejected() -> None:
    with pytest.raises(AuthorInvalidError):
        validate_author_name("Alice" + chr(0xD800))


def test_person_actors_validate_their_names() -> None:
    assert Actor.ui("  Alice   Example ").name == "Alice Example"
    for name in ("seed", "collector:example", "", "Alice, Bob"):
        with pytest.raises(AuthorInvalidError):
            Actor.ui(name)
        with pytest.raises(AuthorInvalidError):
            Actor.restore(name)


def test_actor_constructors() -> None:
    assert Actor.ui("Alice") == Actor("Alice", "ui")
    assert Actor.ui("Alice").is_client
    assert Actor.restore("Alice").is_client
    assert Actor.ui("Alice").as_restore() == Actor("Alice", "restore")
    assert Actor.seed().by == "seed"
    assert not Actor.seed().is_client
    assert Actor.importer("table.xlsx").by == "import:table.xlsx"
    collector = Actor.collector("example", "run_1")
    assert (collector.by, collector.channel, collector.run_id) == (
        "collector:example",
        "collector",
        "run_1",
    )
    assert Actor.system().by == "system"
