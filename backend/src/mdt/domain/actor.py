"""Who writes: the :class:`Actor` of a write unit and author-name validation.

Authors are attribution, not authentication (there is no login). The HTTP layer calls
:func:`parse_author_header` for the ``X-Author`` header and passes ``Actor.ui(name)``
to the domain functions. The channels ``seed``, ``collector``, ``import``, ``merge`` and
``system`` are reachable only from the CLI and in-process jobs (DATA_MODEL §6.2).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote

from mdt.domain.errors import AuthorInvalidError, AuthorRequiredError

Channel = Literal["seed", "ui", "collector", "import", "restore", "merge", "system"]
CHANNELS: tuple[Channel, ...] = ("seed", "ui", "collector", "import", "restore", "merge", "system")
#: Channels of HTTP clients: they may only write editable fields.
CLIENT_CHANNELS: frozenset[str] = frozenset({"ui", "restore"})

MAX_AUTHOR_LENGTH = 100
_REJECTED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"})
_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
_RESERVED_PREFIX = re.compile(r"^[A-Za-z_]+:")
# After the character check only space separators (Zs) remain as whitespace.
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Actor:
    """The author and channel of a write.

    ``name`` is the person's name on channels ``ui``/``restore``/``merge``; for machine
    channels the constructors set it (``seed``, ``import:<file>``, ``collector:<name>``).
    """

    name: str
    channel: Channel
    run_id: str | None = None
    file: str | None = None

    @classmethod
    def ui(cls, name: str) -> Actor:
        """A person editing through the web app; the name is validated again, so no
        person can be recorded under a reserved or malformed name."""
        return cls(name=validate_author_name(name), channel="ui")

    @classmethod
    def restore(cls, name: str) -> Actor:
        """A person restoring an old version (name validated like :meth:`ui`)."""
        return cls(name=validate_author_name(name), channel="restore")

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
        """True for HTTP channels (``ui``, ``restore``)."""
        return self.channel in CLIENT_CHANNELS

    def as_restore(self) -> Actor:
        """The same person on channel ``restore``."""
        return Actor(name=self.name, channel="restore", run_id=self.run_id, file=self.file)


def validate_author_name(raw: str) -> str:
    """Validate and normalise a decoded author name (DATA_MODEL §7).

    Rejects control, format, private-use, surrogate, unassigned, line and paragraph
    separator characters and commas anywhere; then trims, collapses runs of spaces to
    one space and checks the length (1-100) and the reserved names.
    """
    name = unicodedata.normalize("NFC", raw)
    for char in name:
        if char == "," or unicodedata.category(char) in _REJECTED_CATEGORIES:
            raise AuthorInvalidError("The author name contains a character that is not allowed")
    name = _SPACES.sub(" ", name).strip(" ")
    if not name:
        raise AuthorInvalidError("The author name is empty")
    if len(name) > MAX_AUTHOR_LENGTH:
        raise AuthorInvalidError(f"The author name must be at most {MAX_AUTHOR_LENGTH} characters")
    if name.casefold() in ("seed", "system") or _RESERVED_PREFIX.match(name):
        raise AuthorInvalidError("The author name is reserved")
    return name


def parse_author_header(values: Sequence[str]) -> str:
    """Decode and validate the ``X-Author`` header values (percent-encoded UTF-8).

    Missing → :class:`AuthorRequiredError`; repeated, badly encoded or invalid →
    :class:`AuthorInvalidError`.
    """
    if not values:
        raise AuthorRequiredError()
    if len(values) > 1:
        raise AuthorInvalidError("The X-Author header must occur only once")
    encoded = values[0]
    if _BAD_PERCENT.search(encoded):
        raise AuthorInvalidError("The X-Author header is not percent-encoded correctly")
    try:
        decoded = unquote(encoded, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AuthorInvalidError("The X-Author header is not valid UTF-8") from exc
    return validate_author_name(decoded)
