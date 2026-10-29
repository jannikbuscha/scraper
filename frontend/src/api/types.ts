// TypeScript types for every request and response of docs/API.md (field
// semantics in docs/DATA_MODEL.md). Keep in sync with the contract.

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = Record<string, JsonValue>;

// ---------------------------------------------------------------------------
// Entity types and the field registry (GET /api/meta)
// ---------------------------------------------------------------------------

/** Types with a table and a detail page in the UI (docs/UI.md §2). */
export const TABLE_ENTITY_TYPES = ['project', 'service', 'event', 'document', 'organization'] as const;
export type TableEntityType = (typeof TABLE_ENTITY_TYPES)[number];

export const ENTITY_TYPES = [
  ...TABLE_ENTITY_TYPES,
  'participation',
  'component',
  'relation',
  'indicator',
  'evidence',
  'vocabulary_term',
  'saved_view',
] as const;
export type EntityType = (typeof ENTITY_TYPES)[number];

/** Revisions and feeds also cover comments (docs/API.md §3.4). */
export type RecordType = EntityType | 'comment';

export type FieldType =
  | 'string'
  | 'text'
  | 'slug'
  | 'bool'
  | 'int'
  | 'number'
  | 'url'
  | 'url_list'
  | 'string_list'
  | 'vocab'
  | 'vocab_list'
  | 'ref'
  | 'date'
  | 'partial_date'
  | 'datetime'
  | 'alias_list'
  | 'json'
  | 'doc_links';

export type FilterKind = 'text' | 'multiselect' | 'date_range' | 'bool' | 'number_range' | 'ref';

export type FieldGroup = 'basics' | 'classification' | 'wartime' | 'framework' | 'sources' | 'system';

export interface FieldSpec {
  name: string;
  label: string;
  type: FieldType;
  vocabulary: string | null;
  ref_types: RecordType[] | null;
  group: FieldGroup;
  required: boolean;
  editable: boolean;
  create_only: boolean;
  system: boolean;
  tracked: boolean;
  derived: boolean;
  virtual: boolean;
  filter: FilterKind | null;
  sortable: boolean;
  in_list: boolean;
  in_create: boolean;
  default: JsonValue;
  bulk_editable: boolean;
  /** Has a value per list row: can be a table column and an export column (docs/API.md §5). */
  exportable: boolean;
  help: string | null;
}

export interface OneOfRequiredConstraint {
  one_of_required: string[];
}
export type TypeConstraint = OneOfRequiredConstraint;

export interface QuickFilterToggle {
  key: string;
  label: string;
  kind: 'toggle';
  /** Exactly one `f.<field>=<op>:<value>` pair, e.g. `f.verification_status=in:unverified`. */
  query: string;
}

export interface QuickFilterChips {
  key: string;
  label: string;
  kind: 'chips';
  /** Vocabulary field written as `f.<field>=in:<codes>`. */
  field: string;
}

export interface QuickFilterPresetOption {
  key: string;
  label: string;
  /** One `f.<field>=within:<from>..<to>` pair. */
  query: string;
}

export interface QuickFilterPreset {
  key: string;
  label: string;
  kind: 'preset';
  /** Date field the presets filter (`date` for events, `published` for documents). */
  field: string;
  /** Optional: if absent, the UI generates the presets from `meta.parameters`. */
  presets?: QuickFilterPresetOption[];
}

export type QuickFilter = QuickFilterToggle | QuickFilterChips | QuickFilterPreset;

export interface EntityTypeMeta {
  label: string;
  label_plural: string;
  prefix: string;
  table_view: boolean;
  default_sort: string;
  constraints: TypeConstraint[];
  fields: FieldSpec[];
  quick_filters: QuickFilter[];
}

export interface MetaLimits {
  max_comment_chars: number;
  max_note_chars: number;
  max_page_size: number;
  max_bulk_items: number;
  max_export_rows: number;
}

export interface MetaGroup {
  key: FieldGroup;
  label: string;
}

export interface VocabularyMeta {
  label: string;
  multi: boolean;
  fixed_codes: boolean;
}

