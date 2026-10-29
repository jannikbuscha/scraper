"""A synthetic codebook and seed for tests.

Only the codes that program logic depends on (the fixed system vocabularies and the fixed
event types) are real codes; every other code, label and value is obviously synthetic.
The cut-off dates are synthetic too, so no test depends on the real codebook.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

MINISTRY = date(2011, 7, 15)
INVASION = date(2016, 3, 10)
FOCAL_ORG_SEED_KEY = "example-focal-org"

# (code, attributes, active)
_Term = tuple[str, dict[str, Any], bool]


def _terms(*codes: str) -> list[_Term]:
    return [(code, {}, True) for code in codes]


#: name → (multi, fixed_codes, terms)
VOCABULARIES: dict[str, tuple[bool, bool, list[_Term]]] = {
    "verification_status": (False, True, _terms("unverified", "verified", "disputed")),
    "screening_status": (False, True, _terms("unscreened", "included", "excluded")),
    "date_basis": (False, True, _terms("stated_in_source", "inferred", "archive_upper_bound")),
    "date_precision": (False, True, _terms("day", "month", "quarter", "year")),
    "period": (
        False,
        True,
        _terms("pre_ministry", "pre_invasion", "full_scale_war", "unknown"),
    ),
    "war_trajectory": (
        False,
        True,
        _terms("new_in_war", "adapted_in_war", "prewar_unchanged", "unknown"),
    ),
    "derived_reason": (
        False,
        True,
        _terms(
            "no_date",
            "imprecise_date",
            "archive_bound_only",
            "imprecise_modification_date",
            "conflicting_dates",
        ),
    ),
    "event_type": (
        False,
        False,
        [
            ("announced", {"counts_as_modification": False}, True),
            ("beta_launch", {"counts_as_modification": False, "fixed": True}, True),
            ("launch", {"counts_as_modification": False, "fixed": True}, True),
            ("expansion", {"counts_as_modification": True}, True),
            ("rebrand", {"counts_as_modification": True}, True),
            ("first_archived", {"counts_as_modification": False, "fixed": True}, True),
        ],
    ),
    "status": (False, False, [("active", {}, True), ("planned", {}, True), ("retired", {}, False)]),
    "paper_cluster": (False, False, _terms("cluster_a", "cluster_b")),
    "unit_type": (False, False, _terms("unit_a", "unit_b")),
    "ministry_category": (True, False, _terms("category_a", "category_b")),
    "policy_domain": (
        True,
        False,
        [
            ("domain_a", {}, True),
            ("domain_b", {}, True),
            ("domain_c", {}, True),
            ("domain_old", {}, False),
        ],
    ),
    "beneficiary": (True, False, _terms("group_a", "group_b")),
    "wartime_relevance": (False, False, _terms("relevance_a", "relevance_b")),
    "development_mode": (False, False, _terms("mode_a", "mode_b")),
    "service_kind": (False, False, _terms("kind_a", "kind_b")),
    "channel": (True, False, _terms("channel_a", "channel_b", "channel_c")),
    "participation_role": (False, False, _terms("initiator", "owner", "operator", "partner")),
    "relation_type": (False, False, _terms("relates_a", "relates_b")),
    "component_type": (False, False, _terms("component_a")),
    "doc_type": (False, False, _terms("doc_a", "doc_b")),
    "language": (False, False, _terms("lang_a", "lang_b")),
    "license": (False, False, _terms("license_a")),
    "exclusion_reason": (False, False, _terms("reason_a", "reason_b")),
    "org_type": (False, False, _terms("org_a", "org_b")),
}


def write_codebook(directory: Path) -> Path:
    """Write the synthetic vocabularies and parameters to ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, (multi, fixed, terms) in VOCABULARIES.items():
        data = {
            "vocabulary": name,
            "label": f"Example vocabulary {name}",
            "description": "Synthetic vocabulary for tests.",
            "multi": multi,
            "fixed_codes": fixed,
            "terms": [
                {
                    "code": code,
                    "label_en": f"Example {code}",
                    "label_uk": None,
                    "definition": f"Synthetic definition of {code}.",
                    "include_note": None,
                    "exclude_note": None,
                    "examples": None,
                    "sort_order": 10 * (index + 1),
                    "active": active,
                    "attributes": attributes,
                }
                for index, (code, attributes, active) in enumerate(terms)
            ],
        }
        (directory / f"{name}.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    write_parameters(directory, MINISTRY, INVASION)
    (directory / "README.md").write_text("# Not a vocabulary\n", encoding="utf-8")
    return directory


def write_parameters(directory: Path, ministry: date, invasion: date) -> None:
    """Write ``parameters.yaml`` (dates as YAML dates, plus keys the loader ignores)."""
    text = (
        f"ministry_founded: {ministry.isoformat()}\n"
        f"full_scale_invasion: {invasion.isoformat()}\n"
        "publication_timezone: Europe/Kyiv\n"
        "storage_timezone: UTC\n"
        "sources:\n"
        "  ministry_founded: synthetic\n"
    )
    (directory / "parameters.yaml").write_text(text, encoding="utf-8")


def write_seed(directory: Path, projects: list[dict[str, Any]] | None = None) -> Path:
    """Write a synthetic ``projects.yaml`` (focal organisation plus ``projects``)."""
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "provenance": "Synthetic test seed",
        "projects": projects or [],
        "organizations": [
            {
                "slug": FOCAL_ORG_SEED_KEY,
                "name_en": "Example focal organisation",
                "name_uk": None,
                "aliases": [
                    {
                        "text": "Example focal organisation",
                        "lang": "en",
                        "case_sensitive": True,
                        "kind": "name",
                        "exclude_patterns": [],
                    }
                ],
            }
        ],
    }
    (directory / "projects.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return directory
