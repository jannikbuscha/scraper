"""The guides and the source register against the implementation.

CLAUDE.md asks that the documentation be updated in the same change as the commands,
settings and source behaviour it describes, and Definition of Done 8 asks for a complete
README.md. These tests catch the drift that the Phase 2 review found (README.md and the
fixtures README still describing Phase 1, a live observation recorded in docs/COLLECTORS.md
but not in the source register):

* README.md names every ``mdt`` command, every make target, every setting (except the
  test-only ``COLLECTOR_RUN_INLINE``, which .env.example leaves out as well) and every
  document in docs/; every option of an ``mdt`` command is documented in README.md or in
  docs/COLLECTORS.md §11;
* a guide does not announce a command that exists as future work ("once implemented");
* the evidence labels that docs/SOURCES.md and docs/COLLECTORS.md use are defined (in the
  label list of docs/SOURCES.md or the table of PLAN.md), and a live observation that a
  collector section of docs/COLLECTORS.md cites is recorded in the section of its source in
  docs/SOURCES.md (CLAUDE.md, process rules: a source that behaves differently than
  described is documented in docs/SOURCES.md).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import typer

from mdt.cli import app
from mdt.config import REPO_ROOT, Settings

README = REPO_ROOT / "README.md"
FIXTURES_README = REPO_ROOT / "backend" / "tests" / "fixtures" / "README.md"
SOURCES = REPO_ROOT / "docs" / "SOURCES.md"
COLLECTORS = REPO_ROOT / "docs" / "COLLECTORS.md"
PLAN = REPO_ROOT / "PLAN.md"

#: Guides that name every ``mdt`` command and every make target.
COMMAND_GUIDES = (README,)
#: Guides that must not present an existing command as work still to come.
CURRENT_GUIDES = (README, FIXTURES_README)
#: Phrases that announce work still to come.
FUTURE_MARKERS = ("once implemented", "not yet implemented", "will be added", "until then")
#: Settings for tests only, not documented for users (tests/test_docker_layout.py).
TEST_ONLY_SETTINGS = frozenset({"COLLECTOR_RUN_INLINE"})

_FENCE = re.compile(r"^```.*?^```", re.S | re.M)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
#: A bracketed note in prose that is no link, no list index and no regex class:
#: ``[0b]``, ``[user, 2026-10-30]``, ``[local probe of …]``.
_BRACKETS = re.compile(r"(?<![\w\]\)\[])\[(?P<inner>[^\[\]\n]{1,200}?)\](?![\(\[:])")
#: The label of a bracketed note: a lower-case word, then nothing, a comma, colon or space.
_LABEL = re.compile(r"^(?P<label>[a-z0-9][a-z0-9-]*)(?:$|[,: ])")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _walk(group: Any, prefix: str) -> Iterator[tuple[str, Any]]:
    """The commands below a click group (Typer vendors click, so groups are recognised by
    their ``commands``); a group that runs without a subcommand is a command itself."""
    for name, command in sorted(group.commands.items()):
        path = f"{prefix}{name}"
        if hasattr(command, "commands"):
            if getattr(command, "invoke_without_command", False):
                yield path, command
            yield from _walk(command, f"{path} ")
        else:
            yield path, command


@cache
def cli_commands() -> dict[str, tuple[str, ...]]:
    """Every command of the ``mdt`` CLI by its path ("seed", "db upgrade", "runs", "runs
    show"), with its long options ("--dry-run"; "--help" is not a parameter)."""
    root = typer.main.get_command(app)
    assert hasattr(root, "commands")
    commands = {
        path: tuple(
            option
            for param in command.params
            if param.param_type_name == "option"
            for option in param.opts
            if option.startswith("--")
        )
        for path, command in _walk(root, "")
    }
    # Guards against a vacuous pass: the Phase 1 and Phase 2 commands were found.
    assert {"db upgrade", "serve", "collect", "runs show", "fixtures capture"} <= set(commands)
    return commands


@cache
def make_targets() -> tuple[str, ...]:
    """The targets that ``make help`` lists (a ``## `` description after the colon)."""
    targets = re.findall(r"^([a-zA-Z0-9_-]+):.*## ", read(REPO_ROOT / "Makefile"), re.M)
    assert {"help", "check", "collect", "up"} <= set(targets)
    return tuple(targets)


def markdown_section(text: str, heading: str) -> str:
    """The section whose heading line starts with ``heading`` (e.g. ``"## 11."``), up to
    the next heading of the same or a higher level; lines in code fences are no headings."""
    level = len(heading) - len(heading.lstrip("#"))
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.startswith(heading)]
    assert len(starts) == 1, f"expected one heading {heading!r}, found {len(starts)}"
    end, fenced = len(lines), False
    for index in range(starts[0] + 1, len(lines)):
        line = lines[index]
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(rf"#{{1,{level}}} ", line):
            end = index
            break
    return "\n".join(lines[starts[0] : end])