export interface Meta {
  app_version: string;
  team_members: string[];
  focal_org_id: string | null;
  parameters: { ministry_founded: string; full_scale_invasion: string } & Record<string, string>;
  limits: MetaLimits;
  groups: MetaGroup[];
  vocabularies: Record<string, VocabularyMeta>;
  entity_types: Partial<Record<EntityType, EntityTypeMeta>>;
}

// ---------------------------------------------------------------------------
// Vocabularies, statistics, lookup
// ---------------------------------------------------------------------------

export interface VocabTerm {
  id: string;
  code: string;
  label_en: string;
  label_uk: string | null;
  definition: string | null;
  include_note: string | null;
  exclude_note: string | null;
  examples: string | null;
  sort_order: number | null;
  active: boolean;
  replaced_by: string | null;
  attributes: JsonObject;
  version: number;
  usage_count: number;
  open_comments: number;
}

export interface Vocabulary {
  name: string;
  label: string;
  description: string | null;
  multi: boolean;
  fixed_codes: boolean;
  terms: VocabTerm[];
}

export interface VocabResponse {
  vocabularies: Vocabulary[];
}

export interface EntityStats {
  total: number;
  unverified: number;
  deleted: number;
}

export interface StatsResponse {
  entities: Partial<Record<EntityType, EntityStats>>;
  open_comments: number;
}

export interface LookupItem {
  id: string;
  type: RecordType;
  label: string;
  deleted: boolean;
  context: string | null;
}

export interface LookupResponse {
  items: LookupItem[];
}

export interface HealthResponse {
  status: string;
  version: string;
  schema_revision: string;
}

// ---------------------------------------------------------------------------
// Items (list and detail representation, docs/API.md §2)
// ---------------------------------------------------------------------------

export type VerificationStatus = 'unverified' | 'verified' | 'disputed';

/** Field provenance (docs/DATA_MODEL.md §5). */
export interface FieldMetaEntry {
  src: string;
  by: string;
  at: string;
  locked: boolean;
  verified: VerificationStatus;
  evidence_id: string | null;
  restored_from_version: number | null;
}

/** Label of a referenced row (`refs` maps). */
export interface RefLabel {
  id: string;
  type: RecordType;
  label: string;
  deleted: boolean;
}

/** Keys: ref field names, `derived.<name>`, or `links.<subject_id>`. */
export type Refs = Record<string, RefLabel>;

export interface SnippetSegment {
  text: string;
  hit: boolean;
}

export interface Alias {
  text: string;
  lang: string | null;
  case_sensitive: boolean;
  kind: string;
  exclude_patterns: string[];
}

export interface DocLink {
  subject_id: string;
  origin: 'auto' | 'manual';
  state: 'suggested' | 'confirmed' | 'rejected';
  matched_aliases?: string[];
  match_count?: number | null;
  snippet?: string | null;
}

export interface Item {
  id: string;
  type: EntityType;
  label: string;
  version: number;
  created_at: string;
  created_by: string;
  updated_at: string;
  updated_by: string;
  deleted_at: string | null;
  deleted_by: string | null;
  merged_into: string | null;
  fields: JsonObject;
  field_meta: Partial<Record<string, FieldMetaEntry>>;
  /** Present for project and service: launch, launch_start, …, computed_at. */
  derived?: JsonObject | null;
  /** open_comments, comment_count, *_in_paper_scope; detail adds open_comments_by_field. */
  virtual: JsonObject;
  refs: Refs;
  search_snippet: SnippetSegment[] | null;
}

export interface ListResponse {
  items: Item[];
  total: number;
  page: number;
  page_size: number;
}

export interface FacetValue {
  value: string;
  label: string;
  count: number;
}

export interface FacetsResponse {
  field: string;
  values: FacetValue[];
  empty_count: number;
}

export interface ItemResponse {
  item: Item;
}

// ---------------------------------------------------------------------------
// Writes (docs/API.md §3.2)
// ---------------------------------------------------------------------------

export interface WriteWarning {
  code: string;
  message: string;
  field: string | null;
}

export interface CreateRequest {
  data: JsonObject;
  note?: string | null;
}

export interface CreateResponse {
  item: Item;
  revision_id: number;
  warnings: WriteWarning[];
}

export interface PatchRequest {
  expected_version: number;
  changes: JsonObject;
  note?: string | null;
}

export interface PatchResponse {
  item: Item;
  changed: boolean;
  revision_id: number | null;
  warnings: WriteWarning[];
}

