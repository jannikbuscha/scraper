// Synthetic Phase 2 objects for component tests (docs/API.md §7). All values
// are invented examples (example.org, "Example …"), never facts about the
// real sources or the portfolio.
import type { Collector, Observation, Proposal, Run, RunStats } from '../api/acquisition-types';
import type { EntityTypeMeta, Meta, Vocabulary } from '../api/types';
import { exampleMeta, exampleVocabularies, fieldSpec, projectMeta, term, vocabulary } from './fixtures';

/** A project type with the fields the Phase 2 forms use (synthetic labels). */
export const p2ProjectMeta: EntityTypeMeta = {
  ...projectMeta,
  fields: [
    fieldSpec('slug', 'slug', { label: 'Slug', required: true, in_create: true }),
    ...projectMeta.fields.map((field) => (field.name === 'name_en' ? { ...field, in_create: true } : field)),
    fieldSpec('name_uk', 'string', { label: 'Name (UK)', in_create: true }),
    fieldSpec('description_uk', 'text', { label: 'Description (UK)' }),
    fieldSpec('official_urls', 'url_list', { label: 'Official URLs', in_create: true }),
    fieldSpec('in_paper_scope', 'bool', { label: 'In paper scope', required: true, in_create: true, default: false }),
    fieldSpec('scope_note', 'text', { label: 'Scope note', in_create: true }),
    fieldSpec('status', 'vocab', { label: 'Status', vocabulary: 'example_status', in_create: true }),
  ],
};

const eventMeta: EntityTypeMeta = {
  label: 'Event',
  label_plural: 'Events',
  prefix: 'evt',
  table_view: true,
  default_sort: '-date',
  constraints: [],
  quick_filters: [],
  fields: [
    fieldSpec('subject_id', 'ref', { label: 'Subject', ref_types: ['project', 'service'], required: true, in_create: true }),
    fieldSpec('event_type', 'vocab', { label: 'Event type', vocabulary: 'example_event_type', required: true, in_create: true }),
    fieldSpec('date', 'partial_date', { label: 'Date', in_create: true }),
    fieldSpec('date_basis', 'vocab', { label: 'Date basis', vocabulary: 'example_basis', in_create: true }),
    fieldSpec('date_text', 'string', { label: 'Date text', in_create: true }),
    fieldSpec('description_en', 'text', { label: 'Description (EN)', in_create: true }),
  ],
};

const serviceMeta: EntityTypeMeta = {
  label: 'Service',
  label_plural: 'Services',
  prefix: 'svc',
  table_view: true,
  default_sort: 'name_en',
  constraints: [{ one_of_required: ['name_en', 'name_uk'] }],
  quick_filters: [],
  fields: [
    fieldSpec('name_en', 'string', { label: 'Name (EN)', in_create: true }),
    fieldSpec('name_uk', 'string', { label: 'Name (UK)', in_create: true }),
    fieldSpec('urls', 'url_list', { label: 'URLs', in_create: true }),
    fieldSpec('channels', 'vocab_list', { label: 'Channels', vocabulary: 'example_domain', in_create: true }),
    fieldSpec('status', 'vocab', { label: 'Status', vocabulary: 'example_status', in_create: true }),
  ],
};

/** The example vocabularies plus those of the Phase 2 forms. */
export const p2Vocabularies: Vocabulary[] = [
  ...exampleVocabularies,
  vocabulary('example_status', [term('active', 'Example active', 10), term('discontinued', 'Example discontinued', 20), term('suspended', 'Example suspended', 30)]),
  vocabulary('example_event_type', [term('launch', 'Example launch', 10), term('first_archived', 'Example first archived', 20)]),
  vocabulary('example_basis', [term('inferred', 'Example inferred', 10), term('stated_in_source', 'Example stated', 20)]),
];

/** Metadata with the project, event and service types of the Phase 2 tests. */
export const p2Meta: Meta = {
  ...exampleMeta,
  entity_types: { project: p2ProjectMeta, event: eventMeta, service: serviceMeta },
};

