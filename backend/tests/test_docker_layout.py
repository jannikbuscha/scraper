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