def mentions_command(line: str) -> bool:
    """Whether a line names an existing ``mdt`` command or make target."""
    for path in cli_commands():
        if re.search(rf"\bmdt {re.escape(path)}(?![\w-])", line):
            return True
        if re.search(rf"`{re.escape(path)}(?=[ `\[])", line):
            return True
    return any(
        re.search(rf"\bmake {re.escape(target)}(?![\w-])", line) for target in make_targets()
    )


def used_labels(text: str) -> set[str]:
    """The evidence labels of the bracketed notes in the prose of ``text`` (code removed)."""
    prose = _INLINE_CODE.sub("", _FENCE.sub("", text))
    labels = set()
    for match in _BRACKETS.finditer(prose):
        label = _LABEL.match(match.group("inner"))
        if label:
            labels.add(label.group("label"))
    return labels


def defined_labels() -> set[str]:
    """The labels of the label list of docs/SOURCES.md and of the table in PLAN.md."""
    [label_list] = [line for line in read(SOURCES).splitlines() if line.startswith("> **Labels:**")]
    table = markdown_section(read(PLAN), "### Evidence labels")
    defined = set(re.findall(r"\*\*\[([a-z0-9-]+)\]\*\*", label_list))
    defined |= set(re.findall(r"^\| \*\*\[([a-z0-9-]+)\]\*\* \|", table, re.M))
    assert {"user", "0b", "local"} <= defined
    return defined


def source_section(source_id: str) -> str:
    """The section of a source in docs/SOURCES.md (``## S3 — …``)."""
    return markdown_section(read(SOURCES), f"## {source_id} ")


def collector_sections() -> Iterator[tuple[str, tuple[str, ...], str]]:
    """The collector sections of docs/COLLECTORS.md §8: heading, cited sources, text."""
    chapter = markdown_section(read(COLLECTORS), "## 8.")
    parts = re.split(r"^(?=### 8\.\d+ )", chapter, flags=re.M)[1:]
    assert len(parts) >= 5, "the collector sections of docs/COLLECTORS.md §8 were not found"
    for part in parts:
        heading = part.splitlines()[0]
        cited = re.search(r"\(SOURCES ([^)]*)\)", heading)
        sources = tuple(re.findall(r"S\d+[a-z]?", cited.group(1))) if cited else ()
        yield heading, sources, part


# --------------------------------------------------------------------------------------
# README.md and the other guides
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("guide", COMMAND_GUIDES, ids=lambda path: path.name)
def test_the_guide_names_every_cli_command(guide: Path) -> None:
    text = read(guide)
    missing = [
        path
        for path in cli_commands()
        if not re.search(rf"`(?:mdt )?{re.escape(path)}(?=[ `\[])", text)
    ]
    assert not missing, f"{guide.name} does not name the mdt commands {missing}"


@pytest.mark.parametrize("guide", COMMAND_GUIDES, ids=lambda path: path.name)
def test_the_guide_names_every_make_target(guide: Path) -> None:
    text = read(guide)
    missing = [
        target
        for target in make_targets()
        if not re.search(rf"\bmake {re.escape(target)}(?![\w-])", text)
    ]
    assert not missing, f"{guide.name} does not name the make targets {missing}"


