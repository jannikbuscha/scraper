"""``mdt import`` (docs/COLLECTORS.md §9.1, §11): the file is stored as an upload, then
planned or run. All values are synthetic."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mdt import cli
from mdt.config import get_settings
from tests import synthetic

runner = CliRunner()


@pytest.fixture
def environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, codebook_dir: Path, seed_dir: Path
) -> Iterator[Path]:
    """A migrated and seeded database configured through environment variables."""
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{data / 'app.db'}")
    monkeypatch.setenv("CODEBOOK_DIR", str(codebook_dir))
    monkeypatch.setenv("SEED_DIR", str(seed_dir))
    monkeypatch.setenv("FOCAL_ORG_SEED_KEY", synthetic.FOCAL_ORG_SEED_KEY)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    assert invoke("db", "upgrade").exit_code == 0
    assert invoke("seed").exit_code == 0
    yield tmp_path
    get_settings.cache_clear()


def invoke(*args: str) -> Any:
    return runner.invoke(cli.app, list(args))


def test_dry_run_then_run(environment: Path) -> None:
    file = environment / "projects.csv"
    file.write_text("slug,name_en,scope_note\nexample-a,Example A,Synthetic scope\n", "utf-8")
    dry = invoke("import", str(file), "--type", "project", "--key", "slug", "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert "mapping: slug → slug, name_en → name_en, scope_note → scope_note" in dry.output
    assert "create 1" in dry.output and "dry run: nothing was written" in dry.output
    run = invoke("import", str(file), "--type", "project", "--key", "slug", "--note", "Synthetic")
    assert run.exit_code == 0, run.output
    assert "row 2: create prj_" in run.output
    assert ": done (provenance import:projects.csv#" in run.output
    again = invoke("import", str(file), "--type", "project", "--key", "slug")
    assert again.exit_code == 0 and "unchanged 1" in again.output
    checked = invoke("check")
    assert checked.exit_code == 0, checked.output


def test_explicit_mappings_and_errors(environment: Path) -> None:
    file = environment / "data.csv"
    file.write_text("Slug;Name\nexample-b;Example B\n", "utf-8")
    run = invoke(
        "import", str(file), "--type", "project", "--map", "Slug=slug", "--map", "Name=name_en"
    )
    assert run.exit_code == 0, run.output
    assert "error scope_note" in run.output
    bad = invoke("import", str(file), "--type", "project", "--map", "Name=seed_key")
    assert bad.exit_code == 1 and "error: mapping.Name" in bad.output
    malformed = invoke("import", str(file), "--type", "project", "--map", "Name")
    assert malformed.exit_code != 0
    empty = environment / "empty.csv"
    empty.write_bytes(b"")
    assert invoke("import", str(empty), "--type", "project").exit_code == 1
    assert invoke("import", str(environment / "missing.csv"), "--type", "project").exit_code == 1
