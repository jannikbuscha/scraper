"""The codebook definitions of the derived values against the implemented rules.

Coders and readers of the paper rely on the definitions of the vocabularies ``period``,
``war_trajectory`` and ``derived_reason`` (``codebook/*.yaml``, the Codebook page and
docs/CODEBOOK.md §3), while :func:`mdt.domain.derived.compute_derived` applies the rules of
DATA_MODEL §8.3. Below, every definition is formalised as the alternatives its text names,
written from the text alone. On an exhaustive grid of launch, beta-launch, archive and
modification dates around the (synthetic) cut-off dates, the tests check that

* for ``period`` and ``war_trajectory``, exactly the computed value's definition holds;
* a reason is given exactly when the value is ``unknown``, and its definition holds;
* every alternative of every definition occurs, so no definition names a case that cannot
  happen;
* the formalised texts are the texts of ``codebook/*.yaml``: when a definition is reworded,
  a test fails until its alternatives have been checked against the new wording;
* the definitions speak of the launch interval, never of "the launch" alone, which reads as
  the single candidate that the detail page shows as "Launch" (CODEBOOK §2.7).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from itertools import combinations

import pytest

from mdt.config import REPO_ROOT
from mdt.domain.dates import parse_partial_date
from mdt.domain.derived import DerivedValues, EventInput, compute_derived
from mdt.domain.registry import PeriodParameters
from mdt.domain.vocab import load_vocabulary_files
from tests import synthetic

MINISTRY, INVASION = synthetic.MINISTRY, synthetic.INVASION  # 2011-07-15, 2016-03-10
PARAMS = PeriodParameters(MINISTRY, INVASION)
MODIFICATION_TYPES = ("expansion", "rebrand")
VOCABULARIES = ("period", "war_trajectory", "derived_reason")
#: The reason codes each field uses (CODEBOOK §2.7).
REASONS_OF = {
    "period_reason": {"no_date", "imprecise_date", "archive_bound_only"},
    "trajectory_reason": {
        "no_date",
        "imprecise_date",
        "imprecise_modification_date",
        "conflicting_dates",
        "archive_bound_only",
    },
}

#: Dates before, around, on and after both cut-off dates, in every precision.
DATES = (
    "2010",
    "2011",
    "2011-Q3",
    "2011-07",
    "2011-07-14",
    "2011-07-15",
    "2011-08",
    "2013",
    "2016",
    "2016-Q1",
    "2016-03",
    "2016-03-09",
    "2016-03-10",
    "2016-04",
    "2017",
)
#: Archive captures: none, one, or two (the earliest end counts).
ARCHIVES: list[tuple[str, ...]] = [
    (),
    *((value,) for value in DATES),
    ("2016-04", "2011-08"),
    ("2017", "2016"),
]
#: Modification events (``None`` = undated): before, straddling, on and after the invasion.
MODIFICATIONS: list[tuple[str | None, ...]] = [
    (),
    (None,),
    ("2013",),
    ("2016-03-09",),
    ("2016",),
    ("2016-03-10",),
    ("2017",),
    ("2013", None),
    ("2016", "2017"),
    (None, "2017"),
    ("2013", "2016-Q1"),
]


@dataclass(frozen=True)
class Case:
    """The event dates of one subject (``None`` = an undated event)."""

    launches: tuple[str | None, ...]
    betas: tuple[str | None, ...]
    archives: tuple[str, ...]
    modifications: tuple[str | None, ...]


Interval = tuple[date, date]


@dataclass(frozen=True)
class Facts:
    """What the definitions speak of, taken from the event dates as CODEBOOK §2.7 defines
    them (independently of ``mdt.domain.derived``)."""

    #: The launch interval: [earliest start, earliest end] of the dated launch events, or,
    #: if there are none, of the dated beta-launch events.
    launch: Interval | None
    #: The archive bound: the earliest end of the archive captures.
    archive_bound: date | None
    #: The modification events (``None`` = undated).
    modifications: tuple[Interval | None, ...]


@cache
def interval(value: str) -> Interval:
    parsed = parse_partial_date(value)
    return parsed.start, parsed.end


def facts_of(case: Case) -> Facts:
    dated = [interval(v) for v in case.launches if v] or [interval(v) for v in case.betas if v]
    launch = (min(s for s, _ in dated), min(e for _, e in dated)) if dated else None
    archive_bound = min((interval(v)[1] for v in case.archives), default=None)
    modifications = tuple(interval(v) if v else None for v in case.modifications)
    return Facts(launch, archive_bound, modifications)


def events_of(case: Case) -> list[EventInput]:
    groups: tuple[tuple[str, tuple[str | None, ...]], ...] = (
        ("launch", case.launches),
        ("beta_launch", case.betas),
        ("first_archived", case.archives),
        ("expansion", case.modifications),
    )
    result = []
    for event_type, values in groups:
        for index, value in enumerate(values):
            event_id = f"evt_{event_type}_{index}"
            if value is None:
                result.append(EventInput(event_id, event_type, None, None, None, None))
                continue
            parsed = parse_partial_date(value)
            basis = "archive_upper_bound" if event_type == "first_archived" else "stated_in_source"
            result.append(
                EventInput(event_id, event_type, parsed.start, parsed.end, parsed.precision, basis)
            )
    return result


def cases() -> Iterator[Case]:
    launch_options: list[tuple[tuple[str | None, ...], tuple[str | None, ...]]] = [
        ((), ()),
        ((None,), ()),
    ]
    for value in DATES:
        launch_options += [
            ((value,), ()),
            ((), (value,)),  # only a beta launch
            ((None,), (value,)),  # an undated launch does not hide the beta launch
            ((value,), ("2010",)),  # a dated launch hides the beta launch
        ]
    launch_options += [((first, second), ()) for first, second in combinations(DATES, 2)]
    for launches, betas in launch_options:
        for archives in ARCHIVES:
            for modifications in MODIFICATIONS:
                yield Case(launches, betas, archives, modifications)


Evaluated = list[tuple[Case, Facts, DerivedValues]]


@pytest.fixture(scope="module")
def evaluated() -> Evaluated:
    """Every case of the grid with its facts and its computed values."""
    return [
        (case, facts_of(case), compute_derived(events_of(case), (), MODIFICATION_TYPES, PARAMS))
        for case in cases()
    ]


# --------------------------------------------------------------------------------------
# The definitions, formalised
# --------------------------------------------------------------------------------------

#: An alternative of a definition, evaluated for a field: ``period`` and ``war_trajectory``
#: for the values, ``period_reason`` and ``trajectory_reason`` for the reasons.
Alternative = Callable[[Facts, str], bool]


@dataclass(frozen=True)
class Definition:
    """A definition's text and the alternatives it names (it holds if one of them does)."""

    text: str
    alternatives: tuple[Alternative, ...]

    def holds(self, facts: Facts, field: str) -> bool:
        return any(alternative(facts, field) for alternative in self.alternatives)