def test_every_cli_option_is_documented() -> None:
    """In README.md (the Phase 1 commands) or in docs/COLLECTORS.md §11 (Phase 2)."""
    documented = read(README) + "\n" + markdown_section(read(COLLECTORS), "## 11.")
    missing = [
        f"mdt {path} {option}"
        for path, options in cli_commands().items()
        for option in options
        if not re.search(rf"{re.escape(option)}(?![\w-])", documented)
    ]
    assert not missing, f"undocumented options: {missing}"


def test_the_readme_documents_every_setting() -> None:
    text = read(README)
    settings = sorted(name.upper() for name in Settings.model_fields)
    assert {"CONTACT_EMAIL", "COLLECTOR_REPLAY_DIR"} <= set(settings)
    missing = [
        name for name in settings if name not in TEST_ONLY_SETTINGS and f"`{name}`" not in text
    ]
    assert not missing, f"README.md does not document the settings {missing}"


def test_the_readme_lists_every_document_in_docs() -> None:
    text = read(README)
    documents = sorted((REPO_ROOT / "docs").glob("*.md"))
    assert documents
    missing = [path.name for path in documents if f"](docs/{path.name})" not in text]
    assert not missing, f"README.md does not link {missing}"


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


@pytest.mark.parametrize("guide", CURRENT_GUIDES, ids=relative)
def test_the_guide_does_not_announce_existing_commands_as_future_work(guide: Path) -> None:
    stale = [
        f"line {number}: {line[:120]}"
        for number, line in enumerate(read(guide).splitlines(), start=1)
        if mentions_command(line) and any(marker in line.lower() for marker in FUTURE_MARKERS)
    ]
    assert not stale, f"{relative(guide)} announces existing commands as future work: {stale}"


def test_command_mentions_are_recognised() -> None:
    """The detection behind the test above (guards against a vacuous pass)."""
    assert mentions_command("Phase 2 adds `mdt fixtures capture <source>`. Until then …")
    assert mentions_command("| `make collect SOURCE=<name>` | (Phase 2, once implemented) |")
    assert mentions_command("Commands: `collect <name> [--mode] …`, `runs [show <id>]`")
    assert not mentions_command("Automatic daily backups arrive in Phase 4. Until then: copy")


# --------------------------------------------------------------------------------------
# docs/SOURCES.md and docs/COLLECTORS.md
# --------------------------------------------------------------------------------------


def test_evidence_labels_are_defined() -> None:
    """A label that is not defined (e.g. a "[live check]" in docs/COLLECTORS.md) cites
    evidence that the source register does not explain."""
    defined = defined_labels()
    for path in (SOURCES, COLLECTORS):
        undefined = sorted(used_labels(read(path)) - defined)
        assert not undefined, (
            f"{path.name} uses the evidence labels {undefined}, which neither the label list "
            "of docs/SOURCES.md nor the table of PLAN.md defines (write other bracketed text "
            "in backticks)"
        )


def test_live_observations_of_a_collector_are_recorded_for_its_source() -> None:
    checked = 0
    for heading, sources, text in collector_sections():
        if "live" not in used_labels(text):
            continue
        assert sources, f"{heading!r} cites a live observation but names no source"
        for source_id in sources:
            assert "live" in used_labels(source_section(source_id)), (
                f"{heading!r} cites a live observation that docs/SOURCES.md {source_id} does "
                "not record"
            )
            checked += 1
    # Guards against a vacuous pass: C3's live observations of 2026-10-30 were checked.
    assert checked >= 1


def test_labels_are_read_from_prose_only() -> None:
    text = (
        "Seen [0b] and [user, 2026-10-30] and [local probe of the fixtures]; "
        "`list[str]`, [a link](https://example.org), names[key] and\n"
        "```yaml\n# [ignored]\n```\n"
    )
    assert used_labels(text) == {"0b", "user", "local"}
