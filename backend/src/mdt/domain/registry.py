"""Entity registry: every entity type and field of docs/DATA_MODEL.md §2-§3.

Validation, revisions, the API (filters, sorting, exports) and the frontend (through
``GET /api/meta``, built from :func:`meta_entity_types`) are all driven by this module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import cached_property
from typing import Any, Literal

FieldType = Literal[
    "string",
    "text",
    "slug",
    "bool",
    "int",
    "number",
    "url",
    "url_list",
    "string_list",
    "vocab",
    "vocab_list",
    "ref",
    "date",
    "partial_date",
    "datetime",
    "alias_list",
    "json",
    "doc_links",
]
FilterKind = Literal["text", "multiselect", "date_range", "bool", "number_range", "ref"]
Group = Literal["basics", "classification", "wartime", "framework", "sources", "system"]
LabelRule = Literal[
    "names",
    "event",
    "title",
    "participation",
    "relation",
    "indicator",
    "evidence",
    "vocabulary_term",
    "name",
    "comment",
]

GROUPS: tuple[dict[str, str], ...] = (
    {"key": "basics", "label": "Basics"},
    {"key": "classification", "label": "Classification"},
    {"key": "wartime", "label": "Wartime"},
    {"key": "framework", "label": "Framework D1–D4"},
    {"key": "sources", "label": "Sources & Evidence"},
    {"key": "system", "label": "System"},
)

#: Field types whose API value is a list (empty list = empty).
LIST_TYPES: frozenset[str] = frozenset(
    {"url_list", "string_list", "vocab_list", "alias_list", "doc_links"}
)
#: Field types whose values are strings in the FTS body (DATA_MODEL §10).
FTS_TYPES: frozenset[str] = frozenset({"string", "text", "slug", "string_list", "url_list"})
#: Field types that are bulk-editable when editable and not create-only (API §3.1).
BULK_TYPES: frozenset[str] = frozenset({"vocab", "vocab_list", "bool"})

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
CODE_PATTERN = r"^[a-z0-9_]+$"
COUNTRY_PATTERN = r"^[A-Z]{2}$"

DEFAULT_MAX_LENGTH: Mapping[str, int] = {"string": 500, "text": 20_000, "slug": 100}

_DEFAULT_FILTER: Mapping[str, FilterKind | None] = {
    "string": "text",
    "text": "text",
    "slug": "text",
    "url": "text",
    "url_list": "text",
    "string_list": "text",
    "alias_list": "text",
    "vocab": "multiselect",
    "vocab_list": "multiselect",
    "bool": "bool",
    "int": "number_range",
    "number": "number_range",
    "ref": "ref",
    "date": "date_range",
    "partial_date": "date_range",
    "datetime": "date_range",
    "json": None,
    "doc_links": "ref",
}
_SORTABLE_TYPES = frozenset(
    {
        "string",
        "slug",
        "vocab",
        "vocab_list",
        "bool",
        "int",
        "number",
        "ref",
        "date",
        "partial_date",
        "datetime",
    }
)


@dataclass(frozen=True)
class FieldSpec:
    """A registry field. The attributes up to ``help`` are exposed in ``/api/meta``."""

    name: str
    label: str
    type: FieldType
    group: Group
    vocabulary: str | None = None
    ref_types: tuple[str, ...] | None = None
    required: bool = False
    editable: bool = False
    create_only: bool = False
    system: bool = False
    tracked: bool = False
    derived: bool = False
    virtual: bool = False
    filter: FilterKind | None = None
    sortable: bool = False
    in_list: bool = False
    in_create: bool = False
    default: Any = None
    help: str | None = None
    # Implementation details (not exposed in meta).
    max_length: int | None = None
    pattern: str | None = None
    #: Value computed from another field in the same revision (e.g. canonical_url).
    computed_from: str | None = None
    #: Never exposed through the API (seed_key).
    internal: bool = False
    #: One of the common system columns (created_at … version).
    system_column: bool = False
    #: Uniqueness: "all" (including deleted rows) or "live" (non-deleted rows only).
    unique: Literal["all", "live"] | None = None
    #: Only in detail responses (document text).
    detail_only: bool = False
    #: Upper-case the value during normalisation (country codes).
    upper: bool = False

    @property
    def is_list(self) -> bool:
        """True for list types (empty value ``[]``)."""
        return self.type in LIST_TYPES

    @property
    def stored(self) -> bool:
        """True if the value is stored on the entity (row columns or document links)."""
        return not (self.derived or self.virtual)

    @property
    def bulk_editable(self) -> bool:
        """Editable, not create-only, of type vocab, vocab_list or bool (API §3.1)."""
        return self.editable and not self.create_only and self.type in BULK_TYPES

    @property
    def restorable(self) -> bool:
        """Applied by restore: tracked, editable and not create-only (DATA_MODEL §6.4)."""
        return self.tracked and self.editable and not self.create_only

    @property
    def columns(self) -> tuple[str, ...]:
        """Storage columns of a stored field (none for document links)."""
        if not self.stored or self.type == "doc_links":
            return ()
        if self.type == "partial_date":
            return (f"{self.name}_start", f"{self.name}_end", f"{self.name}_precision")
        return (self.name,)

    def empty_value(self) -> Any:
        """The empty API value of this field (``[]`` for lists, else None)."""
        return [] if self.is_list else None

    def meta(self) -> dict[str, Any]:
        """The field description of ``GET /api/meta``."""
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "vocabulary": self.vocabulary,
            "ref_types": list(self.ref_types) if self.ref_types else None,
            "group": self.group,
            "required": self.required,
            "editable": self.editable,
            "create_only": self.create_only,
            "system": self.system,
            "tracked": self.tracked,
            "derived": self.derived,
            "virtual": self.virtual,
            "filter": self.filter,
            "sortable": self.sortable,
            "in_list": self.in_list,
            "in_create": self.in_create,
            "default": self.default,
            "bulk_editable": self.bulk_editable,
            "help": self.help,
        }


@dataclass(frozen=True)
class EntityTypeSpec:
    """An entity type: table, ID prefix, fields and presentation defaults."""

    name: str
    label: str
    label_plural: str
    prefix: str
    fields: tuple[FieldSpec, ...]
    label_rule: LabelRule
    default_sort: str
    table_view: bool = False
    constraints: tuple[Mapping[str, Any], ...] = ()
    #: Has the common curated columns (§2.3); False for comments.
    curated: bool = True
    #: Served by the generic /api/entities endpoints; False for comments.
    generic_api: bool = True
    #: Has a row in ``derived`` (project, service).
    has_derived: bool = False
    #: Soft-deletable; vocabulary terms are deactivated instead.
    deletable: bool = True

    @property
    def table(self) -> str:
        """Database table name."""
        return self.name

    @cached_property
    def field_map(self) -> dict[str, FieldSpec]:
        """Fields by name."""
        return {spec.name: spec for spec in self.fields}

    def field(self, name: str) -> FieldSpec:
        """Return the field ``name``; raises KeyError if unknown."""
        return self.field_map[name]

    def has_field(self, name: str) -> bool:
        """True if ``name`` is a registry field of this type."""
        return name in self.field_map

    @cached_property
    def tracked_fields(self) -> tuple[FieldSpec, ...]:
        """Fields in snapshots, diffs and field_meta (DATA_MODEL §2.2)."""
        return tuple(spec for spec in self.fields if spec.tracked)

    @cached_property
    def stored_fields(self) -> tuple[FieldSpec, ...]:
        """Fields with storage (excluding the common system columns)."""
        return tuple(spec for spec in self.fields if spec.stored and not spec.system_column)

    @cached_property
    def api_fields(self) -> tuple[FieldSpec, ...]:
        """Fields of the item's ``fields`` object (API §2): neither derived, virtual,
        a system column nor internal."""
        return tuple(
            spec
            for spec in self.fields
            if spec.stored and not spec.system_column and not spec.internal
        )

    def meta(self, parameters: PeriodParameters | None = None) -> dict[str, Any]:
        """The entity type description of ``GET /api/meta``."""
        return {
            "label": self.label,
            "label_plural": self.label_plural,
            "prefix": self.prefix,
            "table_view": self.table_view,
            "default_sort": self.default_sort,
            "constraints": [dict(constraint) for constraint in self.constraints],
            "fields": [spec.meta() for spec in self.fields if not spec.internal],
            "quick_filters": quick_filters(self.name, parameters),
        }


@dataclass(frozen=True)
class PeriodParameters:
    """The cut-off dates used for period presets and derived values."""

    ministry_founded: date
    full_scale_invasion: date


# --------------------------------------------------------------------------------------
# Field constructors
# --------------------------------------------------------------------------------------


def _field(
    name: str, type_: FieldType, label: str, group: Group = "basics", **kw: Any
) -> FieldSpec:
    """A stored, tracked, editable field with type-based defaults."""
    kw.setdefault("filter", _DEFAULT_FILTER[type_])
    kw.setdefault("sortable", type_ in _SORTABLE_TYPES)
    kw.setdefault("editable", True)
    kw.setdefault("tracked", True)
    if type_ in DEFAULT_MAX_LENGTH:
        kw.setdefault("max_length", DEFAULT_MAX_LENGTH[type_])
    if type_ == "slug":
        kw.setdefault("pattern", SLUG_PATTERN)
    return FieldSpec(name=name, label=label, type=type_, group=group, **kw)


def _system(
    name: str, type_: FieldType, label: str, group: Group = "sources", **kw: Any
) -> FieldSpec:
    """A stored, tracked field set only by the domain layer or machine channels."""
    kw.setdefault("filter", None)
    kw.setdefault("sortable", False)
    return _field(name, type_, label, group, system=True, editable=False, **kw)


def _derived(name: str, type_: FieldType, label: str, **kw: Any) -> FieldSpec:
    kw.setdefault("filter", _DEFAULT_FILTER[type_])
    kw.setdefault("sortable", True)
    return FieldSpec(name=name, label=label, type=type_, group="wartime", derived=True, **kw)


def _virtual(
    name: str, type_: FieldType, label: str, group: Group = "basics", **kw: Any
) -> FieldSpec:
    kw.setdefault("filter", _DEFAULT_FILTER[type_])
    kw.setdefault("sortable", True)
    return FieldSpec(name=name, label=label, type=type_, group=group, virtual=True, **kw)


def _system_column(name: str, type_: FieldType, label: str, **kw: Any) -> FieldSpec:
    return FieldSpec(
        name=name,
        label=label,
        type=type_,
        group="system",
        system=True,
        system_column=True,
        filter=_DEFAULT_FILTER[type_] if name != "version" else None,
        sortable=True,
        **kw,
    )


def _in_create(fields: Iterable[FieldSpec], names: Iterable[str]) -> tuple[FieldSpec, ...]:
    """Mark the named fields, plus required fields without a default and create-only
    fields, as offered in the create form."""
    wanted = set(names)
    result = []
    for spec in fields:
        offered = spec.name in wanted or (
            spec.stored
            and spec.editable
            and not spec.system_column
            and ((spec.required and spec.default is None) or spec.create_only)
        )
        result.append(replace(spec, in_create=offered))
    unknown = wanted - {spec.name for spec in result}
    if unknown:
        raise ValueError(f"unknown in_create fields: {sorted(unknown)}")
    return tuple(result)


# --------------------------------------------------------------------------------------
# Reusable field groups
# --------------------------------------------------------------------------------------

TABLE_TYPES = ("project", "service", "event", "document", "organization")
CURATED_TYPES = (
    "project",
    "service",
    "event",
    "document",
    "organization",
    "participation",
    "component",
    "relation",
    "indicator",
    "evidence",
    "vocabulary_term",
    "saved_view",
)
PORTFOLIO_TYPES = ("project", "service", "component")

_NAME_HELP_EN = (
    "Official English name as given by the sources. Left empty if there is none; "
    "there is no machine translation."
)
_NAME_HELP_UK = "Official Ukrainian name as given by the sources."
_ALIASES_HELP = (
    "Names and spellings used to match texts to this record (kind name, inflection, "
    "abbreviation or domain), with optional literal exclude phrases."
)


def _names(in_list: bool = True) -> tuple[FieldSpec, ...]:
    return (
        _field("name_en", "string", "Name (English)", in_list=in_list, help=_NAME_HELP_EN),
        _field("name_uk", "string", "Name (Ukrainian)", in_list=in_list, help=_NAME_HELP_UK),
    )


def _aliases() -> FieldSpec:
    return _field("aliases", "alias_list", "Aliases", help=_ALIASES_HELP)


def _descriptions() -> tuple[FieldSpec, ...]:
    return (
        _field(
            "description_en",
            "text",
            "Description (English)",
            help="Short description based on the sources.",
        ),
        _field(
            "description_uk",
            "text",
            "Description (Ukrainian)",
            help="Short description based on the sources.",
        ),
    )


def _classification(beneficiaries_in_list: bool, policy_in_list: bool) -> tuple[FieldSpec, ...]:
    return (
        _field(
            "policy_domains",
            "vocab_list",
            "Policy domains",
            "classification",
            vocabulary="policy_domain",
            in_list=policy_in_list,
            help="Policy domains supported by the sources, main one first (COFOG, draft).",
        ),
        _field(
            "beneficiaries",
            "vocab_list",
            "Beneficiaries",
            "classification",
            vocabulary="beneficiary",
            in_list=beneficiaries_in_list,
            help="Intended beneficiaries supported by the sources, main one first.",
        ),
        _field(
            "development_mode",
            "vocab",
            "Development mode",
            "classification",
            vocabulary="development_mode",
            help=(
                "New development or adaptation of an existing service (Yoo et al. 2012), "
                "coded from the sources (CODEBOOK §2.5)."
            ),
        ),
        _field(
            "development_rationale",
            "text",
            "Development rationale",
            "classification",
            help="The coder's reasoning for the development mode.",
        ),
    )


def _wartime() -> tuple[FieldSpec, ...]:
    return (
        _field(
            "wartime_relevance",
            "vocab",
            "Wartime relevance",
            "wartime",
            vocabulary="wartime_relevance",
            in_list=True,
            help=(
                "Relation of the stated purpose to needs caused or intensified by the "
                "full-scale war (CODEBOOK §2.4). Stays empty until coded."
            ),
        ),
        _field(
            "wartime_rationale",
            "text",
            "Wartime rationale",
            "wartime",
            help="The coder's reasoning for the wartime relevance.",
        ),
    )


def _framework() -> tuple[FieldSpec, ...]:
    return (
        _field(
            "d1_need",
            "text",
            "D1 need",
            "framework",
            help="D1: the public problem or need that motivated the initiative.",
        ),
        _field(
            "d1_affected_groups",
            "text",
            "D1 affected groups",
            "framework",
            help="D1: the citizens, businesses or institutions affected.",
        ),
        _field(
            "d1_priority_link",
            "text",
            "D1 link to priorities",
            "framework",
            help="D1: the link to governmental priorities.",
        ),
        _field(
            "d2_summary",
            "text",
            "D2 digital platforms",
            "framework",
            help="D2: use or extension of existing platforms or infrastructures.",
        ),
        _field(
            "d3_summary",
            "text",
            "D3 distributed innovation",
            "framework",
            help="D3: organisations involved and their roles.",
        ),
        _field(
            "d4_summary",
            "text",
            "D4 combinatorial innovation",
            "framework",
            help="D4: recombination of existing technologies, data or services.",
        ),
    )


def _derived_fields(launch_in_list: bool, period_in_list: bool) -> tuple[FieldSpec, ...]:
    return (
        _derived(
            "launch",
            "partial_date",
            "Launch",
            in_list=launch_in_list,
            help=(
                "Derived: the earliest launch event, otherwise the earliest beta launch; "
                "shown with its precision and basis (CODEBOOK §2.7)."
            ),
        ),
        _derived(
            "existed_by",
            "date",
            "Existed by",
            help="Derived: earliest archive capture, an upper bound (≤ date), never a start date.",
        ),
        _derived(
            "period",
            "vocab",
            "Period",
            vocabulary="period",
            in_list=period_in_list,
            help="Derived from the launch interval and the cut-off dates (CODEBOOK §2.7).",
        ),
        _derived(
            "war_trajectory",
            "vocab",
            "War trajectory",
            vocabulary="war_trajectory",
            help="Derived from the launch and modification events (CODEBOOK §2.7).",
        ),
        _derived(
            "portfolio_entry",
            "partial_date",
            "Portfolio entry",
            help=(
                "Derived: earliest start of a participation of the ministry as initiator, "
                "owner or operator."
            ),
        ),
    )


def _common(table_type: bool) -> tuple[FieldSpec, ...]:
    """The common curated fields (§2.3) and virtual comment counts (§2.4)."""
    return (
        _field(
            "verification_status",
            "vocab",
            "Verification status",
            vocabulary="verification_status",
            required=True,
            default="unverified",
            in_list=True,
            help=(
                "The reviewer's judgement of the whole record. Setting verified or "
                "disputed requires a note."
            ),
        ),
        _field("notes", "text", "Notes", "sources", help="Internal notes."),
        _virtual(
            "open_comments",
            "int",
            "Open comments",
            in_list=table_type,
            help="Number of open comment threads on this record, field threads included.",
        ),
        _virtual(
            "comment_count",
            "int",
            "Comments",
            help="Number of comments on this record, replies included.",
        ),
    )


def _system_columns() -> tuple[FieldSpec, ...]:
    return (
        _system_column("created_at", "datetime", "Created at"),
        _system_column("created_by", "string", "Created by"),
        _system_column("updated_at", "datetime", "Updated at"),
        _system_column("updated_by", "string", "Updated by"),
        _system_column("deleted_at", "datetime", "Deleted at"),
        _system_column("deleted_by", "string", "Deleted by"),
        _system_column("version", "int", "Version"),
    )


def _curated(*fields: FieldSpec, table_type: bool = False) -> tuple[FieldSpec, ...]:
    return (*fields, *_common(table_type), *_system_columns())


_NAMES_CONSTRAINT: tuple[Mapping[str, Any], ...] = ({"one_of_required": ["name_en", "name_uk"]},)

# --------------------------------------------------------------------------------------
# Entity types
# --------------------------------------------------------------------------------------

PROJECT = EntityTypeSpec(
    name="project",
    label="Project",
    label_plural="Projects",
    prefix="prj",
    label_rule="names",
    default_sort="paper_cluster,name_en",
    table_view=True,
    has_derived=True,
    constraints=_NAMES_CONSTRAINT,
    fields=_in_create(
        _curated(
            _field(
                "slug",
                "slug",
                "Slug",
                required=True,
                in_list=True,
                unique="all",
                help="Stable, URL-friendly identifier: lower-case letters, digits and hyphens.",
            ),
            _system(
                "seed_key",
                "slug",
                "Seed key",
                "system",
                tracked=False,
                internal=True,
                unique="all",
            ),
            *_names(),
            _aliases(),
            *_descriptions(),
            _field(
                "official_urls",
                "url_list",
                "Official URLs",
                help="Entry URLs outside the ministry website; the first is the main one.",
            ),
            _field(
                "ministry_urls",
                "url_list",
                "Ministry URLs",
                help="Entry URLs on the ministry website; the first is the main one.",
            ),
            _field(
                "in_paper_scope",
                "bool",
                "In paper scope",
                required=True,
                default=False,
                in_list=True,
                help=(
                    "Whether the project enters the paper's analysis. Setting or changing "
                    "it requires a reason in the scope note (CODEBOOK §2.1)."
                ),
            ),
            _field(
                "scope_note",
                "text",
                "Scope note",
                help="Reason for the scope decision; required whenever the scope changes.",
            ),
            _field(
                "status",
                "vocab",
                "Status",
                vocabulary="status",
                in_list=True,
                help="Operational status according to the most recent source.",
            ),
            _field(
                "paper_cluster",
                "vocab",
                "Paper cluster",
                "classification",
                vocabulary="paper_cluster",
                in_list=True,
                help="Thematic cluster as assigned in the paper.",
            ),
            _field(
                "unit_type",
                "vocab",
                "Unit type",
                "classification",
                vocabulary="unit_type",
                help=(
                    "What the sources describe: a digital product, platform, programme, "
                    "strategy or policy area, or organisation (CODEBOOK §2.1)."
                ),
            ),
            _field(
                "ministry_categories",
                "vocab_list",
                "Ministry categories",
                "classification",
                vocabulary="ministry_category",
                in_list=True,
                help="Categories under which the ministry website lists the project.",
            ),
            _field(
                "primary_objectives",
                "text",
                "Primary objectives",
                "classification",
                help="Primary objectives as stated in the sources.",
            ),
            *_classification(beneficiaries_in_list=False, policy_in_list=True),
            *_wartime(),
            *_framework(),
            *_derived_fields(launch_in_list=True, period_in_list=True),
            table_type=True,
        ),
        [
            "slug",
            "name_en",
            "name_uk",
            "in_paper_scope",
            "scope_note",
            "paper_cluster",
            "status",
            "unit_type",
            "official_urls",
            "ministry_urls",
        ],
    ),
)

SERVICE = EntityTypeSpec(
    name="service",
    label="Service",
    label_plural="Services",
    prefix="svc",
    label_rule="names",
    default_sort="project_id,name_en",
    table_view=True,
    has_derived=True,
    constraints=_NAMES_CONSTRAINT,
    fields=_in_create(
        _curated(
            _field(
                "project_id",
                "ref",
                "Project",
                ref_types=("project",),
                required=True,
                in_list=True,
                help="The project the service belongs to.",
            ),
            _field(
                "parent_service_id",
                "ref",
                "Parent service",
                ref_types=("service",),
                help="Parent service of a sub-service; it must belong to the same project.",
            ),
            *_names(),
            _aliases(),
            *_descriptions(),
            _field(
                "urls",
                "url_list",
                "URLs",
                help="URLs of the service; the first is the canonical one.",
            ),
            _field(
                "status",
                "vocab",
                "Status",
                vocabulary="status",
                in_list=True,
                help="Operational status according to the most recent source.",
            ),
            _field(
                "kind",
                "vocab",
                "Kind",
                "classification",
                vocabulary="service_kind",
                in_list=True,
                help="Kind of service (CODEBOOK §3).",
            ),
            _field(
                "channels",
                "vocab_list",
                "Channels",
                "classification",
                vocabulary="channel",
                in_list=True,
                help="Channels through which the service is offered, main one first.",
            ),
            _system(
                "source_categories",
                "json",
                "Source categories",
                help="Sections under which the sources list the service (filled by collectors).",
            ),
            _field(
                "source_audiences",
                "string_list",
                "Source audiences",
                "sources",
                help="Audiences as labelled by the source.",
            ),
            *_classification(beneficiaries_in_list=True, policy_in_list=False),
            *_wartime(),
            *_framework(),
            *_derived_fields(launch_in_list=True, period_in_list=True),
            _virtual(
                "project_in_paper_scope",
                "bool",
                "Project in paper scope",
                help="Whether the service's project is in the paper's scope.",
            ),
            table_type=True,
        ),
        [
            "project_id",
            "parent_service_id",
            "name_en",
            "name_uk",
            "kind",
            "status",
            "channels",
            "urls",
        ],
    ),
)

EVENT = EntityTypeSpec(
    name="event",
    label="Event",
    label_plural="Events",
    prefix="evt",
    label_rule="event",
    default_sort="-date",
    table_view=True,
    fields=_in_create(
        _curated(
            _field(
                "subject_id",
                "ref",
                "Subject",
                ref_types=("project", "service", "component", "organization"),
                required=True,
                in_list=True,
                help="The project, service, component or organisation the event concerns.",
            ),
            _field(
                "event_type",
                "vocab",
                "Event type",
                vocabulary="event_type",
                required=True,
                in_list=True,
                help="Type of introduction or modification event.",
            ),
            _field(
                "date",
                "partial_date",
                "Date",
                in_list=True,
                help="Date as stated in the source: YYYY, YYYY-Qn, YYYY-MM or YYYY-MM-DD.",
            ),
            _field(
                "date_basis",
                "vocab",
                "Date basis",
                vocabulary="date_basis",
                in_list=True,
                help=(
                    "How the date is known; required with a date. Archive upper bounds are "
                    "allowed only for first_archived events."
                ),
            ),
            _field(
                "date_text",
                "string",
                "Date text",
                "sources",
                sortable=False,
                help="The date exactly as written in the source.",
            ),
            _field("description_en", "text", "Description (English)", in_list=True),
            _field("description_uk", "text", "Description (Ukrainian)"),
            _virtual(
                "subject_in_paper_scope",
                "bool",
                "Subject in paper scope",
                help="Whether the subject is an in-scope project or a service of one.",
            ),
            table_type=True,
        ),
        [
            "subject_id",
            "event_type",
            "date",
            "date_basis",
            "date_text",
            "description_en",
            "description_uk",
        ],
    ),
)

DOCUMENT = EntityTypeSpec(
    name="document",
    label="Document",
    label_plural="Documents",
    prefix="doc",
    label_rule="title",
    default_sort="-published",
    table_view=True,
    fields=_in_create(
        _curated(
            _field(
                "title",
                "string",
                "Title",
                required=True,
                in_list=True,
                max_length=1000,
                help="Original title.",
            ),
            _field(
                "title_en", "string", "Title (English)", help="English title (optional, manual)."
            ),
            _field("url", "url", "URL", "sources", help="URL of the document."),
            _system(
                "canonical_url",
                "url",
                "Canonical URL",
                filter="text",
                computed_from="url",
                unique="live",
                help="Normalised URL used to detect duplicates; computed from the URL.",
            ),
            _field(
                "publisher", "string", "Publisher", in_list=True, help="Publishing site or host."
            ),
            _field(
                "publisher_org_id",
                "ref",
                "Publisher organisation",
                ref_types=("organization",),
                help="Publishing organisation.",
            ),
            _field(
                "doc_type",
                "vocab",
                "Document type",
                vocabulary="doc_type",
                in_list=True,
                help="Type of document.",
            ),
            _field(
                "language",
                "vocab",
                "Language",
                vocabulary="language",
                in_list=True,
                help="Language of the document (ISO 639-1).",
            ),
            _field(
                "published",
                "partial_date",
                "Published",
                in_list=True,
                help="Publication date (calendar date in Europe/Kyiv) with its precision.",
            ),
            _field(
                "published_basis",
                "vocab",
                "Publication date basis",
                vocabulary="date_basis",
                help="How the publication date is known; required with a publication date.",
            ),
            _field(
                "published_text",
                "string",
                "Publication date text",
                "sources",
                sortable=False,
                help="The publication date exactly as written in the source.",
            ),
            _system(
                "published_at_utc",
                "datetime",
                "Published at (UTC)",
                filter="date_range",
                sortable=True,
                help="Machine-readable publication time in UTC, if the source gives one.",
            ),
            _field(
                "retrieved_at",
                "datetime",
                "Retrieved at",
                "sources",
                help="Retrieval time of the current content version (UTC); required with a URL.",
            ),
            _system("source_id", "string", "Source", help="Source key (sources.yaml)."),
            _system("external_id", "string", "External ID", help="Identifier given by the source."),
            _system(
                "raw_snapshot_id",
                "string",
                "Raw snapshot",
                help="Raw snapshot of the current content version.",
            ),
            _system(
                "text_hash", "string", "Text hash", help="SHA-256 of the current text version."
            ),
            _system(
                "extraction_method",
                "string",
                "Extraction method",
                help="How the text was extracted.",
            ),
            _field(
                "archive_urls",
                "url_list",
                "Archive URLs",
                "sources",
                filter=None,
                help="Archived copies of the document.",
            ),
            _field(
                "license",
                "vocab",
                "License",
                "sources",
                vocabulary="license",
                help="License of the content.",
            ),
            _field(
                "screening_status",
                "vocab",
                "Screening status",
                vocabulary="screening_status",
                required=True,
                default="unscreened",
                in_list=True,
                help="Screening for the document analysis (CODEBOOK §2.8).",
            ),
            _field(
                "screening_reason",
                "vocab",
                "Exclusion reason",
                vocabulary="exclusion_reason",
                help="Reason for excluding the document.",
            ),
            _field(
                "screening_note", "text", "Screening note", help="Note on the screening decision."
            ),
            _field(
                "links",
                "doc_links",
                "Linked projects and services",
                "sources",
                ref_types=("project", "service"),
                help=(
                    "Projects and services the document refers to; automatic links stay "
                    "suggested until a person confirms them."
                ),
            ),
            _virtual(
                "linked_in_paper_scope",
                "bool",
                "Linked to in-scope project",
                help="Whether a confirmed link points to an in-scope project or its services.",
            ),
            _virtual(
                "text",
                "text",
                "Text",
                "sources",
                filter=None,
                sortable=False,
                detail_only=True,
                help="Extracted text of the current version, shown as plain text.",
            ),
            table_type=True,
        ),
        [
            "title",
            "title_en",
            "url",
            "retrieved_at",
            "publisher",
            "doc_type",
            "language",
            "published",
            "published_basis",
            "published_text",
        ],
    ),
)

ORGANIZATION = EntityTypeSpec(
    name="organization",
    label="Organization",
    label_plural="Organizations",
    prefix="org",
    label_rule="names",
    default_sort="name_en",
    table_view=True,
    constraints=_NAMES_CONSTRAINT,
    fields=_in_create(
        _curated(
            _field(
                "slug",
                "slug",
                "Slug",
                in_list=True,
                unique="all",
                help="Optional URL-friendly identifier: lower-case letters, digits and hyphens.",
            ),
            _system(
                "seed_key", "slug", "Seed key", "system", tracked=False, internal=True, unique="all"
            ),
            *_names(),
            _aliases(),
            _field(
                "org_type",
                "vocab",
                "Organization type",
                "classification",
                vocabulary="org_type",
                in_list=True,
                help="Type of organisation.",
            ),
            _field(
                "country",
                "string",
                "Country",
                in_list=True,
                pattern=COUNTRY_PATTERN,
                upper=True,
                max_length=2,
                help="Country as ISO 3166-1 alpha-2 code (upper case).",
            ),
            _field("urls", "url_list", "URLs", help="Websites of the organisation."),
            _field(
                "description", "text", "Description", help="Short description based on the sources."
            ),
            table_type=True,
        ),
        ["slug", "name_en", "name_uk", "org_type", "country", "urls"],
    ),
)


def _sortable_text(name: str, label: str, **kw: Any) -> FieldSpec:
    """Text field of the "other" types: filter text and sortable (DATA_MODEL §3.5)."""
    return _field(name, "text", label, sortable=True, **kw)


PARTICIPATION = EntityTypeSpec(
    name="participation",
    label="Participation",
    label_plural="Participations",
    prefix="par",
    label_rule="participation",
    default_sort="organization_id",
    fields=_in_create(
        _curated(
            _field(
                "organization_id",
                "ref",
                "Organization",
                ref_types=("organization",),
                required=True,
                in_list=True,
                help="The participating organisation.",
            ),
            _field(
                "subject_id",
                "ref",
                "Subject",
                ref_types=PORTFOLIO_TYPES,
                required=True,
                in_list=True,
                help="The project, service or component.",
            ),
            _field(
                "role",
                "vocab",
                "Role",
                vocabulary="participation_role",
                required=True,
                in_list=True,
                help="Role of the organisation.",
            ),
            _field(
                "start", "partial_date", "Start", in_list=True, help="Start of the participation."
            ),
            _field(
                "end",
                "partial_date",
                "End",
                in_list=True,
                help="End of the participation; not before the start.",
            ),
            _sortable_text("description", "Description"),
        ),
        ["start", "end", "description"],
    ),
)

COMPONENT = EntityTypeSpec(
    name="component",
    label="Component",
    label_plural="Components",
    prefix="cmp",
    label_rule="names",
    default_sort="name_en",
    constraints=_NAMES_CONSTRAINT,
    fields=_in_create(
        _curated(
            *_names(),
            _aliases(),
            _field(
                "component_type",
                "vocab",
                "Component type",
                vocabulary="component_type",
                in_list=True,
                help="Type of platform or infrastructure component.",
            ),
            _sortable_text("description", "Description"),
            _field("urls", "url_list", "URLs", help="URLs of the component."),
        ),
        ["name_en", "name_uk", "component_type", "description", "urls"],
    ),
)

RELATION = EntityTypeSpec(
    name="relation",
    label="Relation",
    label_plural="Relations",
    prefix="rel",
    label_rule="relation",
    default_sort="relation_type",
    fields=_in_create(
        _curated(
            _field(
                "from_id",
                "ref",
                "From",
                ref_types=PORTFOLIO_TYPES,
                required=True,
                in_list=True,
                help="Read as: from — relation type — to.",
            ),
            _field(
                "to_id",
                "ref",
                "To",
                ref_types=PORTFOLIO_TYPES,
                required=True,
                in_list=True,
                help="Target of the relation; must differ from the source.",
            ),
            _field(
                "relation_type",
                "vocab",
                "Relation type",
                vocabulary="relation_type",
                required=True,
                in_list=True,
                help="Type of relation (CODEBOOK §3).",
            ),
            _sortable_text("description", "Description"),
            _virtual(
                "endpoint",
                "ref",
                "Endpoint",
                ref_types=PORTFOLIO_TYPES,
                sortable=False,
                help="Filter only: matches either end of the relation.",
            ),
        ),
        ["description"],
    ),
)

INDICATOR = EntityTypeSpec(
    name="indicator",
    label="Indicator",
    label_plural="Indicators",
    prefix="ind",
    label_rule="indicator",
    default_sort="-as_of",
    fields=_in_create(
        _curated(
            _field(
                "subject_id",
                "ref",
                "Subject",
                ref_types=(*PORTFOLIO_TYPES, "organization"),
                required=True,
                in_list=True,
                help="The project, service, component or organisation measured.",
            ),
            _field(
                "metric",
                "string",
                "Metric",
                required=True,
                in_list=True,
                help="Name of the metric.",
            ),
            _field("value", "number", "Value", required=True, in_list=True, help="Reported value."),
            _field("unit", "string", "Unit", in_list=True, help="Unit of the value."),
            _field(
                "as_of", "partial_date", "As of", in_list=True, help="Reference date of the value."
            ),
            _sortable_text("description", "Description"),
        ),
        ["unit", "as_of", "description"],
    ),
)

EVIDENCE = EntityTypeSpec(
    name="evidence",
    label="Evidence",
    label_plural="Evidence",
    prefix="evd",
    label_rule="evidence",
    default_sort="-created_at",
    constraints=({"one_of_required": ["document_id", "url"]},),
    fields=_in_create(
        _curated(
            _field(
                "subject_id",
                "ref",
                "Subject",
                ref_types=tuple(t for t in CURATED_TYPES if t != "evidence"),
                required=True,
                create_only=True,
                in_list=True,
                help="The record the evidence supports.",
            ),
            _field(
                "target",
                "string",
                "Target",
                required=True,
                create_only=True,
                in_list=True,
                help="What the evidence supports: entity, field:<field name> or dimension:D1 … D4.",
            ),
            _field(
                "document_id",
                "ref",
                "Document",
                ref_types=("document",),
                in_list=True,
                help="The cited document.",
            ),
            _field("url", "url", "URL", help="The cited URL, if the source is not a document."),
            _field("archive_url", "url", "Archive URL", help="Archived copy of the cited URL."),
            _field(
                "retrieved_at",
                "datetime",
                "Retrieved at",
                help="Retrieval time of the cited URL (UTC); required without a document.",
            ),
            _system(
                "raw_snapshot_id",
                "string",
                "Raw snapshot",
                help="Raw snapshot that contains the quote.",
            ),
            _system(
                "text_hash", "string", "Text hash", help="Text version that contains the quote."
            ),
            _field(
                "char_start",
                "int",
                "Quote start",
                help="Start offset of the quote in the document text.",
            ),
            _field(
                "char_end", "int", "Quote end", help="End offset of the quote in the document text."
            ),
            _sortable_text(
                "quote", "Quote", max_length=1000, help="Verbatim quote (at most 1 000 characters)."
            ),
            _field(
                "locator",
                "string",
                "Locator",
                help="Page, paragraph or other location in the source.",
            ),
            _sortable_text("description", "Description"),
            _system(
                "value_snapshot",
                "json",
                "Value snapshot",
                computed_from="target",
                help="Value of the target field when the evidence was recorded.",
            ),
        ),
        ["document_id", "url", "archive_url", "retrieved_at", "quote", "locator", "description"],
    ),
)

VOCABULARY_TERM = EntityTypeSpec(
    name="vocabulary_term",
    label="Vocabulary term",
    label_plural="Vocabulary terms",
    prefix="voc",
    label_rule="vocabulary_term",
    default_sort="vocabulary,sort_order",
    deletable=False,
    fields=_in_create(
        _curated(
            _field(
                "vocabulary",
                "string",
                "Vocabulary",
                required=True,
                create_only=True,
                in_list=True,
                help="The vocabulary the term belongs to.",
            ),
            _field(
                "code",
                "string",
                "Code",
                required=True,
                create_only=True,
                in_list=True,
                pattern=CODE_PATTERN,
                max_length=100,
                help="Stable code; never renamed or deleted, only deactivated.",
            ),
            _field("label_en", "string", "Label (English)", required=True, in_list=True),
            _field("label_uk", "string", "Label (Ukrainian)"),
            _sortable_text("definition", "Definition"),
            _sortable_text("include_note", "Include note"),
            _sortable_text("exclude_note", "Exclude note"),
            _sortable_text("examples", "Examples"),
            _field("sort_order", "int", "Sort order", in_list=True),
            _field(
                "active",
                "bool",
                "Active",
                default=True,
                in_list=True,
                help="Inactive codes stay valid where already used but cannot be newly assigned.",
            ),
            _field(
                "replaced_by",
                "string",
                "Replaced by",
                help="Replacement code of an inactive term (same vocabulary).",
            ),
            _field(
                "attributes",
                "json",
                "Attributes",
                help="Additional attributes, e.g. counts_as_modification for event types.",
            ),
        ),
        [
            "label_uk",
            "definition",
            "include_note",
            "exclude_note",
            "examples",
            "sort_order",
            "attributes",
        ],
    ),
)

SAVED_VIEW = EntityTypeSpec(
    name="saved_view",
    label="Saved view",
    label_plural="Saved views",
    prefix="view",
    label_rule="name",
    default_sort="name",
    fields=_in_create(
        _curated(
            _field("name", "string", "Name", required=True, in_list=True),
            _field(
                "entity_type",
                "string",
                "Table",
                required=True,
                in_list=True,
                help="The table the view applies to.",
            ),
            # Query strings can be long (API §1.4 allows 8 KiB); 500 characters would not do.
            _field(
                "query",
                "string",
                "Query",
                required=True,
                max_length=8192,
                sortable=False,
                help="Canonical URL query string of the view (without ?).",
            ),
            _sortable_text("description", "Description"),
        ),
        ["description"],
    ),
)

COMMENT = EntityTypeSpec(
    name="comment",
    label="Comment",
    label_plural="Comments",
    prefix="cmt",
    label_rule="comment",
    default_sort="-created_at",
    curated=False,
    generic_api=False,
    fields=(
        _field(
            "subject_id",
            "ref",
            "Subject",
            ref_types=CURATED_TYPES,
            required=True,
            create_only=True,
            tracked=False,
        ),
        _field("field", "string", "Field", create_only=True, tracked=False, max_length=100),
        _field(
            "parent_id", "ref", "Reply to", ref_types=("comment",), create_only=True, tracked=False
        ),
        # The length limit is MAX_COMMENT_CHARS (settings), checked by the comments module.
        _field("body_md", "text", "Comment", required=True, max_length=1_000_000),
        _system("status", "string", "Status", "basics"),
        _system("resolved_by", "string", "Resolved by", "basics"),
        _system("resolved_at", "datetime", "Resolved at", "basics"),
        *_system_columns(),
    ),
)

ENTITY_TYPES: dict[str, EntityTypeSpec] = {
    spec.name: spec
    for spec in (
        PROJECT,
        SERVICE,
        EVENT,
        DOCUMENT,
        ORGANIZATION,
        PARTICIPATION,
        COMPONENT,
        RELATION,
        INDICATOR,
        EVIDENCE,
        VOCABULARY_TERM,
        SAVED_VIEW,
        COMMENT,
    )
}

PREFIXES: dict[str, str] = {spec.prefix: spec.name for spec in ENTITY_TYPES.values()}

#: Default sort of deleted views (trash), API §3.1.
TRASH_DEFAULT_SORT = "-deleted_at"


def generic_types() -> list[EntityTypeSpec]:
    """Entity types served by the generic /api/entities endpoints (API §2)."""
    return [spec for spec in ENTITY_TYPES.values() if spec.generic_api]


def type_of_id(entity_id: str) -> str | None:
    """Entity type of a well-formed ID (by prefix), else None."""
    from mdt.domain.ids import id_prefix

    prefix = id_prefix(entity_id)
    return PREFIXES.get(prefix) if prefix else None


# --------------------------------------------------------------------------------------
# Quick filters and period presets (API §3.1)
# --------------------------------------------------------------------------------------

PERIOD_CODES = ("pre_ministry", "pre_invasion", "full_scale_war", "unknown")


def _toggle(key: str, label: str, query: str) -> dict[str, Any]:
    return {"key": key, "label": label, "kind": "toggle", "query": query}


def period_presets(field: str, parameters: PeriodParameters) -> dict[str, Any]:
    """One quick filter of kind ``preset``: mutually exclusive date presets for the
    three periods, each ``{key, label, query}`` (API §3.1).

    Dates that straddle a cut-off match no preset (``within`` semantics).
    """
    ministry = parameters.ministry_founded
    invasion = parameters.full_scale_invasion
    day = timedelta(days=1)
    return {
        "key": "period",
        "label": "Period",
        "kind": "preset",
        "field": field,
        "presets": [
            {
                "key": "pre_ministry",
                "label": f"Before the ministry (to {ministry - day})",
                "query": f"f.{field}=within:..{ministry - day}",
            },
            {
                "key": "pre_invasion",
                "label": f"Ministry, before the invasion ({ministry} – {invasion - day})",
                "query": f"f.{field}=within:{ministry}..{invasion - day}",
            },
            {
                "key": "full_scale_war",
                "label": f"Full-scale war (from {invasion})",
                "query": f"f.{field}=within:{invasion}..",
            },
        ],
    }


def quick_filters(entity_type: str, parameters: PeriodParameters | None) -> list[dict[str, Any]]:
    """Quick filters of an entity type (API §3.1); presets need the parameters."""
    unverified = _toggle("unverified", "Unverified", "f.verification_status=in:unverified")
    open_comments = _toggle("open_comments", "Open comments", "f.open_comments=range:1..")
    chips = {
        "key": "period",
        "label": "Period",
        "kind": "chips",
        "field": "period",
        "values": list(PERIOD_CODES),
    }
    if entity_type in ("project", "service"):
        scope_field = "in_paper_scope" if entity_type == "project" else "project_in_paper_scope"
        return [
            unverified,
            open_comments,
            _toggle("no_start_date", "No start date", "f.launch=empty:true"),
            _toggle("in_scope", "In paper scope", f"f.{scope_field}=eq:true"),
            chips,
        ]
    if entity_type == "event":
        filters = [
            unverified,
            open_comments,
            _toggle("undated", "Undated", "f.date=empty:true"),
            _toggle("in_scope", "In paper scope", "f.subject_in_paper_scope=eq:true"),
        ]
        return filters + ([period_presets("date", parameters)] if parameters else [])
    if entity_type == "document":
        filters = [
            unverified,
            open_comments,
            _toggle("unscreened", "Unscreened", "f.screening_status=in:unscreened"),
            _toggle("in_scope", "In paper scope", "f.linked_in_paper_scope=eq:true"),
        ]
        return filters + ([period_presets("published", parameters)] if parameters else [])
    if entity_type == "organization":
        return [unverified, open_comments]
    return []


def meta_entity_types(parameters: PeriodParameters | None) -> dict[str, dict[str, Any]]:
    """``entity_types`` of ``GET /api/meta``: every generic type with fields and filters."""
    return {spec.name: spec.meta(parameters) for spec in generic_types()}
