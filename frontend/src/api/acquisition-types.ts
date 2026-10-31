// TypeScript types of the Phase 2 endpoints (docs/API.md §7: collectors and
// runs, raw snapshots, proposals, observations, merge and unmerge, uploads,
// manual documents and imports; tables in docs/DATA_MODEL.md §14). Shared
// shapes (items, refs, warnings) live in types.ts.
import type { EntityType, Item, JsonObject, JsonValue, Refs, TableEntityType, WriteWarning } from './types';

/** Phase 2 lists (docs/API.md §7.1). */
export interface PageOf<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Collectors and runs (§7.2, docs/DATA_MODEL.md §14.2–§14.4)
// ---------------------------------------------------------------------------

export const RUN_STATUSES = ['running', 'succeeded', 'partial', 'failed', 'cancelled'] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

export const RUN_TRIGGERS = ['cli', 'ui'] as const;
export type RunTrigger = (typeof RUN_TRIGGERS)[number];

/** Run parameters a collector may support (docs/COLLECTORS.md §6.4). */
export const RUN_PARAMS = ['limit', 'refetch', 'recall_sample', 'recall_seed', 'document_ids'] as const;
export type RunParam = (typeof RUN_PARAMS)[number];

export type UnavailableReason = 'disabled' | 'contact_email_missing';

/** The `stats` counters of a run (all present, 0 by default) and collector-specific `extra` counters. */
export interface RunStats {
  requests: number;
  not_modified: number;
  robots_disallowed: number;
  bytes: number;
  snapshots: number;
  pages_parsed: number;
  parse_errors: number;
  items_seen: number;
  entities_created: number;
  entities_updated: number;
  revisions: number;
  proposals_opened: number;
  proposals_seen_again: number;
  proposals_superseded: number;
  observations_new: number;
  observations_missing: number;
  links_suggested: number;
  messages_suppressed: number;
  errors: number;
  warnings: number;
  extra: Record<string, JsonValue>;
}

export type MessageLevel = 'info' | 'warning' | 'error';

export interface Run {
  id: string;
  collector: string;
  collector_label: string | null;
  trigger: RunTrigger;
  mode: string;
  /** Parameters given at start; `replay: true` in replay mode. */
  params: JsonObject;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  heartbeat_at: string | null;
  /** Elapsed seconds (so far, for a running run). */
  duration_s: number | null;
  cancel_requested_at: string | null;
  complete_listing: boolean;
  stats: RunStats;
  /** The fatal error of a failed run. */
  error: string | null;
  code_version: string;
  config_hash: string;
  message_counts: Partial<Record<MessageLevel, number>>;
}

export interface RunResponse {
  run: Run;
}

export interface CollectorHost {
  host: string;
  min_interval_s: number;
}

/** What a collector may do per entity type (docs/COLLECTORS.md §2.1, §8). */
export interface TypeDeclaration {
  creates: boolean;
  writes: string[];
  propose_only: string[];
  discontinued: boolean;
}

export interface Collector {
  name: string;
  label: string;
  /** Source ID in docs/SOURCES.md (e.g. `S1`); null for the built-in tagger. */
  source: string | null;
  builtin: boolean;
  enabled: boolean;
  available: boolean;
  unavailable_reason: UnavailableReason | null;
  needs_server_check: boolean;
  modes: string[];
  /** The run parameters the collector supports. */
  params: string[];
  hosts: CollectorHost[];
  exclude_hosts: string[];
  licence: { code: string; statement: string | null };
  declaration: Partial<Record<string, TypeDeclaration>>;
  last_run: Run | null;
  running_run_id: string | null;
  observations: { total: number; present: number; missing: number };
  open_proposals: number;
}

export interface CollectorsResponse {
  collectors: Collector[];
}

export interface CollectorResponse {
  collector: Collector;
  /** The 10 newest runs. */
  recent_runs: Run[];
}

export interface StartRunRequest {
  collector: string;
  mode?: string;
  params?: JsonObject;
}

export const FETCH_OUTCOMES = [
  'ok',
  'not_modified',
  'redirect',
  'http_error',
  'network_error',
  'robots_disallowed',
  'blocked',
  'too_large',
  'refused',
] as const;
export type FetchOutcome = (typeof FETCH_OUTCOMES)[number];

export interface FetchLogEntry {
  id: number;
  at: string;
  method: string;
  url: string;
  host: string;
  purpose: 'robots' | 'content';
  attempt: number;
  status: number | null;
  outcome: FetchOutcome;
  bytes: number | null;
  duration_ms: number | null;
  raw_snapshot_id: string | null;
  retry_after_s: number | null;
  error: string | null;
}