def launch_ends_before(facts: Facts, cut: date) -> bool:
    return facts.launch is not None and facts.launch[1] < cut


def launch_starts_on_or_after(facts: Facts, cut: date) -> bool:
    return facts.launch is not None and facts.launch[0] >= cut


def straddles(facts: Facts, cut: date) -> bool:
    return facts.launch is not None and facts.launch[0] < cut <= facts.launch[1]


def archive_before(facts: Facts, cut: date) -> bool:
    return facts.archive_bound is not None and facts.archive_bound < cut


def only_archive_on_or_after(facts: Facts, cut: date) -> bool:
    return facts.launch is None and facts.archive_bound is not None and facts.archive_bound >= cut


def existed_before_by_launch(facts: Facts) -> bool:
    """`adapted_in_war`: "the launch ends before `FULL_SCALE_INVASION`"."""
    return launch_ends_before(facts, INVASION)


def existed_before_by_archive(facts: Facts) -> bool:
    """`adapted_in_war`: "an archive bound lies before it and the launch, if any, starts
    before it"."""
    return archive_before(facts, INVASION) and (facts.launch is None or facts.launch[0] < INVASION)


def existed_before(facts: Facts) -> bool:
    return existed_before_by_launch(facts) or existed_before_by_archive(facts)


def modification_on_or_after_invasion(facts: Facts) -> bool:
    return any(m is not None and m[0] >= INVASION for m in facts.modifications)


