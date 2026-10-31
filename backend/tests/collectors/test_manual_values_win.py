"""Definition of Done 5: collectors never overwrite manual values; deviations become
proposals (docs/COLLECTORS.md §12.1, docs/DATA_MODEL.md §15.5, §16).

C1 ``ministry_projects`` runs against its fixtures (replay transport) on a fresh database
with the real codebook and seed. A value a person set, accepted, imported, seeded or
verified stays; the collector's differing value becomes an ``update_field`` proposal, and
accept, edit & accept and reject behave as DATA_MODEL §16.4 says. Values the tests write
themselves are obviously synthetic ("Example …", example.org).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mdt.collectors.store import SnapshotStore
from mdt.db.models import Document, Project, RawSnapshot, Revision
from mdt.db.session import read_transaction, write_transaction
from mdt.domain.actor import Actor
from mdt.domain.clock import utc_now
from mdt.domain.document_versions import store_text
from mdt.domain.proposal_actions import accept_proposal, reject_proposal
from mdt.domain.revisions import apply_change, set_field_verification
from mdt.importers.tabular import ImportRequest, dry_run_import, run_import
from tests.collectors.acceptance import Acceptance, acceptance, acceptance_template
from tests.helpers import create_evidence

__all__ = ["acceptance", "acceptance_template"]

C1 = "ministry_projects"
LISTING_URL = "https://thedigital.gov.ua/projects"
MANUAL = "Example description set by hand."
REVIEWED = "Example review note."


def project(acceptance: Acceptance, slug: str) -> dict[str, Any]:
    """The project row of ``slug`` (fields and ``field_meta``)."""
    with acceptance.db.session() as session, read_transaction(session):
        row = (
            session.execute(select(Project.__table__).where(Project.slug == slug)).mappings().one()
        )
        return dict(row)


def edit(
    acceptance: Acceptance,
    slug: str,
    changes: dict[str, Any],
    actor: Actor,
    note: str | None = None,
) -> None:
    """One change of a seed project through the write path."""
    with acceptance.db.session() as session:
        apply_change(session, "project", project(acceptance, slug)["id"], changes, actor, note=note)


def snapshot_of(acceptance: Acceptance, run_id: str, url: str) -> str:
    with acceptance.db.session() as session, read_transaction(session):
        return str(
            session.scalars(
                select(RawSnapshot.id).where(RawSnapshot.run_id == run_id, RawSnapshot.url == url)
            ).one()
        )


def proposals_of(acceptance: Acceptance, slug: str, field: str) -> list[dict[str, Any]]:
    subject = project(acceptance, slug)["id"]
    return acceptance.proposals(kind="update_field", subject_id=subject, field=field)


def test_a_manual_value_wins_and_accepting_takes_the_collected_value(
    acceptance: Acceptance,
) -> None:
    first = acceptance.run(C1, C1)
    brave1 = project(acceptance, "brave1")
    collected = brave1["description_uk"]
    meta = brave1["field_meta"]["description_uk"]
    assert collected
    assert (meta["src"], meta["by"], meta["locked"]) == (
        f"collector:{C1}@{first}",
        f"collector:{C1}",
        False,
    )
    assert meta["raw_snapshot_ids"] == [snapshot_of(acceptance, first, LISTING_URL)]

    edit(acceptance, "brave1", {"description_uk": MANUAL}, Actor.ui())
    second = acceptance.run(C1, C1)
    brave1 = project(acceptance, "brave1")
    assert brave1["description_uk"] == MANUAL
    assert (
        brave1["field_meta"]["description_uk"]["src"],
        brave1["field_meta"]["description_uk"]["locked"],
    ) == ("manual", True)
    [proposal] = proposals_of(acceptance, "brave1", "description_uk")
    assert (proposal["state"], proposal["proposed_value"], proposal["current_value"]) == (
        "open",
        collected,
        MANUAL,
    )
    assert proposal["last_run_id"] == second
    assert proposal["raw_snapshot_id"] == snapshot_of(acceptance, second, LISTING_URL)

    with acceptance.db.session() as session:
        decision = accept_proposal(session, proposal["id"])
    assert decision.changed
    brave1 = project(acceptance, "brave1")
    meta = brave1["field_meta"]["description_uk"]
    assert brave1["description_uk"] == collected
    assert (meta["src"], meta["by"], meta["locked"]) == (f"collector:{C1}@{second}", "user", True)
    assert meta["raw_snapshot_ids"] == proposal["payload"]["field_snapshots"]["description_uk"]
    with acceptance.db.session() as session, read_transaction(session):
        latest = session.scalars(
            select(Revision)
            .where(Revision.entity_id == brave1["id"])
            .order_by(Revision.version.desc())
        ).first()
        assert latest is not None and latest.proposal_id == proposal["id"]

    acceptance.run(C1, C1)  # an accepted value is never proposed again
    [again] = proposals_of(acceptance, "brave1", "description_uk")
    assert (again["id"], again["state"]) == (proposal["id"], "accepted")


def test_edit_and_accept_keeps_the_edited_value_and_a_rejection_is_remembered(
    acceptance: Acceptance,
) -> None:
    acceptance.run(C1, C1)
    for slug in ("diia-city", "virtual-assets"):
        edit(acceptance, slug, {"description_uk": MANUAL}, Actor.ui())
    acceptance.run(C1, C1)
    [city] = proposals_of(acceptance, "diia-city", "description_uk")
    [assets] = proposals_of(acceptance, "virtual-assets", "description_uk")
    edited = "Example description edited while accepting."
    with acceptance.db.session() as session:
        accept_proposal(session, city["id"], values={"description_uk": edited})
        reject_proposal(session, assets["id"], "The manual description is right.")
    diia_city = project(acceptance, "diia-city")
    assert diia_city["description_uk"] == edited
    assert diia_city["field_meta"]["description_uk"]["src"] == "manual"
    assert project(acceptance, "virtual-assets")["description_uk"] == MANUAL
    before = acceptance.state()
    acceptance.run(C1, C1)  # neither decision is reopened
    assert acceptance.state().proposals == before.proposals
    assert [row["state"] for row in proposals_of(acceptance, "diia-city", "description_uk")] == [
        "accepted_modified"
    ]
    assert [
        row["state"] for row in proposals_of(acceptance, "virtual-assets", "description_uk")
    ] == ["rejected"]
    assert project(acceptance, "virtual-assets")["description_uk"] == MANUAL


def test_seeded_imported_and_verified_values_are_kept_too(acceptance: Acceptance) -> None:
    first = acceptance.run(C1, C1)
    earlier = "Example description of an earlier source version."
    # a seed-locked URL list: only the URL to add is proposed
    edit(
        acceptance,
        "mriia",
        {"ministry_urls": ["https://example.org/example-project"]},
        Actor.seed(),
    )
    # an imported value
    imported = "Example description from an import."
    edit(
        acceptance,
        "uresidency",
        {"description_uk": imported},
        Actor.importer("example.csv#000000000000"),
    )
    # a field-verified value: an earlier collected value that a person verified
    edit(acceptance, "diia-engine", {"description_uk": earlier}, Actor.collector(C1, first))
    with acceptance.db.session() as session:
        engine_id = project(acceptance, "diia-engine")["id"]
        evidence = create_evidence(session, engine_id, "description_uk").entity_id
        set_field_verification(
            session,
            "project",
            engine_id,
            "description_uk",
            "verified",
            Actor.ui(),
            evidence_id=evidence,
        )
    # a verified record: every differing field becomes a proposal
    edit(acceptance, "diia-center", {"description_uk": earlier}, Actor.collector(C1, first))
    edit(acceptance, "diia-center", {"verification_status": "verified"}, Actor.ui(), REVIEWED)

    acceptance.run(C1, C1)

    mriia = project(acceptance, "mriia")
    entry_url = "https://thedigital.gov.ua/projects/technologies/mriia"
    assert mriia["ministry_urls"] == ["https://example.org/example-project"]
    [urls] = proposals_of(acceptance, "mriia", "ministry_urls")
    assert (urls["proposed_value"], urls["current_value"]) == (
        [entry_url],
        ["https://example.org/example-project"],
    )
    assert project(acceptance, "uresidency")["description_uk"] == imported
    assert len(proposals_of(acceptance, "uresidency", "description_uk")) == 1
    engine = project(acceptance, "diia-engine")
    assert engine["description_uk"] == earlier
    assert engine["field_meta"]["description_uk"]["verified"] == "verified"
    assert len(proposals_of(acceptance, "diia-engine", "description_uk")) == 1
    assert project(acceptance, "diia-center")["description_uk"] == earlier
    assert len(proposals_of(acceptance, "diia-center", "description_uk")) == 1


def test_a_verified_document_gets_its_new_text_version_as_a_proposal(
    acceptance: Acceptance,
) -> None:
    first = acceptance.run(C1, C1)
    with acceptance.db.session() as session, read_transaction(session):
        document = session.scalars(
            select(Document).where(
                Document.url == "https://thedigital.gov.ua/projects/technologies/brave1"
            )
        ).one()
        document_id, collected_hash = document.id, document.text_hash
    with acceptance.db.session() as session:
        with write_transaction(session):
            earlier = store_text(session, "Example text of an earlier page version.", utc_now())
        apply_change(
            session, "document", document_id, {"text_hash": earlier}, Actor.collector(C1, first)
        )
        apply_change(
            session,
            "document",
            document_id,
            {"verification_status": "verified"},
            Actor.ui(),
            note=REVIEWED,
        )
    acceptance.run(C1, C1)
    with acceptance.db.session() as session, read_transaction(session):
        assert session.get(Document, document_id).text_hash == earlier  # type: ignore[union-attr]
    [proposal] = acceptance.proposals(
        kind="update_field", subject_id=document_id, field="text_hash"
    )
    assert (proposal["proposed_value"], proposal["current_value"]) == (collected_hash, earlier)
    assert proposal["payload"]["extraction_method"] == "turbo-stream"


def test_an_import_never_overwrites_a_manual_value(acceptance: Acceptance) -> None:
    acceptance.run(C1, C1)
    edit(acceptance, "brave1", {"description_uk": MANUAL}, Actor.ui())
    body = b"slug,description_uk\nbrave1,Example description from an import.\n"
    store = SnapshotStore(acceptance.settings.raw_path)
    with acceptance.db.session() as session:
        upload = store.put_upload(session, [body], "example.csv")
    request = ImportRequest(
        upload_id=upload.id,
        entity_type="project",
        mapping={"slug": "slug", "description_uk": "description_uk"},
        key_field="slug",
    )
    with acceptance.db.session() as session:
        plan = dry_run_import(session, acceptance.settings, request)
    [row] = plan.rows
    assert row.action == "unchanged" and row.changes == {}
    assert [(item["field"], item["reason"]) for item in row.conflicts] == [
        ("description_uk", "manual")
    ]
    with acceptance.db.session() as session:
        result = run_import(session, acceptance.settings, request)
    assert result.import_run["stats"]["conflicts"] == 1
    assert project(acceptance, "brave1")["description_uk"] == MANUAL