export const emptyStats = (overrides: Partial<RunStats> = {}): RunStats => ({
  requests: 0,
  not_modified: 0,
  robots_disallowed: 0,
  bytes: 0,
  snapshots: 0,
  pages_parsed: 0,
  parse_errors: 0,
  items_seen: 0,
  entities_created: 0,
  entities_updated: 0,
  revisions: 0,
  proposals_opened: 0,
  proposals_seen_again: 0,
  proposals_superseded: 0,
  observations_new: 0,
  observations_missing: 0,
  links_suggested: 0,
  messages_suppressed: 0,
  errors: 0,
  warnings: 0,
  extra: {},
  ...overrides,
});

export const exampleRun = (overrides: Partial<Run> = {}): Run => ({
  id: 'run_EXAMPLE',
  collector: 'example_collector',
  collector_label: 'Example collector',
  trigger: 'ui',
  mode: 'incremental',
  params: {},
  status: 'running',
  started_at: '2026-01-01T10:00:00.000000Z',
  finished_at: null,
  heartbeat_at: '2026-01-01T10:00:30.000000Z',
  duration_s: 30,
  cancel_requested_at: null,
  complete_listing: false,
  stats: emptyStats(),
  error: null,
  code_version: '0.0.0-test',
  config_hash: 'abc',
  message_counts: { error: 0, warning: 0, info: 0 },
  ...overrides,
});

export const exampleCollector = (overrides: Partial<Collector> = {}): Collector => ({
  name: 'example_collector',
  label: 'Example collector',
  source: 'S0',
  builtin: false,
  enabled: true,
  available: true,
  unavailable_reason: null,
  needs_server_check: false,
  modes: ['incremental', 'full'],
  params: ['limit'],
  hosts: [{ host: 'example.org', min_interval_s: 1 }],
  exclude_hosts: [],
  licence: { code: 'unknown', statement: null },
  declaration: { project: { creates: false, writes: ['description_en'], propose_only: [], discontinued: true } },
  last_run: null,
  running_run_id: null,
  observations: { total: 0, present: 0, missing: 0 },
  open_proposals: 0,
  ...overrides,
});

export const exampleProposal = (overrides: Partial<Proposal> = {}): Proposal => ({
  id: 'prp_EXAMPLE',
  kind: 'update_field',
  state: 'open',
  entity_type: 'project',
  subject_id: 'prj_A',
  related_id: null,
  field: 'name_en',
  current_value: 'Example name',
  proposed_value: 'Example name (source)',
  live_value: 'Example name',
  payload: {},
  collector: 'example_collector',
  first_run_id: 'run_EXAMPLE',
  last_run_id: 'run_EXAMPLE',
  raw_snapshot_id: 'raw_EXAMPLE',
  source_url: 'https://example.org/projects/a',
  quote: null,
  locator: null,
  observation_id: null,
  seen_count: 1,
  created_at: '2026-01-01T10:00:00.000000Z',
  last_seen_at: '2026-01-01T10:00:00.000000Z',
  decided_at: null,
  decided_by: null,
  decision_note: null,
  result_id: null,
  ...overrides,
});

export const exampleObservation = (overrides: Partial<Observation> = {}): Observation => ({
  id: 1,
  collector: 'example_collector',
  key: 'entry:example-a',
  entity_type: 'project',
  subject_id: 'prj_A',
  bound_by: 'auto',
  bound_at: '2026-01-01T10:00:00.000000Z',
  external_id: null,
  url: 'https://example.org/projects/a',
  label: 'Example project A',
  first_seen_at: '2026-01-01T10:00:00.000000Z',
  first_seen_run: 'run_EXAMPLE',
  last_seen_at: '2026-01-02T10:00:00.000000Z',
  last_seen_run: 'run_EXAMPLE',
  present: true,
  missing_since_at: null,
  missing_runs: 0,
  last_snapshot_id: null,
  details: {},
  ...overrides,
});