def no_trajectory_value(facts: Facts) -> bool:
    """`war_trajectory` `unknown`: none of the other values is determined."""
    return not any(
        DEFINITIONS[("war_trajectory", code)].holds(facts, "war_trajectory")
        for code in ("new_in_war", "adapted_in_war", "prewar_unchanged")
    )


DEFINITIONS: dict[tuple[str, str], Definition] = {
    ("period", "pre_ministry"): Definition(
        "The launch interval ends before `MINISTRY_FOUNDED`, or, without a dated launch or "
        "beta-launch event, the archive bound lies before `MINISTRY_FOUNDED`.",
        (
            lambda f, _: launch_ends_before(f, MINISTRY),
            lambda f, _: f.launch is None and archive_before(f, MINISTRY),
        ),
    ),
    ("period", "pre_invasion"): Definition(
        "The launch interval lies within `MINISTRY_FOUNDED` … `FULL_SCALE_INVASION` − 1 day.",
        (
            lambda f, _: (
                f.launch is not None
                and f.launch[0] >= MINISTRY
                and f.launch[1] <= INVASION - timedelta(days=1)
            ),
        ),
    ),
    ("period", "full_scale_war"): Definition(
        "The launch interval starts on or after `FULL_SCALE_INVASION`.",
        (lambda f, _: launch_starts_on_or_after(f, INVASION),),
    ),
    ("period", "unknown"): Definition(
        "No dated launch, beta-launch or archive event, a launch interval that straddles a "
        "cut-off date, or only an archive bound on or after `MINISTRY_FOUNDED`; the reason is "
        "given in `period_reason`.",
        (
            lambda f, _: f.launch is None and f.archive_bound is None,
            lambda f, _: straddles(f, MINISTRY) or straddles(f, INVASION),
            lambda f, _: only_archive_on_or_after(f, MINISTRY),
        ),
    ),
    ("war_trajectory", "new_in_war"): Definition(
        "The launch interval starts on or after `FULL_SCALE_INVASION`, and no archive bound lies "
        "before `FULL_SCALE_INVASION`.",
        (lambda f, _: launch_starts_on_or_after(f, INVASION) and not archive_before(f, INVASION),),
    ),
    ("war_trajectory", "adapted_in_war"): Definition(
        "Existed before the invasion: the launch interval ends before `FULL_SCALE_INVASION`, or "
        "an archive bound lies before `FULL_SCALE_INVASION` and the launch interval, if any, "
        "starts before it. At least one modification event starts on or after "
        "`FULL_SCALE_INVASION`.",
        (
            lambda f, _: existed_before_by_launch(f) and modification_on_or_after_invasion(f),
            lambda f, _: existed_before_by_archive(f) and modification_on_or_after_invasion(f),
        ),
    ),
    ("war_trajectory", "prewar_unchanged"): Definition(
        "Existed before the invasion (as for `adapted_in_war`). Every modification event is "
        "dated and ends before `FULL_SCALE_INVASION`, or there is none: no modification on or "
        "after the invasion is recorded up to the release date.",
        (
            lambda f, _: (
                existed_before(f)
                and bool(f.modifications)
                and all(m is not None and m[1] < INVASION for m in f.modifications)
            ),
            lambda f, _: existed_before(f) and not f.modifications,
        ),
    ),
    ("war_trajectory", "unknown"): Definition(
        "Not determinable; the reason is given in `trajectory_reason`.",
        (lambda f, _: no_trajectory_value(f),),
    ),
    ("derived_reason", "no_date"): Definition(
        "No dated launch, beta-launch or archive event.",
        (lambda f, _: f.launch is None and f.archive_bound is None,),
    ),
    ("derived_reason", "imprecise_date"): Definition(
        "The launch interval, taken over all dated launch events or, if there are none, all "
        "dated beta-launch events, straddles a cut-off date: it starts before the date and ends "
        "on or after it.",
        (
            lambda f, _: straddles(f, MINISTRY),
            lambda f, _: straddles(f, INVASION),
        ),
    ),
    ("derived_reason", "archive_bound_only"): Definition(
        "Only an archive upper bound is known (no dated launch or beta-launch event), and it "
        "does not decide the value: it lies on or after `MINISTRY_FOUNDED` (`period_reason`) "
        "or on or after `FULL_SCALE_INVASION` (`trajectory_reason`).",
        (
            lambda f, field: field == "period_reason" and only_archive_on_or_after(f, MINISTRY),
            lambda f, field: field == "trajectory_reason" and only_archive_on_or_after(f, INVASION),
        ),
    ),
    ("derived_reason", "imprecise_modification_date"): Definition(
        "A modification event is undated or straddles `FULL_SCALE_INVASION`.",
        (
            lambda f, _: any(m is None for m in f.modifications),
            lambda f, _: any(m is not None and m[0] < INVASION <= m[1] for m in f.modifications),
        ),
    ),
    ("derived_reason", "conflicting_dates"): Definition(
        "The launch interval starts on or after `FULL_SCALE_INVASION`, but an archive bound lies "
        "before `FULL_SCALE_INVASION`, so the item existed before the invasion.",
        (lambda f, _: launch_starts_on_or_after(f, INVASION) and archive_before(f, INVASION),),
    ),
}


