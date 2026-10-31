"""Documents in the reconciler (docs/DATA_MODEL.md §15.6, §15.8, §15.9): the text version
as one unit, suggested links (also on a locked ``links`` field), event proposals of the
tagger, and the built-in tagger's write unit. Synthetic values only."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mdt.collectors.base import LinkHint, Outcome
from mdt.collectors.parsing.texts import text_hash
from mdt.db.models import DocumentText, Proposal
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.document_versions import tag_document
from mdt.domain.reconcile import reconcile_candidate
from mdt.domain.revisions import apply_change, restore_version
from tests.domain_p2.conftest import P2, StubScope, candidate
from tests.helpers import create_project, fields_of, load

USER = Actor.ui()
DOC_URL = "https://example.org/docs/one"
TEXT = "Example Zeta went live today.\nA second line without a name."
OTHER_TEXT = "Example Zeta went live again.\nAnother line."


def zeta(p2: P2, **overrides: Any) -> str:
    with p2.session() as session:
        return create_project(session, name_en="Example Zeta", **overrides).entity_id


def document(p2: P2, scope: StubScope, text: str | None = TEXT, **kwargs: Any) -> Any:
    snapshot = kwargs.pop("snapshot", None) or p2.snapshot(scope.run_id, DOC_URL)
    fields = {"title": "Example document", "url": DOC_URL, "language": "lang_a"}
    fields.update(kwargs.pop("fields", {}))
    return candidate(
        "document",
        kwargs.pop("key", "doc:one"),
        snapshot,
        url=DOC_URL,
        fields=fields,
        text=text,
        extraction_method=kwargs.pop("extraction_method", "html"),
        **kwargs,
    )


def run(p2: P2, scope: StubScope, *items: Any) -> list[Outcome]:
    with p2.session() as session:
        return [reconcile_candidate(session, scope, item) for item in items]


def test_a_new_document_gets_its_text_version_links_and_event_proposals(p2: P2) -> None:
    subject = zeta(p2)
    scope = p2.scope()
    snapshot = p2.snapshot(scope.run_id, DOC_URL, fetched_at="2026-01-02T03:04:05.000000Z")
    [outcome] = run(p2, scope, document(p2, scope, snapshot=snapshot, external_id="ext-1"))
    assert outcome.action == "created" and outcome.record_id is not None
    with p2.session() as session:
        values = fields_of(session, "document", outcome.record_id)
        with read_transaction(session):
            stored = session.get(DocumentText, text_hash(TEXT))
            assert stored is not None and stored.text == TEXT
    assert values["text_hash"] == text_hash(TEXT)
    assert (values["raw_snapshot_id"], values["retrieved_at"], values["extraction_method"]) == (
        snapshot,
        "2026-01-02T03:04:05.000000Z",
        "html",
    )
    assert (values["source_id"], values["external_id"]) == ("stub", "ext-1")
    assert values["canonical_url"] == DOC_URL
    [link] = values["links"]
    assert (link["subject_id"], link["origin"], link["state"]) == (subject, "auto", "suggested")
    assert link["matched_aliases"] == ["Example Zeta"] and link["match_count"] == 1
    [proposal] = p2.proposals(Proposal.kind == "create_event")
    assert (proposal["collector"], proposal["subject_id"], proposal["entity_type"]) == (
        "tagger",
        subject,
        "event",
    )
    assert proposal["quote"] == "Example Zeta went live today."
    evidence = proposal["payload"]["evidence"]
    assert evidence["document_id"] == outcome.record_id
    assert (evidence["char_start"], evidence["char_end"]) == (0, len(proposal["quote"]))
    assert (evidence["raw_snapshot_id"], evidence["retrieved_at"]) == (
        snapshot,
        "2026-01-02T03:04:05.000000Z",
    )
    assert proposal["payload"]["event"]["date"] is None  # the document has no publication date
    assert proposal["payload"]["pattern_id"] == "example_launch"
    assert scope.counts["links_suggested"] == 1
    assert scope.memory["mdt.duplicate_candidates"]["document"] == {outcome.record_id}


def test_an_unchanged_text_writes_nothing(p2: P2) -> None:
    zeta(p2)
    first = p2.scope()
    [created] = run(p2, first, document(p2, first))
    revisions, proposals = p2.revisions(), len(p2.proposals())
    later = p2.scope()
    [outcome] = run(p2, later, document(p2, later))
    # The tagger runs only over a new or changed text, so nothing is raised again either.
    assert outcome == Outcome("unchanged", created.record_id, ())
    assert p2.revisions() == revisions and len(p2.proposals()) == proposals


def test_a_changed_text_of_its_own_source_is_written_as_one_unit(p2: P2) -> None:
    zeta(p2)
    first = p2.scope()
    [created] = run(p2, first, document(p2, first))
    assert created.record_id is not None
    later = p2.scope()
    snapshot = p2.snapshot(later.run_id, DOC_URL, body=b"<html>changed</html>")
    [outcome] = run(p2, later, document(p2, later, text=OTHER_TEXT, snapshot=snapshot))
    assert outcome.action == "updated"
    with p2.session() as session:
        values = fields_of(session, "document", created.record_id)
        entry = load(session, "document", created.record_id)["field_meta"]["text_hash"]
    assert (values["text_hash"], values["raw_snapshot_id"]) == (text_hash(OTHER_TEXT), snapshot)
    assert entry["raw_snapshot_ids"] == [snapshot] and entry["locked"] is False
    assert later.memory["mdt.duplicate_candidates"]["document"] == {created.record_id}


def test_a_changed_text_with_a_corrected_retrieval_time_is_proposed(p2: P2) -> None:
    zeta(p2)
    first = p2.scope()
    [created] = run(p2, first, document(p2, first))
    assert created.record_id is not None
    with p2.session() as session:
        apply_change(
            session,
            "document",
            created.record_id,
            {"retrieved_at": "2025-05-05T05:05:05Z"},
            USER,
        )
    later = p2.scope()
    snapshot = p2.snapshot(later.run_id, DOC_URL, body=b"<html>changed</html>")
    [outcome] = run(p2, later, document(p2, later, text=OTHER_TEXT, snapshot=snapshot))
    assert outcome.action == "proposed"
    [proposal] = p2.proposals(Proposal.field == "text_hash")
    assert (proposal["current_value"], proposal["proposed_value"]) == (
        text_hash(TEXT),
        text_hash(OTHER_TEXT),
    )
    assert proposal["payload"]["raw_snapshot_id"] == snapshot
    assert proposal["payload"]["extraction_method"] == "html"
    assert proposal["payload"]["char_count"] == len(OTHER_TEXT)
    with p2.session() as session:
        assert fields_of(session, "document", created.record_id)["text_hash"] == text_hash(TEXT)


def test_a_document_of_another_source_gets_a_text_version_proposal(p2: P2) -> None:
    zeta(p2)
    first = p2.scope(collector="other")
    [created] = run(p2, first, document(p2, first, key="doc:other"))
    later = p2.scope()
    [outcome] = run(p2, later, document(p2, later, text=OTHER_TEXT))
    assert outcome.record_id == created.record_id and outcome.action == "proposed"
    assert len(p2.proposals(Proposal.field == "text_hash")) == 1


def test_link_suggestions_are_added_even_to_a_locked_links_field(p2: P2) -> None:
    subject = zeta(p2)
    with p2.session() as session:
        other = create_project(session, name_en="Example Omega").entity_id
    first = p2.scope()
    [created] = run(p2, first, document(p2, first, text=None, extraction_method="listing_only"))
    assert created.record_id is not None
    with p2.session() as session:  # the person rejects nothing yet but sets links: locked
        apply_change(
            session,
            "document",
            created.record_id,
            {"links": [{"subject_id": subject, "state": "rejected"}]},
            USER,
        )
        entry_before = load(session, "document", created.record_id)["field_meta"]["links"]
    later = p2.scope()
    hints = [LinkHint("Project page", subject_id=subject), LinkHint("Other", subject_id=other)]
    [outcome] = run(
        p2, later, document(p2, later, text=None, extraction_method="listing_only", links=hints)
    )
    assert outcome.action == "updated"
    with p2.session() as session:
        links = fields_of(session, "document", created.record_id)["links"]
        entry_after = load(session, "document", created.record_id)["field_meta"]["links"]
    assert [(link["subject_id"], link["origin"], link["state"]) for link in links] == sorted(
        [(subject, "manual", "rejected"), (other, "auto", "suggested")]
    )
    assert entry_after == entry_before  # suggestions leave the person's entry unchanged


def test_a_link_hint_by_key_follows_the_binding(p2: P2) -> None:
    subject = zeta(p2, ministry_urls=["https://example.org/projects/zeta"])
    scope = p2.scope()
    project_item = candidate(
        "project",
        "entry:zeta",
        p2.snapshot(scope.run_id),
        url="https://example.org/projects/zeta",
    )
    hint = LinkHint("Project page", subject_key="entry:zeta")
    outcomes = run(
        p2,
        scope,
        project_item,
        document(p2, scope, text=None, extraction_method="none", links=[hint]),
    )
    assert outcomes[1].record_id is not None
    with p2.session() as session:
        links = fields_of(session, "document", outcomes[1].record_id)["links"]
    assert [(link["subject_id"], link["snippet"]) for link in links] == [(subject, "Project page")]


def test_a_source_stated_link_keeps_its_snippet_and_takes_the_tagger_details(p2: P2) -> None:
    subject = zeta(p2)
    scope = p2.scope()
    hint = LinkHint("Official page of the project", subject_id=subject)
    [outcome] = run(p2, scope, document(p2, scope, links=[hint]))
    assert outcome.record_id is not None
    with p2.session() as session:
        [link] = fields_of(session, "document", outcome.record_id)["links"]
    assert (link["subject_id"], link["snippet"]) == (subject, "Official page of the project")
    assert link["matched_aliases"] == ["Example Zeta"] and link["match_count"] == 1


def test_the_document_rule_matches_by_canonical_url(p2: P2) -> None:
    with p2.session() as session:
        manual = apply_change(
            session,
            "document",
            None,
            {
                "title": "Manual",
                "url": DOC_URL + "/?utm_source=x",
                "retrieved_at": "2025-01-01T00:00:00Z",
            },
            USER,
        ).entity_id
    scope = p2.scope()
    [outcome] = run(p2, scope, document(p2, scope, fields={"title": "Collected title"}))
    assert outcome.record_id == manual
    with p2.session() as session:
        values = fields_of(session, "document", manual)
    assert values["source_id"] is None and values["title"] == "Manual"
    assert {p["field"] for p in p2.proposals(Proposal.kind == "update_field")} >= {"title"}


def test_the_tagger_tags_a_stored_document_once(p2: P2) -> None:
    first = p2.scope()
    [created] = run(p2, first, document(p2, first))  # no project yet: no links, no events
    assert created.record_id is not None and p2.proposals() == []
    subject = zeta(p2)
    tagger = p2.scope(collector="tagger")
    with p2.session() as session:
        outcome = tag_document(session, tagger, created.record_id)
    assert outcome.action == "updated" and len(outcome.proposal_ids) == 1
    with p2.session() as session:
        links = fields_of(session, "document", created.record_id)["links"]
        revision = load(session, "document", created.record_id)
    assert [link["subject_id"] for link in links] == [subject]
    assert revision["updated_by"] == "collector:tagger"
    again = p2.scope(collector="tagger")
    revisions = p2.revisions()
    with p2.session() as session:
        second = tag_document(session, again, created.record_id)
    assert second.action == "proposed" and p2.revisions() == revisions
    with p2.session() as session, read_transaction(session):
        [event] = session.scalars(select(Proposal).where(Proposal.kind == "create_event")).all()
        assert event.seen_count == 2 and event.collector == "tagger"


def test_restoring_the_retrieval_time_restores_the_whole_text_version(p2: P2) -> None:
    first = p2.scope()
    [created] = run(p2, first, document(p2, first))
    assert created.record_id is not None
    later = p2.scope()
    snapshot = p2.snapshot(later.run_id, DOC_URL, body=b"<html>changed</html>")
    run(p2, later, document(p2, later, text=OTHER_TEXT, snapshot=snapshot))
    with p2.session() as session:
        preview = restore_version(
            session,
            "document",
            created.record_id,
            1,
            Actor.restore(),
            fields=["retrieved_at"],
            dry_run=True,
        )
    assert set(preview.changes) == {"retrieved_at", "text_hash", "raw_snapshot_id"}
    assert preview.skipped_fields == []
    with p2.session() as session:
        restore_version(
            session, "document", created.record_id, 1, Actor.restore(), fields=["retrieved_at"]
        )
        values = fields_of(session, "document", created.record_id)
    assert values["text_hash"] == text_hash(TEXT) and values["raw_snapshot_id"] != snapshot
    with p2.session() as session:  # never without the retrieval time
        result = restore_version(
            session, "document", created.record_id, 2, Actor.restore(), fields=["text_hash"]
        )
    assert (result.changed, result.skipped_fields) == (False, ["text_hash"])