export interface RunMessage {
  id: number;
  at: string;
  level: MessageLevel;
  code: string;
  message: string;
  url: string | null;
  raw_snapshot_id: string | null;
  subject_id: string | null;
  details: JsonObject;
}

export type FetchLogResponse = PageOf<FetchLogEntry>;
export type RunMessagesResponse = PageOf<RunMessage> & { refs: Refs };

/** `runs` of GET /api/stats. */
export interface RunsSummary {
  running: { id: string; collector: string; started_at: string } | null;
  last_finished: { id: string; collector: string; status: RunStatus; finished_at: string | null } | null;
}

// ---------------------------------------------------------------------------
// Raw snapshots (§7.3) and uploads (§7.7)
// ---------------------------------------------------------------------------

export interface Snapshot {
  id: string;
  run_id: string | null;
  source_id: string;
  /** `live`, `wayback:<timestamp>`, `upload` or `replay`. */
  via: string;
  url: string | null;
  final_url: string | null;
  redirects: string[];
  http_status: number | null;
  fetched_at: string;
  headers: Record<string, string>;
  content_type: string | null;
  filename: string | null;
  sha256: string;
  size: number;
}

/** Defaults derived from a stored file (docs/COLLECTORS.md §10.1); never written by themselves. */
export interface Suggested {
  title: string | null;
  language: string | null;
  publisher: string | null;
  extraction_method: string;
  char_count: number;
  warnings: WriteWarning[];
}

export interface UploadResponse {
  upload: Snapshot;
  suggested: Suggested;
}

// ---------------------------------------------------------------------------
// Proposals (§7.4, docs/DATA_MODEL.md §16)
// ---------------------------------------------------------------------------

export const PROPOSAL_KINDS = [
  'create_entity',
  'update_field',
  'create_event',
  'possible_duplicate',
  'possibly_discontinued',
] as const;
export type ProposalKind = (typeof PROPOSAL_KINDS)[number];

export const PROPOSAL_STATES = ['open', 'accepted', 'accepted_modified', 'rejected', 'superseded'] as const;
export type ProposalState = (typeof PROPOSAL_STATES)[number];

export const PROPOSAL_SORTS = ['-last_seen_at', 'last_seen_at', '-created_at', 'created_at'] as const;
export type ProposalSort = (typeof PROPOSAL_SORTS)[number];

export interface Proposal {
  id: string;
  kind: ProposalKind;
  state: ProposalState;
  entity_type: TableEntityType;
  subject_id: string | null;
  related_id: string | null;
  field: string | null;
  current_value: JsonValue;
  proposed_value: JsonValue;
  /** The subject's value of `field` (or `status`) now; null for kinds without one. */
  live_value: JsonValue;
  /** Kind-specific (docs/DATA_MODEL.md §16.1). */
  payload: JsonObject;
  collector: string;
  first_run_id: string;
  last_run_id: string;
  raw_snapshot_id: string | null;
  source_url: string | null;
  quote: string | null;
  locator: string | null;
  observation_id: number | null;
  seen_count: number;
  created_at: string;
  last_seen_at: string;
  decided_at: string | null;
  decided_by: string | null;
  decision_note: string | null;
  result_id: string | null;
}

/** Labels of every record a proposal list mentions, keyed by ID. */
export type ProposalListResponse = PageOf<Proposal> & { refs: Refs };

export interface ProposalTexts {
  current: string | null;
  proposed: string | null;
}

export interface ProposalDetailResponse {
  proposal: Proposal;
  refs: Refs;
  /** Both document texts of a text-version proposal, else null. */
  texts: ProposalTexts | null;
}

export interface PatternPrecision {
  pattern_id: string;
  open: number;
  accepted: number;
  accepted_modified: number;
  rejected: number;
  precision: number | null;
}

export interface ProposalSummary {
  open: number;
  by_kind: Partial<Record<ProposalKind, number>>;
  by_collector: Record<string, number>;
  by_entity_type: Partial<Record<EntityType, number>>;
  patterns: PatternPrecision[];
}

export interface AcceptRequest {
  values?: JsonObject | null;
  match_id?: string | null;
  note?: string | null;
}

export interface AcceptResponse {
  proposal: Proposal;
  changed: boolean;
  result_id: string | null;
  revision_ids: number[];
  batch_id: string | null;
}

export interface RejectResponse {
  proposal: Proposal;
}

export type BulkDecisionStatus = 'accepted' | 'rejected' | 'superseded' | 'stale' | 'needs_values' | 'error';

export interface BulkDecisionRequest {
  ids: string[];
  action: 'accept' | 'reject';
  note?: string | null;
}

export interface BulkDecisionResponse {
  batch_id: string;
  results: { id: string; status: BulkDecisionStatus; error: { code: string; message: string } | null }[];
}

