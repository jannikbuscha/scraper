"""Validation rules of DATA_MODEL §7 on the write path."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from mdt.domain.actor import Actor
from mdt.domain.errors import (
    FixedCodeError,
    ReferenceDeletedError,
    UniqueViolationError,
    ValidationError,
)
from mdt.domain.revisions import apply_change, soft_delete
from mdt.domain.vocab import TermIndex
from tests.conftest import Db
from tests.helpers import (
    ALICE,
    create_event,
    create_project,
    create_service,
    fields_of,
    load,
    project_data,
)

EXAMPLE_URL = "https://example.org/source"


def details_of(error: pytest.ExceptionInfo[ValidationError]) -> dict[str, Any]:
    return error.value.details or {}


def term_id(session: Session, vocabulary: str, code: str) -> str:
    term = TermIndex(session).term(vocabulary, code)
    session.rollback()
    assert term is not None
    return term.id


# --------------------------------------------------------------------------------------
# Required fields, names, scope and verification notes
# --------------------------------------------------------------------------------------


def test_required_fields_and_one_of_names(db: Db) -> None:
    with db.session() as session, pytest.raises(ValidationError) as caught:
        apply_change(session, "project", None, {"scope_note": "Synthetic."}, ALICE)
    assert details_of(caught) == {
        "slug": ["is required"],
        "name_en": ["At least one of name_en/name_uk is required"],
        "name_uk": ["At least one of name_en/name_uk is required"],
    }


def test_names_are_checked_after_normalisation(db: Db) -> None:
    with db.session() as session:
        with pytest.raises(ValidationError):
            create_project(session, name_en="   ", name_uk="")
        created = create_project(session, name_en=None, name_uk="Приклад")
        with pytest.raises(ValidationError):
            apply_change(
                session, "project", created.entity_id, {"name_uk": " "}, ALICE, expected_version=1
            )


def test_scope_note_is_required_on_create_and_when_the_scope_changes(db: Db) -> None:
    with db.session() as session:
        with pytest.raises(ValidationError) as caught:
            apply_change(session, "project", None, project_data(scope_note=None), ALICE)
        assert "scope_note" in details_of(caught)
        created = create_project(session)
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "project",
                created.entity_id,
                {"in_paper_scope": True},
                ALICE,
                expected_version=1,
            )
        assert "scope_note" in details_of(caught)
        changed = apply_change(
            session,
            "project",
            created.entity_id,
            {"in_paper_scope": True, "scope_note": "Synthetic reason for the scope."},
            ALICE,
            expected_version=1,
        )
        assert changed.changed
        # Other changes need no scope note.
        apply_change(
            session, "project", created.entity_id, {"name_en": "x"}, ALICE, expected_version=2
        )


def test_verified_or_disputed_record_status_needs_a_note(db: Db) -> None:
    with db.session() as session:
        created = create_project(session)
        for status in ("verified", "disputed"):
            with pytest.raises(ValidationError) as caught:
                apply_change(
                    session,
                    "project",
                    created.entity_id,
                    {"verification_status": status},
                    ALICE,
                    expected_version=1,
                )
            assert "note" in details_of(caught)
        result = apply_change(
            session,
            "project",
            created.entity_id,
            {"verification_status": "verified"},
            ALICE,
            note="Checked against the sources.",
            expected_version=1,
        )
        assert result.changed
        apply_change(
            session,
            "project",
            created.entity_id,
            {"verification_status": "unverified"},
            ALICE,
            expected_version=2,
        )


# --------------------------------------------------------------------------------------
# Vocabulary codes
# --------------------------------------------------------------------------------------


def test_unknown_codes_are_refused_with_their_index(db: Db) -> None:
    with db.session() as session, pytest.raises(ValidationError) as caught:
        create_project(session, status="unknown_code", policy_domains=["domain_a", "nope"])
    assert details_of(caught) == {
        "status": ["is not a code of the vocabulary status"],
        "policy_domains[1]": ["is not a code of the vocabulary policy_domain"],
    }


def test_inactive_codes_cannot_be_added_but_may_be_kept(db: Db) -> None:
    with db.session() as session:
        with pytest.raises(ValidationError) as caught:
            create_project(session, status="retired")
        assert details_of(caught) == {"status": ["is an inactive code"]}
        created = create_project(session, status="planned", policy_domains=["domain_a"])
        planned = term_id(session, "status", "planned")
        apply_change(
            session,
            "vocabulary_term",
            planned,
            {"active": False},
            ALICE,
            expected_version=1,
        )
        domain = term_id(session, "policy_domain", "domain_a")
        apply_change(
            session, "vocabulary_term", domain, {"active": False}, ALICE, expected_version=1
        )
        # The stored inactive codes stay; other changes are still possible.
        apply_change(
            session,
            "project",
            created.entity_id,
            {"name_en": "Changed", "policy_domains": ["domain_a", "domain_b"]},
            ALICE,
            expected_version=1,
        )
        assert fields_of(session, "project", created.entity_id)["status"] == "planned"
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "project",
                created.entity_id,
                {"policy_domains": ["domain_b", "domain_old"]},
                ALICE,
                expected_version=2,
            )
        assert details_of(caught) == {"policy_domains[1]": ["is an inactive code"]}


# --------------------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------------------


def test_reference_to_a_missing_row(db: Db) -> None:
    with db.session() as session, pytest.raises(ValidationError) as caught:
        create_service(session, "prj_01JBX3ABCDEFGHJKMNPQRSTVWX")
    assert details_of(caught) == {"project_id": ["refers to a record that does not exist"]}


def test_reference_to_a_deleted_row(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Deleted example")
        soft_delete(session, "project", project.entity_id, ALICE, expected_version=1)
        with pytest.raises(ReferenceDeletedError) as caught:
            create_service(session, project.entity_id)
        assert caught.value.details == {
            "field": "project_id",
            "id": project.entity_id,
            "type": "project",
            "label": "Deleted example",
        }


def test_unchanged_reference_to_a_deleted_row_does_not_block_other_changes(db: Db) -> None:
    with db.session() as session:
        project = create_project(session)
        event = create_event(session, project.entity_id, "announced")
        soft_delete(session, "project", project.entity_id, ALICE, expected_version=1)
        result = apply_change(
            session,
            "event",
            event.entity_id,
            {"description_en": "Changed."},
            ALICE,
            expected_version=1,
        )
        assert result.changed


def test_reference_type_is_checked_by_prefix(db: Db) -> None:
    with db.session() as session:
        project = create_project(session)
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "participation",
                None,
                {"organization_id": project.entity_id, "subject_id": project.entity_id},
                ALICE,
            )
        assert "organization_id" in details_of(caught)


# --------------------------------------------------------------------------------------
# Entity-specific rules
# --------------------------------------------------------------------------------------


def test_parent_service_rules(db: Db) -> None:
    with db.session() as session:
        project = create_project(session)
        other = create_project(session)
        parent = create_service(session, project.entity_id)
        foreign = create_service(session, other.entity_id)
        child = create_service(session, project.entity_id, parent_service_id=parent.entity_id)
        with pytest.raises(ValidationError) as caught:
            create_service(session, project.entity_id, parent_service_id=foreign.entity_id)
        assert details_of(caught) == {
            "parent_service_id": ["The parent service must belong to the same project"]
        }
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "service",
                parent.entity_id,
                {"parent_service_id": child.entity_id},
                ALICE,
                expected_version=1,
            )
        assert details_of(caught) == {
            "parent_service_id": ["The parent service would create a cycle"]
        }
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "service",
                parent.entity_id,
                {"parent_service_id": parent.entity_id},
                ALICE,
                expected_version=1,
            )
        assert details_of(caught) == {"parent_service_id": ["A service cannot be its own parent"]}
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "service",
                parent.entity_id,
                {"project_id": other.entity_id},
                ALICE,
                expected_version=1,
            )
        assert "project_id" in details_of(caught)


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        ({"event_type": "launch", "date": "2020"}, "is required when a date is set"),
        (
            {"event_type": "first_archived", "date": "2020", "date_basis": "stated_in_source"},
            "must be archive_upper_bound for first_archived events",
        ),
        (
            {"event_type": "launch", "date": "2020", "date_basis": "archive_upper_bound"},
            "archive_upper_bound is allowed only for first_archived events; record an archive "
            "capture as a separate first_archived event",
        ),
    ],
)
def test_event_date_rules(db: Db, data: dict[str, Any], problem: str) -> None:
    with db.session() as session:
        project = create_project(session)
        with pytest.raises(ValidationError) as caught:
            apply_change(session, "event", None, {"subject_id": project.entity_id, **data}, ALICE)
        assert details_of(caught) == {"date_basis": [problem]}


def test_valid_events(db: Db) -> None:
    with db.session() as session:
        project = create_project(session)
        create_event(session, project.entity_id, "launch", "2020-Q2", date_text="Q2 2020")
        create_event(session, project.entity_id, "first_archived", "2019-05-04")
        create_event(session, project.entity_id, "announced")  # undated
        # A basis without a date is allowed.
        create_event(session, project.entity_id, "announced", date_basis="inferred")


def test_document_rules(db: Db) -> None:
    with db.session() as session:
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session, "document", None, {"title": "Example", "published": "2020-05"}, ALICE
            )
        assert details_of(caught) == {
            "published_basis": ["is required when a publication date is set"]
        }
        with pytest.raises(ValidationError) as caught:
            apply_change(session, "document", None, {"title": "Example", "url": EXAMPLE_URL}, ALICE)
        assert details_of(caught) == {"retrieved_at": ["is required when a URL is set"]}
        # Collectors set retrieval times themselves; the rule is for channel ui.
        collected = apply_change(
            session,
            "document",
            None,
            {"title": "Example", "url": EXAMPLE_URL},
            Actor.collector("example", "run_01"),
        )
        assert collected.changed


def test_screening_reason_belongs_to_excluded_documents(db: Db) -> None:
    # CODEBOOK §2.8: excluded "with an exclusion reason"; the PRISMA-style counts per
    # status and reason need both rules.
    with db.session() as session:
        for data, problem in (
            ({"screening_status": "excluded"}, "is required when the document is excluded"),
            (
                {"screening_status": "included", "screening_reason": "reason_a"},
                "is allowed only for excluded documents",
            ),
            ({"screening_reason": "reason_a"}, "is allowed only for excluded documents"),
        ):
            with pytest.raises(ValidationError) as caught:
                apply_change(session, "document", None, {"title": "Example", **data}, ALICE)
            assert details_of(caught) == {"screening_reason": [problem]}
        document_id = apply_change(
            session,
            "document",
            None,
            {"title": "Example", "screening_status": "excluded", "screening_reason": "reason_a"},
            ALICE,
        ).entity_id
        # Including it again needs the reason cleared in the same change.
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "document",
                document_id,
                {"screening_status": "included"},
                ALICE,
                expected_version=1,
            )
        assert details_of(caught) == {
            "screening_reason": ["is allowed only for excluded documents"]
        }
        with pytest.raises(ValidationError):
            apply_change(
                session,
                "document",
                document_id,
                {"screening_reason": None},
                ALICE,
                expected_version=1,
            )
        apply_change(
            session,
            "document",
            document_id,
            {"screening_status": "included", "screening_reason": None},
            ALICE,
            expected_version=1,
        )
        # Other changes do not touch the screening fields and are not checked against them.
        apply_change(
            session, "document", document_id, {"title": "Renamed"}, ALICE, expected_version=2
        )
        assert fields_of(session, "document", document_id)["screening_status"] == "included"


def test_participation_end_not_before_start(db: Db) -> None:
    with db.session() as session:
        project = create_project(session)
        org = apply_change(session, "organization", None, {"name_en": "Example org"}, ALICE)
        base = {
            "organization_id": org.entity_id,
            "subject_id": project.entity_id,
            "role": "partner",
        }
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session, "participation", None, {**base, "start": "2020-05", "end": "2020"}, ALICE
            )
        assert details_of(caught) == {"end": ["must not be before the start"]}
        apply_change(
            session, "participation", None, {**base, "start": "2020-Q2", "end": "2020-04"}, ALICE
        )


def test_relation_ends_must_differ(db: Db) -> None:
    with db.session() as session:
        project = create_project(session)
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "relation",
                None,
                {
                    "from_id": project.entity_id,
                    "to_id": project.entity_id,
                    "relation_type": "relates_a",
                },
                ALICE,
            )
        assert details_of(caught) == {"to_id": ["must differ from from_id"]}


@pytest.mark.parametrize(
    ("target", "valid"),
    [
        ("entity", True),
        ("dimension:D1", True),
        ("dimension:D4", True),
        ("field:name_en", True),
        ("field:verification_status", True),
        ("dimension:D5", False),
        ("field:canonical_url", False),  # not a project field
        ("field:seed_key", False),  # untracked
        ("field:launch", False),  # derived, not tracked
        ("field:unicorn", False),
        ("name_en", False),
    ],
)
def test_evidence_targets(db: Db, target: str, valid: bool) -> None:
    with db.session() as session:
        project = create_project(session)
        data = {"subject_id": project.entity_id, "target": target, "url": EXAMPLE_URL}
        if valid:
            assert apply_change(session, "evidence", None, data, ALICE).changed
        else:
            with pytest.raises(ValidationError) as caught:
                apply_change(session, "evidence", None, data, ALICE)
            assert set(details_of(caught)) == {"target"}


def test_evidence_target_must_not_be_a_system_field(db: Db) -> None:
    with db.session() as session:
        document = apply_change(session, "document", None, {"title": "Example"}, ALICE)
        with pytest.raises(ValidationError):
            apply_change(
                session,
                "evidence",
                None,
                {"subject_id": document.entity_id, "target": "field:text_hash", "url": EXAMPLE_URL},
                ALICE,
            )


def test_evidence_needs_a_document_or_url_and_a_retrieval_time(db: Db) -> None:
    with db.session() as session:
        project = create_project(session)
        base = {"subject_id": project.entity_id, "target": "entity"}
        with pytest.raises(ValidationError) as caught:
            apply_change(session, "evidence", None, base, ALICE)
        assert set(details_of(caught)) == {"document_id", "url"}
        # Without a document, retrieved_at defaults to now on channel ui ...
        created = apply_change(session, "evidence", None, {**base, "url": EXAMPLE_URL}, ALICE)
        row = load(session, "evidence", created.entity_id)
        assert row["retrieved_at"] == row["created_at"]
        assert "retrieved_at" in row["field_meta"]
        # ... and is required on other channels.
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session, "evidence", None, {**base, "url": EXAMPLE_URL}, Actor.importer("x.csv")
            )
        assert details_of(caught) == {"retrieved_at": ["is required when no document is cited"]}
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "evidence",
                created.entity_id,
                {"retrieved_at": None},
                ALICE,
                expected_version=1,
            )
        assert "retrieved_at" in details_of(caught)


def test_evidence_copies_the_target_value_and_has_create_only_fields(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Value at creation")
        created = apply_change(
            session,
            "evidence",
            None,
            {"subject_id": project.entity_id, "target": "field:name_en", "url": EXAMPLE_URL},
            ALICE,
        )
        row = load(session, "evidence", created.entity_id)
        assert row["value_snapshot"] == "Value at creation"
        apply_change(
            session, "project", project.entity_id, {"name_en": "Later"}, ALICE, expected_version=1
        )
        assert load(session, "evidence", created.entity_id)["value_snapshot"] == (
            "Value at creation"
        )
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "evidence",
                created.entity_id,
                {"target": "entity"},
                ALICE,
                expected_version=1,
            )
        assert details_of(caught) == {"target": ["can only be set when the record is created"]}
        with pytest.raises(ValidationError):
            apply_change(
                session,
                "evidence",
                created.entity_id,
                {"value_snapshot": "forged"},
                ALICE,
                expected_version=1,
            )


def test_evidence_for_a_char_range(db: Db) -> None:
    with db.session() as session:
        project = create_project(session)
        base = {"subject_id": project.entity_id, "target": "entity", "url": EXAMPLE_URL}
        with pytest.raises(ValidationError) as caught:
            apply_change(session, "evidence", None, {**base, "char_start": 5, "char_end": 2}, ALICE)
        assert details_of(caught) == {"char_end": ["must not be before char_start"]}
        with pytest.raises(ValidationError):
            apply_change(session, "evidence", None, {**base, "char_start": -1}, ALICE)
        with pytest.raises(ValidationError) as caught:
            apply_change(session, "evidence", None, {**base, "quote": "q" * 1001}, ALICE)
        assert "quote" in details_of(caught)


def test_saved_view_rules(db: Db) -> None:
    with db.session() as session:
        base = {"name": "Example view", "entity_type": "project", "query": "f.status=in:active"}
        assert apply_change(session, "saved_view", None, base, ALICE).changed
        with pytest.raises(ValidationError) as caught:
            apply_change(session, "saved_view", None, {**base, "entity_type": "evidence"}, ALICE)
        assert "entity_type" in details_of(caught)
        with pytest.raises(ValidationError) as caught:
            apply_change(session, "saved_view", None, {**base, "query": "?sort=slug"}, ALICE)
        assert "query" in details_of(caught)


# --------------------------------------------------------------------------------------
# Vocabulary terms
# --------------------------------------------------------------------------------------


def test_new_terms_and_their_rules(db: Db) -> None:
    with db.session() as session:
        base = {"vocabulary": "status", "code": "example_status", "label_en": "Example status"}
        created = apply_change(session, "vocabulary_term", None, base, ALICE)
        assert created.changed
        with pytest.raises(UniqueViolationError) as caught:
            apply_change(session, "vocabulary_term", None, base, ALICE)
        assert caught.value.details is not None
        assert caught.value.details["field"] == "code"
        assert caught.value.details["existing"]["label"] == "status:example_status"
        with pytest.raises(ValidationError) as caught_validation:
            apply_change(session, "vocabulary_term", None, {**base, "vocabulary": "nope"}, ALICE)
        assert "vocabulary" in details_of(caught_validation)
        with pytest.raises(ValidationError):
            apply_change(session, "vocabulary_term", None, {**base, "code": "Bad-Code"}, ALICE)
        with pytest.raises(ValidationError) as caught_validation:
            apply_change(
                session,
                "vocabulary_term",
                created.entity_id,
                {"code": "renamed"},
                ALICE,
                expected_version=1,
            )
        assert details_of(caught_validation) == {
            "code": ["can only be set when the record is created"]
        }


def test_fixed_codes(db: Db) -> None:
    with db.session() as session:
        with pytest.raises(FixedCodeError):
            apply_change(
                session,
                "vocabulary_term",
                None,
                {"vocabulary": "period", "code": "example_period", "label_en": "Example"},
                ALICE,
            )
        with pytest.raises(FixedCodeError):
            apply_change(
                session,
                "vocabulary_term",
                None,
                {
                    "vocabulary": "event_type",
                    "code": "example_fixed",
                    "label_en": "Example",
                    "attributes": {"fixed": True},
                },
                ALICE,
            )
        launch = term_id(session, "event_type", "launch")
        with pytest.raises(FixedCodeError):
            apply_change(
                session, "vocabulary_term", launch, {"active": False}, ALICE, expected_version=1
            )
        with pytest.raises(FixedCodeError):
            apply_change(
                session,
                "vocabulary_term",
                launch,
                {"attributes": {"counts_as_modification": False}},
                ALICE,
                expected_version=1,
            )
        # Labels and definitions of fixed codes stay editable.
        assert apply_change(
            session,
            "vocabulary_term",
            launch,
            {"label_en": "Example launch label", "definition": "Edited."},
            ALICE,
            expected_version=1,
        ).changed
        verified = term_id(session, "verification_status", "verified")
        with pytest.raises(FixedCodeError):
            apply_change(
                session, "vocabulary_term", verified, {"active": False}, ALICE, expected_version=1
            )
        # New terms in vocabularies with only some fixed codes are allowed.
        assert apply_change(
            session,
            "vocabulary_term",
            None,
            {"vocabulary": "event_type", "code": "example_event", "label_en": "Example"},
            ALICE,
        ).changed


def test_replaced_by_rules(db: Db) -> None:
    with db.session() as session:
        planned = term_id(session, "status", "planned")
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "vocabulary_term",
                planned,
                {"replaced_by": "active"},
                ALICE,
                expected_version=1,
            )
        assert details_of(caught) == {"replaced_by": ["is allowed only for inactive terms"]}
        for code, message in (
            ("planned", "must differ from the term's own code"),
            ("retired", "must be an active code of the same vocabulary"),  # inactive
            ("domain_a", "must be an active code of the same vocabulary"),  # other vocabulary
        ):
            with pytest.raises(ValidationError) as caught:
                apply_change(
                    session,
                    "vocabulary_term",
                    planned,
                    {"active": False, "replaced_by": code},
                    ALICE,
                    expected_version=1,
                )
            assert details_of(caught) == {"replaced_by": [message]}
        result = apply_change(
            session,
            "vocabulary_term",
            planned,
            {"active": False, "replaced_by": "active"},
            ALICE,
            expected_version=1,
        )
        assert result.changed
        with pytest.raises(ValidationError):
            apply_change(
                session, "vocabulary_term", planned, {"active": True}, ALICE, expected_version=2
            )


def test_term_attributes_must_be_an_object(db: Db) -> None:
    with db.session() as session, pytest.raises(ValidationError) as caught:
        apply_change(
            session,
            "vocabulary_term",
            None,
            {"vocabulary": "status", "code": "x_y", "label_en": "X", "attributes": [1]},
            ALICE,
        )
    assert details_of(caught) == {"attributes": ["must be an object"]}


# --------------------------------------------------------------------------------------
# Uniqueness
# --------------------------------------------------------------------------------------


def test_slug_is_unique_including_deleted_rows(db: Db) -> None:
    with db.session() as session:
        first = create_project(session, slug="example-unique", name_en="First example")
        with pytest.raises(UniqueViolationError) as caught:
            create_project(session, slug="example-unique")
        assert caught.value.details == {
            "field": "slug",
            "existing": {"id": first.entity_id, "label": "First example", "deleted": False},
        }
        soft_delete(session, "project", first.entity_id, ALICE, expected_version=1)
        with pytest.raises(UniqueViolationError) as caught:
            create_project(session, slug="example-unique")
        assert caught.value.details is not None
        assert caught.value.details["existing"]["deleted"] is True
        other = create_project(session)
        with pytest.raises(UniqueViolationError):
            apply_change(
                session,
                "project",
                other.entity_id,
                {"slug": "example-unique"},
                ALICE,
                expected_version=1,
            )


def test_organization_slugs_may_be_empty(db: Db) -> None:
    with db.session() as session:
        apply_change(session, "organization", None, {"name_en": "Example org one"}, ALICE)
        apply_change(session, "organization", None, {"name_en": "Example org two"}, ALICE)
        apply_change(
            session, "organization", None, {"name_en": "Example three", "slug": "org-x"}, ALICE
        )
        with pytest.raises(UniqueViolationError):
            apply_change(
                session, "organization", None, {"name_en": "Example four", "slug": "org-x"}, ALICE
            )


def test_canonical_url_is_unique_among_live_documents(db: Db) -> None:
    with db.session() as session:
        data = {
            "title": "Example document",
            "url": "https://example.org/doc",
            "retrieved_at": "2026-10-28T10:00:00Z",
        }
        first = apply_change(session, "document", None, data, ALICE)
        with pytest.raises(UniqueViolationError) as caught:
            apply_change(
                session, "document", None, {**data, "url": "https://EXAMPLE.org/doc/#x"}, ALICE
            )
        assert caught.value.details is not None
        assert caught.value.details["field"] == "canonical_url"
        soft_delete(session, "document", first.entity_id, ALICE, expected_version=1)
        assert apply_change(session, "document", None, data, ALICE).changed


def test_evidence_retrieved_at_defaults_to_now_on_channel_ui_only(db: Db) -> None:
    with db.session() as session:
        project = create_project(session)
        document = apply_change(session, "document", None, {"title": "Example"}, ALICE)
        base = {
            "subject_id": project.entity_id,
            "target": "entity",
            "document_id": document.entity_id,
        }
        cited = apply_change(session, "evidence", None, base, ALICE).entity_id
        row = load(session, "evidence", cited)
        assert row["retrieved_at"] == row["created_at"]
        imported = apply_change(session, "evidence", None, base, Actor.importer("x.csv")).entity_id
        assert load(session, "evidence", imported)["retrieved_at"] is None
        explicit = apply_change(
            session, "evidence", None, {**base, "retrieved_at": "2026-01-02T03:04:05Z"}, ALICE
        ).entity_id
        assert load(session, "evidence", explicit)["retrieved_at"] == "2026-01-02T03:04:05.000000Z"
