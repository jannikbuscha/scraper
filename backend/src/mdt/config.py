"""Application settings from environment variables and an optional ``.env`` file.

Relative paths (``DATA_DIR``, ``CODEBOOK_DIR``, ``SEED_DIR``, ``FRONTEND_DIST``,
``SOURCES_FILE``, ``COLLECTOR_REPLAY_DIR`` and the ``.env`` file itself) resolve against the
repository root, so the CLI behaves the same whether it runs from the repository root
(``uv run --project backend mdt``), from ``backend/`` or inside the container (``/app``).
Absolute values are used unchanged.

The collector settings and the rules for ``CONTACT_EMAIL`` are those of
docs/COLLECTORS.md §3 and §4.4.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

#: A plain e-mail address as it may appear in the User-Agent (no spaces, quotes,
#: parentheses or semicolons, which would break the header's comment syntax).
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
#: Reserved example domains (RFC 2606, RFC 6761): a contact address there reaches nobody,
#: so it is refused like a missing one (the ``.env.example`` placeholder is one of them).
RESERVED_EMAIL_DOMAINS = ("example.org", "example.com", "example.net", "localhost")
RESERVED_EMAIL_TLDS = ("example", "invalid", "test", "localhost")
#: The optional project URL of the User-Agent: http(s), no whitespace, parentheses or ";".
_PROJECT_URL_RE = re.compile(r"^https?://[^\s();]+$")


def _detect_repo_root() -> Path:
    """Return the repository root: the parent of ``backend/`` for the source checkout.

    The package lives at ``<root>/backend/src/mdt``; this holds for the editable install
    in Docker (``/app/backend``) and for local development. Outside such a layout the
    current working directory is used.
    """
    package_dir = Path(__file__).resolve().parent
    backend_dir = package_dir.parents[1]
    if (backend_dir / "pyproject.toml").is_file() and backend_dir.name == "backend":
        return backend_dir.parent
    return Path.cwd()


REPO_ROOT = _detect_repo_root()
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path)


def _upper_log_level(value: str) -> str:
    level = value.strip().upper()
    if level not in _LOG_LEVELS:
        raise ValueError(f"LOG_LEVEL must be one of {', '.join(_LOG_LEVELS)}")
    return level


def _check_project_url(value: str) -> str:
    url = value.strip()
    if url and not _PROJECT_URL_RE.fullmatch(url):
        raise ValueError("PROJECT_URL must be an http(s) URL without spaces, parentheses or ';'")
    return url


def _empty_to_none(value: Any) -> Any:
    """An empty setting (e.g. ``COLLECTOR_REPLAY_DIR=``, as compose pins it) means unset."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def contact_email_problem(value: str | None) -> str | None:
    """Why ``value`` cannot serve as ``CONTACT_EMAIL`` for collector runs and manual
    fetches, or None if it can (docs/COLLECTORS.md §4.4). The message never repeats the
    address."""
    address = (value or "").strip()
    if not address:
        return "CONTACT_EMAIL is not set in .env; collectors need a contact address"
    if not _EMAIL_RE.fullmatch(address):
        return "CONTACT_EMAIL is not set to a plain e-mail address"
    domain = address.rsplit("@", 1)[1].lower()
    reserved = domain in RESERVED_EMAIL_DOMAINS or any(
        domain.endswith(f".{name}") for name in RESERVED_EMAIL_DOMAINS
    )
    if reserved or domain.rsplit(".", 1)[-1] in RESERVED_EMAIL_TLDS:
        return (
            "CONTACT_EMAIL is not set to a real address (a reserved example domain such as "
            "the .env.example placeholder)"
        )
    return None


class Settings(BaseSettings):
    """Runtime configuration. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    data_dir: Path = Path("data")
    database_url: str | None = None
    codebook_dir: Path = Path("codebook")
    seed_dir: Path = Path("seed")
    frontend_dist: Path = Path("frontend/dist")
    max_comment_chars: int = Field(default=10_000, ge=1)
    focal_org_seed_key: str = "ministry-of-digital-transformation"
    contact_email: str | None = None
    project_url: Annotated[str, AfterValidator(_check_project_url)] = ""
    sources_file: Path = Path("sources.yaml")
    run_stale_after_s: int = Field(default=300, ge=1)
    collector_replay_dir: Annotated[Path | None, BeforeValidator(_empty_to_none)] = None
    collector_run_inline: bool = False
    log_level: Annotated[str, AfterValidator(_upper_log_level)] = "INFO"

    @property
    def data_path(self) -> Path:
        """Absolute data directory."""
        return _resolve(self.data_dir)

    @property
    def codebook_path(self) -> Path:
        """Absolute codebook directory (vocabulary YAML files and parameters.yaml)."""
        return _resolve(self.codebook_dir)

    @property
    def seed_path(self) -> Path:
        """Absolute seed directory (projects.yaml)."""
        return _resolve(self.seed_dir)

    @property
    def frontend_dist_path(self) -> Path:
        """Absolute directory of the built frontend."""
        return _resolve(self.frontend_dist)

    @property
    def sources_path(self) -> Path:
        """Absolute path of ``sources.yaml`` (docs/COLLECTORS.md §3)."""
        return _resolve(self.sources_file)

    @property
    def replay_path(self) -> Path | None:
        """Absolute fixture directory of replay mode, or None (docs/COLLECTORS.md §4.10)."""
        return None if self.collector_replay_dir is None else _resolve(self.collector_replay_dir)

    @property
    def raw_path(self) -> Path:
        """Directory of the raw snapshot files (docs/DATA_MODEL.md §14.1)."""
        return self.data_path / "raw"

    @property
    def sqlalchemy_url(self) -> str:
        """The database URL; defaults to ``sqlite:///<DATA_DIR>/app.db``."""
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_path / 'app.db'}"

    def ensure_data_dirs(self) -> None:
        """Create ``DATA_DIR`` and the directory of a file-based SQLite database if missing."""
        self.data_path.mkdir(parents=True, exist_ok=True)
        url = make_url(self.sqlalchemy_url)
        if url.get_backend_name() != "sqlite":
            return
        database = url.database
        if not database or database == ":memory:" or database.startswith("file:"):
            return
        Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings (read once)."""
    return Settings()