// ---------------------------------------------------------------------------
// Observations (§7.5)
// ---------------------------------------------------------------------------

export interface Observation {
  id: number;
  collector: string;
  key: string;
  entity_type: string;
  subject_id: string | null;
  bound_by: 'auto' | 'proposal' | null;
  bound_at: string | null;
  external_id: string | null;
  url: string | null;
  label: string | null;
  first_seen_at: string;
  first_seen_run: string;
  last_seen_at: string;
  last_seen_run: string;
  present: boolean;
  missing_since_at: string | null;
  missing_runs: number;
  last_snapshot_id: string | null;
  details: JsonObject;
}

export type ObservationListResponse = PageOf<Observation> & { refs: Refs };

// ---------------------------------------------------------------------------
// Merge and unmerge (§7.6, docs/DATA_MODEL.md §18)
// ---------------------------------------------------------------------------

export type MergeChoice = 'survivor' | 'merged' | 'union';

export interface MergePreviewField {
  name: string;
  survivor: JsonValue;
  merged: JsonValue;
  list: boolean;
  default: MergeChoice;
}

export interface MergeConflict {
  kind: string;
  id: string;
  label: string;
  message: string;
}

export interface MergePreview {
  fields: MergePreviewField[];
  /** References to be moved, per entity type. */
  repoint: Record<string, number>;
  conflicts: MergeConflict[];
}

export interface MergeRequest {
  merged_id: string;
  fields: Record<string, MergeChoice>;
  note?: string | null;
  proposal_id?: string | null;
}

export interface MergeResponse {
  item: Item;
  merge_id: string;
  batch_id: string;
  revision_ids: number[];
}

export interface UnmergeSkipped {
  entity_type: string;
  id: string;
  field: string;
  current: JsonValue;
}

export interface UnmergeResponse extends MergeResponse {
  skipped: UnmergeSkipped[];
}

// ---------------------------------------------------------------------------
// Manual documents (§7.8)
// ---------------------------------------------------------------------------

export interface FetchDocumentResponse {
  snapshot: Snapshot;
  suggested: Suggested;
}

export interface ManualDocumentRequest {
  snapshot_id: string;
  title?: string | null;
  url?: string | null;
  retrieved_at?: string | null;
  doc_type?: string | null;
  language?: string | null;
  publisher?: string | null;
  published?: string | null;
  published_basis?: string | null;
  published_text?: string | null;
  license?: string | null;
  note?: string | null;
}

export interface ManualDocumentResponse {
  item: Item;
  revision_id: number;
  warnings: WriteWarning[];
}

export type FetchFailedReason =
  | 'robots_disallowed'
  | 'robots_unavailable'
  | 'blocked'
  | 'throttled'
  | 'http_error'
  | 'network_error'
  | 'too_large';

// ---------------------------------------------------------------------------
// Imports (§7.9, docs/COLLECTORS.md §9)
// ---------------------------------------------------------------------------

export interface ImportPreviewRequest {
  upload_id: string;
  entity_type: TableEntityType;
  sheet?: string | null;
}

export interface ImportPreview {
  sheets: string[] | null;
  columns: string[];
  /** The first rows, one cell per column. */
  preview: string[][];
  suggested_mapping: Record<string, string>;
  importable_fields: string[];
  key_fields: string[];
}

export interface ImportDryRunRequest extends ImportPreviewRequest {
  mapping: Record<string, string>;
  key_field: string | null;
}

export interface ImportRunRequest extends ImportDryRunRequest {
  note?: string | null;
}

export type ImportConflictReason = 'manual' | 'seed' | 'verified' | 'restored';

export interface PlanRow {
  row: number;
  action: 'create' | 'update' | 'unchanged' | 'error';
  id: string | null;
  changes: Record<string, [JsonValue, JsonValue]>;
  conflicts: { field: string; current: JsonValue; new: JsonValue; reason: ImportConflictReason }[];
  errors: Record<string, string[]>;
}

export interface PlanStats {
  rows: number;
  create: number;
  update: number;
  unchanged: number;
  conflicts: number;
  errors: number;
}

export interface Plan {
  stats: PlanStats;
  rows: PlanRow[];
}

export interface ImportRun {
  id: string;
  upload_id: string;
  filename: string;
  file_label: string;
  entity_type: TableEntityType;
  sheet: string | null;
  status: 'done' | 'failed';
  mapping: Record<string, string>;
  key_field: string | null;
  note: string | null;
  stats: Partial<PlanStats>;
  /** The stored row errors and conflicts. */
  errors: PlanRow[];
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ImportRunResponse {
  import: ImportRun;
  result: Plan;
}

export type ImportListResponse = PageOf<ImportRun>;
