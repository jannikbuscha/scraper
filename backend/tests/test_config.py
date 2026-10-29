"""Settings from the environment and an optional .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mdt.config import BACKEND_DIR, REPO_ROOT, Settings, split_csv

VARIABLES = (
    "HOST",
    "PORT",
    "DATA_DIR",
    "DATABASE_URL",
    "CODEBOOK_DIR",
    "SEED_DIR",
    "FRONTEND_DIST",
    "ALLOWED_HOSTS",
    "TEAM_MEMBERS",
    "MAX_COMMENT_CHARS",
    "FOCAL_ORG_SEED_KEY",
    "CONTACT_EMAIL",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_repository_root_is_the_parent_of_backend() -> None:
    assert BACKEND_DIR == REPO_ROOT / "backend"
    assert (BACKEND_DIR / "pyproject.toml").is_file()
    assert (REPO_ROOT / "codebook").is_dir()


def test_defaults() -> None:
    current = settings()
    assert (current.host, current.port) == ("127.0.0.1", 8080)
    assert current.data_path == REPO_ROOT / "data"
    assert current.sqlalchemy_url == f"sqlite:///{REPO_ROOT / 'data' / 'app.db'}"
    assert current.codebook_path == REPO_ROOT / "codebook"
    assert current.seed_path == REPO_ROOT / "seed"
    assert current.frontend_dist_path == REPO_ROOT / "frontend" / "dist"
    assert current.allowed_hosts_list == ["127.0.0.1", "localhost"]
    assert current.team_members_list == []
    assert current.max_comment_chars == 10_000
    assert current.focal_org_seed_key == "ministry-of-digital-transformation"
    assert current.contact_email is None
    assert current.log_level == "INFO"


def test_comma_separated_lists_are_not_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", " Example.org, localhost ,, ")
    monkeypatch.setenv("TEAM_MEMBERS", "Alice Example,Bob Example")
    current = settings()
    assert current.allowed_hosts_list == ["example.org", "localhost"]
    assert current.team_members_list == ["Alice Example", "Bob Example"]
    monkeypatch.setenv("ALLOWED_HOSTS", "")
    monkeypatch.setenv("TEAM_MEMBERS", "")
    empty = settings()
    assert empty.allowed_hosts_list == [] and empty.team_members_list == []
    assert split_csv(None) == []


def test_paths_resolve_against_the_repository_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATA_DIR", "var/data")
    monkeypatch.setenv("CODEBOOK_DIR", str(tmp_path / "codebook"))
    monkeypatch.chdir(tmp_path)
    current = settings()
    assert current.data_path == REPO_ROOT / "var" / "data"
    assert current.codebook_path == tmp_path / "codebook"  # absolute values win


def test_database_url_and_data_directories(tmp_path: Path) -> None:
    explicit = settings(database_url="sqlite:////srv/example/app.db")
    assert explicit.sqlalchemy_url == "sqlite:////srv/example/app.db"
    data = tmp_path / "nested" / "data"
    current = settings(data_dir=data)
    current.ensure_data_dirs()
    assert data.is_dir()
    other = tmp_path / "elsewhere" / "db"
    settings(data_dir=data, database_url=f"sqlite:///{other / 'app.db'}").ensure_data_dirs()
    assert other.is_dir()
    settings(data_dir=data, database_url="sqlite://").ensure_data_dirs()  # in memory


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", " debug ")
    assert settings().log_level == "DEBUG"
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with pytest.raises(ValidationError):
        settings()


def test_env_file_is_read(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PORT=9090\nTEAM_MEMBERS=Alice Example\nUNRELATED=1\nCONTACT_EMAIL=contact@example.org\n",
        encoding="utf-8",
    )
    current = Settings(_env_file=env_file)  # type: ignore[call-arg]
    assert current.port == 9090
    assert current.team_members_list == ["Alice Example"]
    assert current.contact_email == "contact@example.org"


def test_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "70000")
    with pytest.raises(ValidationError):
        settings()
