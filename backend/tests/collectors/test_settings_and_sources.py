"""Collector settings (docs/COLLECTORS.md §3, §4.4) and ``sources.yaml``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from mdt.collectors.sources import SourcesError, load_sources, parse_sources
from mdt.config import REPO_ROOT, Settings, contact_email_problem

#: A syntactically valid address in a non-reserved, non-public domain (RFC 6762 style
#: private-use label): it passes the CONTACT_EMAIL rule but reaches nobody.
VALID_EMAIL = "ua-test@mdt-portfolio.internal"


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CONTACT_EMAIL",
        "PROJECT_URL",
        "SOURCES_FILE",
        "RUN_STALE_AFTER_S",
        "COLLECTOR_REPLAY_DIR",
        "COLLECTOR_RUN_INLINE",
        "DATA_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------


def test_collector_setting_defaults() -> None:
    current = settings()
    assert current.project_url == ""
    assert current.sources_path == REPO_ROOT / "sources.yaml"
    assert current.run_stale_after_s == 300
    assert current.replay_path is None
    assert current.collector_run_inline is False
    assert current.raw_path == REPO_ROOT / "data" / "raw"


def test_empty_replay_dir_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLECTOR_REPLAY_DIR", "")
    assert settings().replay_path is None
    monkeypatch.setenv("COLLECTOR_REPLAY_DIR", "backend/tests/fixtures/ministry_projects")
    assert settings().replay_path == REPO_ROOT / "backend/tests/fixtures/ministry_projects"


def test_inline_runs_and_stale_limit_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLECTOR_RUN_INLINE", "true")
    monkeypatch.setenv("RUN_STALE_AFTER_S", "60")
    current = settings()
    assert current.collector_run_inline is True
    assert current.run_stale_after_s == 60
    monkeypatch.setenv("RUN_STALE_AFTER_S", "0")
    with pytest.raises(ValidationError):
        settings()


@pytest.mark.parametrize("value", ["https://example.org/project", "http://example.org", ""])
def test_project_url_accepts_http_urls(value: str) -> None:
    assert settings(project_url=value).project_url == value


@pytest.mark.parametrize(
    "value", ["ftp://example.org", "example.org", "https://example.org/a b", "https://x.org/(a)"]
)
def test_project_url_refuses_values_that_break_the_user_agent(value: str) -> None:
    with pytest.raises(ValidationError):
        settings(project_url=value)


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        (None, "is not set in .env"),
        ("", "is not set in .env"),
        ("   ", "is not set in .env"),
        ("not-an-address", "plain e-mail address"),
        ("two@at@example.dev", "plain e-mail address"),
        ("a b@mdt-portfolio.internal", "plain e-mail address"),
        ("research-contact@example.org", "reserved example domain"),
        ("someone@EXAMPLE.COM", "reserved example domain"),
        ("someone@mail.example.net", "reserved example domain"),
        ("someone@project.example", "reserved example domain"),
        ("someone@project.invalid", "reserved example domain"),
        ("someone@project.test", "reserved example domain"),
        ("someone@localhost", "plain e-mail address"),
        ("someone@app.localhost", "reserved example domain"),
    ],
)
def test_contact_email_rules(value: str | None, fragment: str) -> None:
    problem = contact_email_problem(value)
    assert problem is not None and fragment in problem
    assert problem.startswith("CONTACT_EMAIL is not set")
    if value and value.strip():
        assert value.strip() not in problem  # the address is never repeated


def test_a_plain_address_in_another_domain_is_accepted() -> None:
    assert contact_email_problem(VALID_EMAIL) is None
    assert contact_email_problem(f"  {VALID_EMAIL}  ") is None


def test_the_env_example_placeholder_is_refused() -> None:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    match = re.search(r"^CONTACT_EMAIL=(.*)$", text, flags=re.MULTILINE)
    assert match is not None
    assert contact_email_problem(match.group(1)) is not None


# --------------------------------------------------------------------------------------
# The repository's sources.yaml
# --------------------------------------------------------------------------------------


def test_repository_sources_file_has_every_collector_of_the_contract() -> None:
    sources = load_sources(REPO_ROOT / "sources.yaml")
    assert set(sources.collectors) == {
        "ministry_projects",
        "project_sites",
        "diia_catalog",
        "ministry_news",
        "kmu_news",
        "wayback",
        "tagger",
    }
    for config in sources.collectors.values():
        assert config.enabled
        assert "codeua.com" in config.exclude_hosts
        assert config.settings.min_interval_s == 1.0
        assert config.settings.max_bytes == 26_214_400
        assert config.settings.max_wait_s == 600
        assert config.settings.discontinued_after_runs == 2
    wayback = sources.collectors["wayback"]
    assert wayback.min_interval("web.archive.org") == 5.0
    assert wayback.min_interval("thedigital.gov.ua") == 1.0
    assert wayback.needs_server_check
    assert wayback.fixtures[0].name == "robots_web_archive"
    assert sources.collectors["tagger"].builtin
    assert not sources.collectors["ministry_projects"].builtin
    assert sources.collectors["diia_catalog"].options["project_seed_key"] == "diia"


def test_repository_licence_codes_are_license_terms() -> None:
    terms = yaml.safe_load((REPO_ROOT / "codebook" / "license.yaml").read_text(encoding="utf-8"))
    codes = {term["code"] for term in terms["terms"]}
    for config in load_sources(REPO_ROOT / "sources.yaml").collectors.values():
        assert config.licence.code in codes, config.name


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def minimal(**collector: Any) -> dict[str, Any]:
    entry = {"label": "Example collector", **collector}
    return {"version": 1, "defaults": {}, "collectors": {"example": entry}}


def parse(data: Any) -> Any:
    return parse_sources(data, Path("sources.yaml"))


def test_minimal_file_gets_the_documented_defaults() -> None:
    config = parse(minimal()).collectors["example"]
    assert config.enabled and not config.builtin and not config.needs_server_check
    assert config.licence.code == "unknown"
    assert config.settings.retries == 2 and config.settings.max_redirects == 5
    assert config.settings.timeout_connect_s == 10 and config.settings.timeout_read_s == 30
    assert config.fixtures == () and dict(config.options) == {}


def test_collector_overrides_defaults_and_merges_excluded_hosts() -> None:
    data = minimal(min_interval_s=2.5, retries=0, exclude_hosts=["Other.Example.ORG."])
    data["defaults"] = {"min_interval_s": 1.5, "exclude_hosts": ["blocked.example.org"]}
    config = parse(data).collectors["example"]
    assert config.settings.min_interval_s == 2.5
    assert config.settings.retries == 0
    assert config.exclude_hosts == {"blocked.example.org", "other.example.org"}


def test_entry_hash_follows_the_entry_and_the_defaults() -> None:
    first = parse(minimal()).collectors["example"].entry_hash
    assert parse(minimal()).collectors["example"].entry_hash == first
    assert parse(minimal(retries=1)).collectors["example"].entry_hash != first
    changed = minimal()
    changed["defaults"] = {"retries": 1}
    assert parse(changed).collectors["example"].entry_hash != first


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ([], "expected a mapping"),
        ({"version": 2, "collectors": {"x": {"label": "X"}}}, "version must be 1"),
        ({**minimal(), "extra": 1}, "unknown keys"),
        ({**minimal(), "defaults": {"speed": 1}}, "defaults: unknown keys"),
        ({**minimal(), "defaults": {"min_interval_s": -1}}, "must be at least 0"),
        ({**minimal(), "defaults": {"timeout_read_s": 0}}, "greater than 0"),
        ({**minimal(), "defaults": {"retries": 1.5}}, "an integer is required"),
        ({**minimal(), "defaults": {"retries": True}}, "a number is required"),
        ({**minimal(), "defaults": {"max_bytes": "big"}}, "a number is required"),
        ({**minimal(), "defaults": {"discontinued_after_runs": 0}}, "at least 1"),
        ({"version": 1, "collectors": {}}, "must not be empty"),
        ({"version": 1, "collectors": {"Bad-Name": {"label": "X"}}}, "invalid collector name"),
        ({"version": 1, "collectors": {"client": {"label": "X"}}}, "invalid collector name"),
        (minimal(label=""), "label: a non-empty string is required"),
        (minimal(color="red"), "unknown keys"),
        (minimal(enabled="yes"), "must be true or false"),
        (minimal(hosts={"web.example.org": {"retries": 1}}), "only min_interval_s"),
        (minimal(hosts={"bad host": {"min_interval_s": 1}}), "invalid host name"),
        (minimal(exclude_hosts="example.org"), "expected a list of host names"),
        (minimal(licence={"code": "CC BY"}), "license vocabulary code"),
        (minimal(licence={"code": "unknown", "url": "x"}), "only code and statement"),
        (minimal(fixtures=[{"name": "a", "url": "https://example.org/"}]), "are required"),
        (
            minimal(fixtures=[{"name": "a", "url": "ftp://example.org/", "purpose": "p"}]),
            "fixtures[0].url",
        ),
        (
            minimal(
                fixtures=[
                    {"name": "a", "url": "https://example.org/", "purpose": "p"},
                    {"name": "a", "url": "https://example.org/b", "purpose": "p"},
                ]
            ),
            "must be unique",
        ),
        (minimal(options=["a"]), "options: expected a mapping"),
    ],
)
def test_invalid_files_name_the_offending_key(data: Any, fragment: str) -> None:
    with pytest.raises(SourcesError) as raised:
        parse(data)
    assert fragment in str(raised.value)


def test_missing_and_unreadable_files(tmp_path: Path) -> None:
    with pytest.raises(SourcesError, match="is missing"):
        load_sources(tmp_path / "sources.yaml")
    broken = tmp_path / "broken.yaml"
    broken.write_text("version: [1\n", encoding="utf-8")
    with pytest.raises(SourcesError, match="cannot be read as YAML"):
        load_sources(broken)


def test_load_is_cached_until_the_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump(minimal()), encoding="utf-8")
    first = load_sources(path)
    assert load_sources(path) is first
    path.write_text(yaml.safe_dump(minimal(label="Another example")), encoding="utf-8")
    assert load_sources(path).collectors["example"].label == "Another example"


def test_fixture_urls_are_normalised() -> None:
    data = minimal(
        fixtures=[{"name": "root", "url": "HTTPS://Example.ORG.:443", "purpose": "a root"}]
    )
    assert parse(data).collectors["example"].fixtures[0].url == "https://example.org/"