export interface DeleteRequest {
  expected_version: number;
  note?: string | null;
  cascade?: boolean;
}

export type UndeleteRequest = DeleteRequest;

export interface DeleteResponse {
  item: Item;
  revision_id: number;
  batch_id: string;
}

export type UndeleteResponse = DeleteResponse;

export interface VerifyFieldRequest {
  expected_version: number;
  field: string;
  status: VerificationStatus;
  evidence_id?: string | null;
  note?: string | null;
}

export interface VerifyFieldResponse {
  item: Item;
  /** null for a no-op (the status and evidence were already recorded). */
  revision_id: number | null;
}

export interface RestoreRequest {
  expected_version: number;
  version: number;
  /** Limit the restore to these fields; null = all restorable fields. */
  fields?: string[] | null;
  dry_run?: boolean;
  note?: string | null;
}

/** `{field: [current, restored]}` */
export type RestoreChanges = Record<string, [JsonValue, JsonValue]>;

/** Response of a dry run: only `changes` is guaranteed. */
export interface RestorePreviewResponse {
  changes: RestoreChanges;
  warnings?: WriteWarning[];
  skipped_fields?: string[];
}

export interface RestoreResponse {
  item: Item;
  changed: boolean;
  revision_id: number | null;
  warnings: WriteWarning[];
  skipped_fields: string[];
  changes: RestoreChanges;
}

export interface BulkItemRef {
  id: string;
  expected_version: number;
}

export interface BulkRequest {
  items: BulkItemRef[];
  set?: JsonObject;
  add?: Record<string, JsonValue[]>;
  remove?: Record<string, JsonValue[]>;
  note?: string | null;
}

export type BulkStatus = 'updated' | 'unchanged' | 'conflict' | 'entity_deleted' | 'error';

export interface BulkResult {
  id: string;
  status: BulkStatus;
  version: number | null;
  current_version: number | null;
  current_values: JsonObject | null;
  error: ApiErrorBody | null;
}

export interface BulkResponse {
  batch_id: string;
  results: BulkResult[];
}

// ---------------------------------------------------------------------------
// Revisions and history (docs/API.md §3.2, §3.4; docs/DATA_MODEL.md §6.3)
// ---------------------------------------------------------------------------

export type Channel = 'seed' | 'ui' | 'collector' | 'import' | 'restore' | 'merge' | 'system';

export type RevisionAction =
  | 'create'
  | 'update'
  | 'verify'
  | 'delete'
  | 'undelete'
  | 'restore'
  | 'merge'
  | 'resolve'
  | 'reopen';

export interface RevisionSummary {
  id: number;
  version: number;
  at: string;
  author: string;
  channel: Channel;
  action: RevisionAction;
  note: string | null;
  changed_fields: string[];
  restored_from: number | null;
  restored_from_version: number | null;
  batch_id: string | null;
}

/** `[old, new]` pairs; empty sections are omitted. */
export interface RevisionDiff {
  fields?: Record<string, [JsonValue, JsonValue]>;
  meta?: Record<string, Record<string, [JsonValue, JsonValue]>>;
  state?: Record<string, [JsonValue, JsonValue]>;
}

export interface RevisionSnapshot {
  fields: JsonObject;
  field_meta: Partial<Record<string, FieldMetaEntry>>;
  state: JsonObject;
}

export interface RevisionFull extends RevisionSummary {
  snapshot: RevisionSnapshot;
  diff: RevisionDiff;
  schema_revision: string | null;
}

export interface RevisionListResponse {
  items: RevisionSummary[];
  total: number;
  page: number;
  page_size: number;
  refs: Refs;
}

export interface RevisionResponse {
  revision: RevisionFull;
  refs: Refs;
}

export interface DiffResponse {
  from: number;
  to: number;
  diff: RevisionDiff;
  not_recorded: string[];
  refs: Refs;
}

export interface RevisionByIdResponse {
  revision: RevisionFull;
  entity_type: RecordType;
  entity_id: string;
  entity_label: string;
  refs: Refs;
}

/** comment → subject_id/subject_type/field/parent_id; vocabulary term → vocabulary; saved view → entity_type. */
export interface ChangeContext {
  subject_id?: string;
  subject_type?: RecordType;
  field?: string | null;
  /** Comments: the root of a reply (null for a root). */
  parent_id?: string | null;
  vocabulary?: string;
  entity_type?: EntityType;
}

