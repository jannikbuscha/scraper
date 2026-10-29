"""Application settings from environment variables and an optional ``.env`` file.

Relative paths (``DATA_DIR``, ``CODEBOOK_DIR``, ``SEED_DIR``, ``FRONTEND_DIST`` and the
``.env`` file itself) resolve against the repository root, so the CLI behaves the same
whether it runs from the repository root (``uv run --project backend mdt``), from
``backend/`` or inside the container (``/app``). Absolute values are used unchanged.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


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
