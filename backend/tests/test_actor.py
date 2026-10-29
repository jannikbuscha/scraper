"""Actors per channel (DATA_MODEL §6.2): the user on the client channels, fixed names on
the machine channels."""

from __future__ import annotations

from mdt.domain.actor import USER_NAME, Actor


def test_actor_constructors() -> None:
    assert USER_NAME == "user"
    assert Actor.ui() == Actor("user", "ui")
    assert Actor.restore() == Actor("user", "restore")
    assert Actor.ui().is_client
    assert Actor.restore().is_client
    assert Actor.ui().as_restore() == Actor.restore()
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