export interface ChangeFeedItem {
  id: number;
  entity_type: RecordType;
  entity_id: string;
  entity_label: string;
  version: number;
  at: string;
  author: string;
  channel: Channel;
  action: RevisionAction;
  note: string | null;
  changed_fields: string[];
  restored_from_version: number | null;
  batch_id: string | null;
  context: ChangeContext | null;
}

export interface ChangeFeedResponse {
  items: ChangeFeedItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface RevisionAuthorsResponse {
  authors: string[];
}

// ---------------------------------------------------------------------------
// Comments (docs/API.md §3.3)
// ---------------------------------------------------------------------------

export type CommentStatus = 'open' | 'resolved';

export interface Comment {
  id: string;
  subject_id: string;
  subject_type: EntityType;
  subject_label: string;
  field: string | null;
  parent_id: string | null;
  body_md: string;
  /** Server-rendered and sanitised; pass through lib/sanitize before injecting. */
  body_html: string;
  status: CommentStatus | null;
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
  created_by: string;
  updated_at: string;
  updated_by: string;
  version: number;
  edited: boolean;
  deleted_at: string | null;
  deleted_by: string | null;
}

export interface CommentThread {
  root: Comment;
  replies: Comment[];
}

export interface CommentThreadsResponse {
  threads: CommentThread[];
}

export interface CommentFeedItem {
  root: Comment;
  reply_count: number;
  last_activity_at: string;
}

export interface CommentFeedResponse {
  items: CommentFeedItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface CommentResponse {
  comment: Comment;
}

export interface CommentStatusResponse {
  comment: Comment;
  changed: boolean;
}

export interface CreateCommentRequest {
  subject_id: string;
  field?: string | null;
  parent_id?: string | null;
  body_md: string;
}

export interface EditCommentRequest {
  expected_version: number;
  body_md: string;
  note?: string | null;
}

export interface CommentVersionRequest {
  expected_version: number;
}

export interface CommentNoteRequest {
  expected_version: number;
  note?: string | null;
}

export interface RestoreCommentRequest {
  expected_version: number;
  version: number;
  note?: string | null;
}

/** Query of GET /api/comments with subject_id (threads of one subject). */
export interface CommentThreadsQuery {
  status?: CommentStatus | 'all';
  /** A field name, or `-` for entity-level threads only. */
  field?: string;
  deleted?: DeletedMode;
}

// ---------------------------------------------------------------------------
// Errors (docs/API.md §1.2) and the conflict payload (docs/DATA_MODEL.md §6.5)
// ---------------------------------------------------------------------------

export type DeletedMode = 'exclude' | 'only' | 'include';

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: JsonValue;
}

export interface ApiErrorEnvelope {
  error: ApiErrorBody;
}

export type ConflictAction = 'patch' | 'delete' | 'undelete' | 'verify' | 'restore' | 'bulk' | 'comment';

export interface RowState {
  deleted_at: string | null;
  deleted_by: string | null;
  merged_into?: string | null;
}

export interface ConflictPayload {
  action: ConflictAction;
  entity_type: RecordType;
  entity_id: string;
  base_version: number;
  current_version: number;
  /** Fields of the base snapshot; null if no revision exists for base_version. */
  base: JsonObject | null;
  current: JsonObject;
  base_state: RowState | null;
  current_state: RowState;
  changed_since_base: string[];
  your_changes: JsonObject;
  conflicting_fields: string[];
  meta_changed_since_base: Record<string, Record<string, [JsonValue, JsonValue]>>;
  intervening: RevisionSummary[];
  refs: Refs;
}

export type ValidationErrorDetails = Record<string, string[]>;

export interface EntityDeletedDetails {
  deleted_at: string;
  deleted_by: string;
}

export interface InvalidStateDetails {
  state: string;
}

/** e.g. `{"service": 12}` */
export type HasDependentsDetails = Record<string, number>;

export interface UniqueViolationDetails {
  field: string;
  existing: { id: string; label: string; deleted: boolean };
}

export interface ReferenceDeletedDetails {
  field: string;
  id: string;
  type: RecordType;
  label: string;
}