def computed(values: DerivedValues) -> list[tuple[str, str, str, str | None]]:
    """(value field, value, reason field, reason) of the two derived values."""
    return [
        ("period", values.period, "period_reason", values.period_reason),
        ("war_trajectory", values.war_trajectory, "trajectory_reason", values.trajectory_reason),
    ]


# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------


def test_the_grid_covers_every_value_and_reason(evaluated: Evaluated) -> None:
    seen: dict[str, set[str | None]] = defaultdict(set)
    for _, _, values in evaluated:
        for value_field, value, reason_field, reason in computed(values):
            seen[value_field].add(value)
            seen[reason_field].add(reason)
    assert seen["period"] == {"pre_ministry", "pre_invasion", "full_scale_war", "unknown"}
    assert seen["war_trajectory"] == {"new_in_war", "adapted_in_war", "prewar_unchanged", "unknown"}
    # The reason codes of each field are exactly those of CODEBOOK §2.7.
    assert seen["period_reason"] == {None, *REASONS_OF["period_reason"]}
    assert seen["trajectory_reason"] == {None, *REASONS_OF["trajectory_reason"]}


def test_exactly_the_definition_of_the_computed_value_holds(evaluated: Evaluated) -> None:
    for case, facts, values in evaluated:
        for value_field, value, _, _ in computed(values):
            holding = {
                code
                for (vocabulary, code), definition in DEFINITIONS.items()
                if vocabulary == value_field and definition.holds(facts, value_field)
            }
            assert holding == {value}, (case, value_field, value, holding)


def test_the_definition_of_the_computed_reason_holds(evaluated: Evaluated) -> None:
    for case, facts, values in evaluated:
        for _, value, reason_field, reason in computed(values):
            assert (reason is not None) == (value == "unknown"), (case, reason_field)
            if reason is None:
                continue
            definition = DEFINITIONS[("derived_reason", reason)]
            assert definition.holds(facts, reason_field), (case, reason_field, reason)
        if values.trajectory_reason == "conflicting_dates":
            # The deciding event is the archive capture that shows the earlier existence.
            assert values.trajectory_event_id == values.existed_by_event_id, case


