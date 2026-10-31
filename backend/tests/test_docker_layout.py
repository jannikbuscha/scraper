"""The repository layout that the Docker setup relies on (Definition of Done 1).

``docker compose up -d`` must work on a fresh clone without leaving directories that belong to
root. The Docker daemon runs as root and creates a missing bind-mount source directory as root,
which neither the host user (a later ``git pull`` into it fails) nor the container user ``app``
can write to. In CI these tests run on a fresh checkout, so a file found here is a committed one.
"""

from __future__ import annotations

from typing import Any

import yaml

from mdt.config import REPO_ROOT

COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


def compose_services() -> dict[str, dict[str, Any]]:
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    services = compose["services"]
    assert isinstance(services, dict)
    assert services
    return services


def bind_mounts(service: dict[str, Any]) -> dict[str, str]:
    """Container path -> host path (as written) of the service's bind mounts.

    In the short syntax ``SOURCE:TARGET[:MODE]`` an entry is a bind mount when SOURCE is a path
    (it starts with ``.``, ``/`` or ``~``); otherwise SOURCE names a volume, and an entry without
    a colon is an anonymous volume. The long syntax says ``type: bind``.
    """
    mounts: dict[str, str] = {}
    for volume in service.get("volumes", []):
        if isinstance(volume, str):
            source, _, rest = volume.partition(":")
            if not rest or not source.startswith((".", "/", "~")):
                continue
            target = rest.split(":")[0]
        elif volume.get("type") == "bind":
            source, target = volume["source"], volume["target"]
        else:
            continue
        mounts[target] = source
    return mounts


def test_bind_mounts_parse_short_and_long_syntax() -> None:
    service = {
        "volumes": [
            "./data:/app/data",
            "./releases:/app/releases:ro",
            "cache:/app/cache",
            "/app/anonymous",
            {"type": "bind", "source": "./import", "target": "/app/import"},
            {"type": "volume", "source": "logs", "target": "/app/logs"},
        ]
    }
    assert bind_mounts(service) == {
        "/app/data": "./data",
        "/app/releases": "./releases",
        "/app/import": "./import",
    }


def test_bind_mount_sources_in_the_repository_exist_in_every_clone() -> None:
    """Only the data directory may be missing in a fresh clone.

    It is gitignored runtime data, and the entrypoint hands DATA_DIR to the user ``app`` on every
    start, whoever created it. Every other bind-mount source inside the repository must be part
    of the repository, so that git creates it (owned by the user who cloned), not the Docker
    daemon: a directory with a committed README.md that says what it holds.
    """
    checked: set[str] = set()
    for name, service in compose_services().items():
        environment = service.get("environment") or {}
        assert isinstance(environment, dict), f"{name}: environment must be a mapping"
        data_dir = environment.get("DATA_DIR")
        for target, source in bind_mounts(service).items():
            host_path = (REPO_ROOT / source).resolve()
            if not host_path.is_relative_to(REPO_ROOT) or target == data_dir:
                continue
            assert (host_path / "README.md").is_file(), (
                f"{name}: the bind-mount source {source} ({target}) must be part of the "
                f"repository, e.g. through a committed {source}/README.md. Otherwise a plain "
                "`docker compose up -d` on a fresh clone lets the Docker daemon create it as root."
            )
            checked.add(source)
    # Guards against a vacuous pass: the documented release directory was found and checked.
    assert "./releases" in checked


def test_collector_settings_are_pinned_in_the_container() -> None:
    """docs/COLLECTORS.md §3: the image carries sources.yaml, compose pins SOURCES_FILE to it,
    and COLLECTOR_REPLAY_DIR is pinned empty, so the server's database never runs in replay
    mode whatever .env says."""
    environment = compose_services()["app"]["environment"]
    assert environment["SOURCES_FILE"] == "/app/sources.yaml"
    assert environment["COLLECTOR_REPLAY_DIR"] == ""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY sources.yaml ./sources.yaml" in dockerfile
    allowlist = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "!sources.yaml" in allowlist


def test_the_image_carries_the_collector_inputs_and_the_settings_are_documented() -> None:
    """The image copies the codebook (with the two collector files of docs/COLLECTORS.md
    §7.7 and §7.9) and sets SOURCES_FILE; .env.example documents every collector setting
    except the test-only COLLECTOR_RUN_INLINE (docs/COLLECTORS.md §3)."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY codebook/ ./codebook/" in dockerfile
    assert "SOURCES_FILE=/app/sources.yaml" in dockerfile
    allowlist = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "!codebook/" in allowlist
    for name in ("event_patterns.yaml", "collector_mappings.yaml"):
        assert (REPO_ROOT / "codebook" / name).is_file(), name
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for setting in (
        "CONTACT_EMAIL",
        "PROJECT_URL",
        "SOURCES_FILE",
        "RUN_STALE_AFTER_S",
        "COLLECTOR_REPLAY_DIR",
    ):
        assert f"{setting}=" in example, setting
    assert "COLLECTOR_RUN_INLINE" not in example
