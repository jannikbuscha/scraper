"""Derived values (DATA_MODEL §8, CODEBOOK §2.7) with synthetic cut-off dates."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from mdt.db.models import AppState, Derived
from mdt.db.session import read_transaction, write_transaction
from mdt.domain import derived
from mdt.domain.dates import parse_partial_date
from mdt.domain.derived import (
    INITIAL,
    EventInput,
    ParticipationInput,
    compute_derived,
)
from mdt.domain.registry import PeriodParameters
from mdt.domain.revisions import (
    apply_change,
    bulk_apply,
    restore_version,
    set_field_verification,
    soft_delete,
    undelete,
)
from mdt.domain.vocab import TermIndex
from tests import synthetic
from tests.conftest import Db, make_settings, open_db
from tests.helpers import (
    ALICE,
    create_event,
    create_evidence,
    create_project,
    create_service,
    focal_org_id,
)

PARAMS = PeriodParameters(synthetic.MINISTRY, synthetic.INVASION)  # 2011-07-15, 2016-03-10
MODIFICATIONS = ("expansion", "rebrand")


def ev(event_id: str, event_type: str, value: str | None, basis: str | None = None) -> EventInput:
    if value is None:
        return EventInput(event_id, event_type, None, None, None, basis)
    parsed = parse_partial_date(value)
    if basis is None:
        basis = "archive_upper_bound" if event_type == "first_archived" else "stated_in_source"
    return EventInput(event_id, event_type, parsed.start, parsed.end, parsed.precision, basis)


def compute(*events: EventInput, participations: tuple[ParticipationInput, ...] = ()) -> Any:
    return compute_derived(events, participations, MODIFICATIONS, PARAMS)


def period_of(*events: EventInput) -> tuple[str, str | None]:
    values = compute(*events)
    return values.period, values.period_reason


def trajectory_of(*events: EventInput) -> tuple[str, str | None, str | None]:
    values = compute(*events)
    return values.war_trajectory, values.trajectory_reason, values.trajectory_event_id


# --------------------------------------------------------------------------------------
# Pure rules
# --------------------------------------------------------------------------------------


def test_no_events_gives_the_initial_state() -> None:
    assert compute() == INITIAL
    assert (INITIAL.period, INITIAL.period_reason) == ("unknown", "no_date")
    assert (INITIAL.war_trajectory, INITIAL.trajectory_reason) == ("unknown", "no_date")
    assert INITIAL.existed_before_invasion is False


def test_launch_interval_and_displayed_candidate() -> None:
    values = compute(ev("evt_b", "launch", "2013"), ev("evt_a", "launch", "2013-06"))
    assert (values.launch_start, values.launch_end) == ("2013-01-01", "2013-06-30")
    assert (values.launch_value, values.launch_precision, values.launch_event_id) == (
        "2013-06",
        "month",
        "evt_a",
    )
    assert values.launch_basis == "stated_in_source"
    # Equal ends: the earlier start wins, then the smaller ID.
    tie = compute(ev("evt_m", "launch", "2013-06"), ev("evt_q", "launch", "2013-Q2"))
    assert tie.launch_event_id == "evt_q"
    same = compute(ev("evt_2", "launch", "2013-06"), ev("evt_1", "launch", "2013-06"))
    assert same.launch_event_id == "evt_1"


def test_beta_launches_count_only_without_dated_launches() -> None:
    beta = ev("evt_beta", "beta_launch", "2012-03")
    assert compute(beta, ev("evt_undated", "launch", None)).launch_event_id == "evt_beta"
    assert compute(beta, ev("evt_launch", "launch", "2014")).launch_event_id == "evt_launch"
    assert compute(ev("evt_undated", "launch", None)).launch_event_id is None


def test_existed_by_is_the_earliest_archive_end() -> None:
    values = compute(
        ev("evt_1", "first_archived", "2014-05"), ev("evt_2", "first_archived", "2013-02-03")
    )
    assert (values.existed_by, values.existed_by_event_id) == ("2013-02-03", "evt_2")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2010", ("pre_ministry", None)),
        ("2011-06", ("pre_ministry", None)),
        ("2011-07-14", ("pre_ministry", None)),
        ("2011-07-15", ("pre_invasion", None)),  # on the founding day
        ("2011-08", ("pre_invasion", None)),
        ("2016-02", ("pre_invasion", None)),
        ("2016-03-09", ("pre_invasion", None)),
        ("2016-03-10", ("full_scale_war", None)),  # on the invasion day
        ("2016-04", ("full_scale_war", None)),
        ("2017", ("full_scale_war", None)),
        # Intervals that straddle a cut-off cannot be assigned.
        ("2011", ("unknown", "imprecise_date")),
        ("2011-Q3", ("unknown", "imprecise_date")),
        ("2011-07", ("unknown", "imprecise_date")),
        ("2016", ("unknown", "imprecise_date")),
        ("2016-Q1", ("unknown", "imprecise_date")),
        ("2016-03", ("unknown", "imprecise_date")),
    ],
)
def test_period_from_the_launch_interval(value: str, expected: tuple[str, str | None]) -> None:
    assert period_of(ev("evt_1", "launch", value)) == expected


def test_imprecise_date_refers_to_the_launch_interval() -> None:
    # The displayed launch (2011-08) lies after the founding day, but the earliest launch may
    # be the one known only as 2011: the interval [2011-01-01, 2011-08-31] straddles the day.
    values = compute(ev("evt_year", "launch", "2011"), ev("evt_month", "launch", "2011-08"))
    assert (values.launch_value, values.launch_start, values.launch_end) == (
        "2011-08",
        "2011-01-01",
        "2011-08-31",
    )
    assert (values.period, values.period_reason) == ("unknown", "imprecise_date")


def test_period_without_launch() -> None:
    assert period_of(ev("evt_1", "first_archived", "2011-07-14")) == ("pre_ministry", None)
    assert period_of(ev("evt_1", "first_archived", "2011-07-15")) == (
        "unknown",
        "archive_bound_only",
    )
    assert period_of(ev("evt_1", "first_archived", "2015")) == ("unknown", "archive_bound_only")
    assert period_of(ev("evt_1", "announced", "2013"), ev("evt_2", "launch", None)) == (
        "unknown",
        "no_date",
    )


def test_existed_before_invasion() -> None:
    assert compute(ev("e", "launch", "2016-03-09")).existed_before_invasion
    assert not compute(ev("e", "launch", "2016-03")).existed_before_invasion
    assert compute(ev("e", "first_archived", "2016-03-09")).existed_before_invasion
    assert not compute(ev("e", "first_archived", "2016-03-10")).existed_before_invasion
    # A straddling launch with an earlier archive bound existed before the invasion.
    assert compute(
        ev("e1", "launch", "2016"), ev("e2", "first_archived", "2015-12-31")
    ).existed_before_invasion


def test_trajectory_new_in_war_and_conflicting_dates() -> None:
    assert trajectory_of(ev("evt_launch", "launch", "2016-03-10")) == (
        "new_in_war",
        None,
        "evt_launch",
    )
    assert trajectory_of(
        ev("evt_launch", "launch", "2017-05"), ev("evt_arch", "first_archived", "2015-01-01")
    ) == ("unknown", "conflicting_dates", "evt_arch")


def test_trajectory_adapted_in_war() -> None:
    launch = ev("evt_launch", "launch", "2013")
    assert trajectory_of(
        launch,
        ev("evt_late", "expansion", "2018"),
        ev("evt_early", "rebrand", "2016-03-10"),
        ev("evt_before", "expansion", "2015"),
    ) == ("adapted_in_war", None, "evt_early")
    # Equal starts: the smaller ID decides.
    assert trajectory_of(
        launch, ev("evt_b", "expansion", "2017-01"), ev("evt_a", "rebrand", "2017")
    ) == ("adapted_in_war", None, "evt_a")
    # Pre-war existence from an archive bound alone is enough.
    assert trajectory_of(
        ev("evt_arch", "first_archived", "2014-06"), ev("evt_mod", "expansion", "2017")
    ) == ("adapted_in_war", None, "evt_mod")


def test_trajectory_prewar_unchanged() -> None:
    launch = ev("evt_launch", "launch", "2013")
    assert trajectory_of(launch) == ("prewar_unchanged", None, None)
    assert trajectory_of(launch, ev("evt_mod", "expansion", "2016-03-09")) == (
        "prewar_unchanged",
        None,
        None,
    )
    # Events that are not modifications do not count.
    assert trajectory_of(launch, ev("evt_other", "announced", "2018")) == (
        "prewar_unchanged",
        None,
        None,
    )
    assert trajectory_of(ev("evt_arch", "first_archived", "2012")) == (
        "prewar_unchanged",
        None,
        None,
    )


def test_trajectory_unknown_reasons() -> None:
    launch = ev("evt_launch", "launch", "2013")
    # An undated or straddling modification event.
    assert trajectory_of(launch, ev("evt_undated", "expansion", None)) == (
        "unknown",
        "imprecise_modification_date",
        "evt_undated",
    )
    assert trajectory_of(launch, ev("evt_straddle", "rebrand", "2016-Q1")) == (
        "unknown",
        "imprecise_modification_date",
        "evt_straddle",
    )
    # A dated straddling event is preferred over an undated one.
    assert (
        trajectory_of(launch, ev("evt_a", "expansion", None), ev("evt_b", "rebrand", "2016"))[2]
        == "evt_b"
    )
    # One modification after the invasion decides, whatever else is imprecise.
    assert trajectory_of(
        launch, ev("evt_undated", "expansion", None), ev("evt_after", "rebrand", "2019")
    ) == ("adapted_in_war", None, "evt_after")
    # A launch interval that straddles the invasion.
    assert trajectory_of(ev("evt_launch", "launch", "2016")) == ("unknown", "imprecise_date", None)
    # Only an archive bound on or after the invasion.
    assert trajectory_of(ev("evt_arch", "first_archived", "2016-03-10")) == (
        "unknown",
        "archive_bound_only",
        None,
    )
    assert trajectory_of(ev("evt_other", "announced", "2013")) == ("unknown", "no_date", None)


def test_portfolio_entry() -> None:
    def participation(pid: str, role: str, value: str | None) -> ParticipationInput:
        if value is None:
            return ParticipationInput(pid, role, None, None, None)
        parsed = parse_partial_date(value)
        return ParticipationInput(pid, role, parsed.start, parsed.end, parsed.precision)

    values = compute(
        participations=(
            participation("par_partner", "partner", "2010"),
            participation("par_owner", "owner", "2014-05"),
            participation("par_operator", "operator", "2013"),
            participation("par_undated", "initiator", None),
        )
    )
    assert (
        values.portfolio_entry_value,
        values.portfolio_entry_start,
        values.portfolio_entry_end,
        values.portfolio_entry_precision,
        values.portfolio_entry_participation_id,
    ) == ("2013", "2013-01-01", "2013-12-31", "year", "par_operator")
    assert (
        compute(participations=(participation("p", "partner", "2010"),)).portfolio_entry_value
        is None
    )


# --------------------------------------------------------------------------------------
# Stored rows and recompute triggers
# --------------------------------------------------------------------------------------


def stored(session: Session, entity_id: str) -> Derived:
    with read_transaction(session):
        row = session.get(Derived, entity_id)
        assert row is not None
        session.expunge(row)
    return row


def test_event_writes_recompute_old_and_new_subjects(db: Db) -> None:
    with db.session() as session:
        first = create_project(session).entity_id
        second = create_project(session).entity_id
        event_id = create_event(session, first, "launch", "2013-05").entity_id
        assert stored(session, first).period == "pre_invasion"
        assert stored(session, first).launch_event_id == event_id
        apply_change(session, "event", event_id, {"date": "2017"}, ALICE, expected_version=1)
        assert stored(session, first).period == "full_scale_war"
        apply_change(session, "event", event_id, {"subject_id": second}, ALICE, expected_version=2)
        assert stored(session, first).period == "unknown"
        assert stored(session, second).war_trajectory == "new_in_war"
        soft_delete(session, "event", event_id, ALICE, expected_version=3)
        assert stored(session, second).period_reason == "no_date"
        undelete(session, "event", event_id, ALICE, expected_version=4)
        assert stored(session, second).period == "full_scale_war"
        restore_version(session, "event", event_id, 1, ALICE, expected_version=5)
        assert stored(session, first).period == "pre_invasion"
        assert stored(session, second).period == "unknown"


def test_disputed_events_are_ignored(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        event_id = create_event(session, project_id, "launch", "2013").entity_id
        apply_change(
            session,
            "event",
            event_id,
            {"verification_status": "disputed"},
            ALICE,
            note="Contradicting source.",
            expected_version=1,
        )
        assert stored(session, project_id).period_reason == "no_date"
        bulk_apply(
            session,
            "event",
            [{"id": event_id, "expected_version": 2}],
            ALICE,
            set_values={"verification_status": "unverified"},
        )
        assert stored(session, project_id).period == "pre_invasion"


def test_event_verification_and_services_get_rows(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        service_id = create_service(session, project_id).entity_id
        assert stored(session, service_id).period == "unknown"
        event_id = create_event(session, service_id, "beta_launch", "2016-03-10").entity_id
        assert stored(session, service_id).war_trajectory == "new_in_war"
        assert stored(session, project_id).period_reason == "no_date"
        evidence_id = create_evidence(session, event_id, "date").entity_id
        set_field_verification(
            session,
            "event",
            event_id,
            "date",
            "verified",
            ALICE,
            evidence_id=evidence_id,
            expected_version=1,
        )
        assert stored(session, service_id).launch_event_id == event_id


def test_focal_participations_set_the_portfolio_entry(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        focal = focal_org_id(session)
        other = apply_change(session, "organization", None, {"name_en": "Example org"}, ALICE)
        base = {"subject_id": project_id, "role": "owner", "start": "2014-02"}
        apply_change(
            session, "participation", None, {**base, "organization_id": other.entity_id}, ALICE
        )
        assert stored(session, project_id).portfolio_entry_value is None
        participation_id = apply_change(
            session, "participation", None, {**base, "organization_id": focal}, ALICE
        ).entity_id
        row = stored(session, project_id)
        assert (row.portfolio_entry_value, row.portfolio_entry_participation_id) == (
            "2014-02",
            participation_id,
        )
        # Moving the participation away from the focal organisation recomputes as well.
        apply_change(
            session,
            "participation",
            participation_id,
            {"organization_id": other.entity_id},
            ALICE,
            expected_version=1,
        )
        assert stored(session, project_id).portfolio_entry_value is None


def test_event_type_terms_trigger_a_full_recompute(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        create_event(session, project_id, "launch", "2013")
        create_event(session, project_id, "announced", "2018")
        assert stored(session, project_id).war_trajectory == "prewar_unchanged"
        with read_transaction(session):
            before = session.get(AppState, derived.HASH_KEY)
            assert before is not None
            hash_before = before.value
        announced = TermIndex(session).term("event_type", "announced")
        session.rollback()
        assert announced is not None
        apply_change(
            session,
            "vocabulary_term",
            announced.id,
            {"attributes": {"counts_as_modification": True}},
            ALICE,
            expected_version=1,
        )
        assert stored(session, project_id).war_trajectory == "adapted_in_war"
        with read_transaction(session):
            after = session.get(AppState, derived.HASH_KEY)
            assert after is not None and after.value != hash_before


def test_rows_change_only_when_values_change(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        computed_at = stored(session, project_id).computed_at
        create_event(session, project_id, "announced")
        assert stored(session, project_id).computed_at == computed_at
        with write_transaction(session):
            assert (
                derived.recompute(
                    session, [project_id, "evt_ignored"], "2030-01-01T00:00:00.000000Z", db.settings
                )
                == 0
            )


def test_parameters_change_triggers_a_full_recompute(db: Db, tmp_path: Path) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        create_event(session, project_id, "launch", "2013")
        assert stored(session, project_id).period == "pre_invasion"
    codebook = tmp_path / "codebook"
    shutil.copytree(db.settings.codebook_path, codebook)
    synthetic.write_parameters(codebook, date(2014, 1, 1), synthetic.INVASION)
    moved = open_db(db.root, make_settings(db.root, codebook, db.settings.seed_path))
    try:
        with moved.session() as session:
            with write_transaction(session):
                assert derived.ensure_current(
                    session, "2030-01-01T00:00:00.000000Z", moved.settings
                )
            assert stored(session, project_id).period == "pre_ministry"
            with write_transaction(session):
                assert not derived.ensure_current(
                    session, "2030-01-01T00:00:00.000000Z", moved.settings
                )
    finally:
        moved.engine.dispose()
    db.check_on_teardown = False  # the original settings now disagree with the stored rows
