"""Who writes: the :class:`Actor` of a write unit.

The app has one user and no login: every write through the web app is attributed to
:data:`USER_NAME`, on channel ``ui`` (``restore`` for restores, ``merge`` for merges and
unmerges). The channels ``seed``, ``collector``, ``import`` and ``system`` are reachable only
from the CLI and in-process jobs (DATA_MODEL §6.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

Channel = Literal["seed", "ui", "collector", "import", "restore", "merge", "system"]
CHANNELS: tuple[Channel, ...] = ("seed", "ui", "collector", "import", "restore", "merge", "system")
#: Channels of HTTP clients: they may only write editable fields.
CLIENT_CHANNELS: frozenset[str] = frozenset({"ui", "restore", "merge"})
#: The name recorded for every write through the web app.
USER_NAME: Final = "user"


@dataclass(frozen=True)
class Actor:
    """The author and channel of a write.

    ``name`` is :data:`USER_NAME` on the client channels; for machine channels the
    constructors set it (``seed``, ``import:<file>``, ``collector:<name>``).
    """

    name: str
    channel: Channel
    run_id: str | None = None
    file: str | None = None
    #: The proposal a write accepts (``revision.proposal_id``, DATA_MODEL §16.4).
    proposal_id: str | None = None
    #: ``field_meta.src`` of the values taken unchanged from that proposal's source.
    proposal_src: str | None = None

    @classmethod
    def ui(cls) -> Actor:
        """The user editing through the web app."""
        return cls(name=USER_NAME, channel="ui")

    @classmethod
    def accept(cls, proposal_id: str, proposal_src: str) -> Actor:
        """The user accepting a proposal (channel ``ui``): values observed in a source and
        taken unchanged get ``proposal_src`` (``collector:<name>@<run_id>``), DATA_MODEL §5."""
        return cls(name=USER_NAME, channel="ui", proposal_id=proposal_id, proposal_src=proposal_src)

    @classmethod
    def merge(cls, proposal_id: str | None = None) -> Actor:
        """The user merging or unmerging records (DATA_MODEL §18); ``proposal_id`` is the
        ``possible_duplicate`` proposal a merge accepts."""
        return cls(name=USER_NAME, channel="merge", proposal_id=proposal_id)

    @classmethod
    def restore(cls) -> Actor:
        """The user restoring an old version."""
        return cls(name=USER_NAME, channel="restore")

    @classmethod
    def seed(cls) -> Actor:
        """The seed loader (``mdt seed``)."""
        return cls(name="seed", channel="seed")

    @classmethod
    def importer(cls, file: str) -> Actor:
        """A tabular import from ``file``."""
        return cls(name=f"import:{file}", channel="import", file=file)

    @classmethod
    def collector(cls, collector: str, run_id: str) -> Actor:
        """A collector run (Phase 2)."""
        return cls(name=f"collector:{collector}", channel="collector", run_id=run_id)

    @classmethod
    def system(cls) -> Actor:
        """In-process maintenance."""
        return cls(name="system", channel="system")

    @property
    def by(self) -> str:
        """Value of ``created_by``/``updated_by``, ``revision.author`` and ``field_meta.by``."""
        return self.name

    @property
    def is_client(self) -> bool:
        """True for HTTP channels (``ui``, ``restore``, ``merge``)."""
        return self.channel in CLIENT_CHANNELS

    def as_restore(self) -> Actor:
        """The same actor on channel ``restore``."""
        return Actor(name=self.name, channel="restore", run_id=self.run_id, file=self.file)