def test_every_alternative_of_every_definition_occurs(evaluated: Evaluated) -> None:
    witnessed: set[tuple[str, str, int]] = set()
    for _, facts, values in evaluated:
        for value_field, value, reason_field, reason in computed(values):
            for field, code, vocabulary in (
                (value_field, value, value_field),
                (reason_field, reason, "derived_reason"),
            ):
                if code is None:
                    continue
                definition = DEFINITIONS[(vocabulary, code)]
                for index, alternative in enumerate(definition.alternatives):
                    if alternative(facts, field):
                        witnessed.add((vocabulary, code, index))
    never = [
        f"{vocabulary}.{code}, alternative {index + 1}: {definition.text}"
        for (vocabulary, code), definition in DEFINITIONS.items()
        for index in range(len(definition.alternatives))
        if (vocabulary, code, index) not in witnessed
    ]
    assert not never, never


def test_the_formalised_texts_are_the_codebook_definitions() -> None:
    codebook = {
        (vocabulary.name, term["code"]): term["definition"]
        for vocabulary in load_vocabulary_files(REPO_ROOT / "codebook")
        if vocabulary.name in VOCABULARIES
        for term in vocabulary.terms
    }
    formalised = {key: definition.text for key, definition in DEFINITIONS.items()}
    # A reworded definition: check its alternatives above against the new text, then update
    # the text here (and keep docs/CODEBOOK.md §3 in step, see test_vocab.py).
    assert codebook == formalised


#: "launch" or "launched" meaning the derived launch, i.e. anything but "launch interval",
#: the event types ("dated launch event(s)", "launch, beta-launch or archive event", "launch
#: or beta-launch event") and "beta-launch".
BARE_LAUNCH = re.compile(
    r"(?<!beta-)\blaunch(?:ed)?\b(?! interval)(?! events?\b)(?!,? (?:or )?beta-launch)",
    re.IGNORECASE,
)


@pytest.mark.parametrize(
    ("text", "bare"),
    [
        # Earlier wordings that a reader applies to the displayed candidate.
        ("The launch date's precision straddles a cut-off date.", True),
        ("Launched on or after `FULL_SCALE_INVASION`.", True),
        ("Launch starts on or after `FULL_SCALE_INVASION`.", True),
        ("No launch date, an imprecise date that straddles a cut-off", True),
        ("a launch that straddles a cut-off date", True),
        ("an archive bound lies before it and the launch, if any, starts before it", True),
        # The launch interval and the event types.
        ("The launch interval starts on or after `FULL_SCALE_INVASION`.", False),
        ("No dated launch, beta-launch or archive event.", False),
        ("without a dated launch or beta-launch event", False),
        ("all dated launch events or, if there are none, all dated beta-launch events", False),
    ],
)
def test_bare_launch_pattern(text: str, bare: bool) -> None:
    assert bool(BARE_LAUNCH.search(text)) is bare


def test_the_definitions_speak_of_the_launch_interval() -> None:
    # The detail page shows one candidate as "Launch" (the one that ends first), next to the
    # reason's definition, while the rules use the interval over all candidates: launch
    # events dated 2011 and 2011-08 show "2011-08", which lies after the founding day, yet
    # the period is unknown because the interval [2011-01-01, 2011-08-31] straddles it (see
    # test_derived.py). A definition that speaks of "the launch" or "the launch date" is read
    # as the displayed candidate and then contradicts the computed value.
    bare = [
        f"{vocabulary.name}.{term['code']}: {term['definition']}"
        for vocabulary in load_vocabulary_files(REPO_ROOT / "codebook")
        if vocabulary.name in VOCABULARIES
        for term in vocabulary.terms
        if BARE_LAUNCH.search(term["definition"] or "")
    ]
    assert not bare, bare
