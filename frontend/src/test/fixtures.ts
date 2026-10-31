// Synthetic metadata and rows for component tests. All values are invented
// examples, never facts about the real portfolio.
import type {
  EntityTypeMeta,
  FieldSpec,
  FieldType,
  Item,
  JsonObject,
  ListResponse,
  Meta,
  Vocabulary,
  VocabTerm,
} from '../api/types';

export function fieldSpec(name: string, type: FieldType, overrides: Partial<FieldSpec> = {}): FieldSpec {
  return {
    name,
    label: name,
    type,
    vocabulary: null,
    ref_types: null,
    group: 'basics',
    required: false,
    editable: true,
    create_only: false,
    system: false,
    tracked: true,
    derived: false,
    virtual: false,
    filter: null,
    sortable: false,
    in_list: false,
    in_create: false,
    default: null,
    bulk_editable: false,
    exportable: true,
    help: null,
    ...overrides,
  };
}

export const projectMeta: EntityTypeMeta = {
  label: 'Project',
  label_plural: 'Projects',
  prefix: 'prj',
  table_view: true,
  default_sort: 'name_en',
  constraints: [{ one_of_required: ['name_en', 'name_uk'] }],
  fields: [
    fieldSpec('name_en', 'string', { label: 'Name (EN)', filter: 'text', sortable: true, in_list: true, in_create: true }),
    fieldSpec('paper_cluster', 'vocab', {
      label: 'Paper cluster',
      vocabulary: 'example_cluster',
      group: 'classification',
      filter: 'multiselect',
      sortable: true,
      in_list: true,
      bulk_editable: true,
    }),
    fieldSpec('policy_domains', 'vocab_list', {
      label: 'Policy domains',
      vocabulary: 'example_domain',
      group: 'classification',
      filter: 'multiselect',
      sortable: true,
      in_list: true,
      bulk_editable: true,
    }),
    fieldSpec('verification_status', 'vocab', {
      label: 'Verification',
      vocabulary: 'verification_status',
      filter: 'multiselect',
      sortable: true,
      in_list: true,
      bulk_editable: true,
      required: true,
      default: 'unverified',
    }),
    fieldSpec('period', 'vocab', {
      label: 'Period',
      vocabulary: 'example_period',
      group: 'wartime',
      editable: false,
      derived: true,
      filter: 'multiselect',
      sortable: true,
      in_list: true,
    }),
  ],
  quick_filters: [
    { key: 'unverified', label: 'Unverified', kind: 'toggle', query: 'f.verification_status=in:unverified' },
    { key: 'period', label: 'Period', kind: 'chips', field: 'period' },
  ],
};

export const exampleMeta: Meta = {
  app_version: '0.0.0-test',
  focal_org_id: null,
  parameters: { ministry_founded: '2000-01-01', full_scale_invasion: '2001-01-01' },
  limits: { max_comment_chars: 10000, max_note_chars: 2000 },
  groups: [
    { key: 'basics', label: 'Basics' },
    { key: 'classification', label: 'Classification' },
    { key: 'wartime', label: 'Wartime' },
    { key: 'system', label: 'System' },
  ],
  vocabularies: {},
  entity_types: { project: projectMeta },
};

export function term(code: string, label: string, sortOrder: number): VocabTerm {
  return {
    id: `voc_${code}`,
    code,
    label_en: label,
    label_uk: null,
    definition: null,
    include_note: null,
    exclude_note: null,
    examples: null,
    sort_order: sortOrder,
    active: true,
    replaced_by: null,
    attributes: {},
    version: 1,
    usage_count: 0,
    open_comments: 0,
  };
}

export function vocabulary(name: string, terms: VocabTerm[]): Vocabulary {
  return { name, label: name, description: null, multi: false, fixed_codes: false, terms };
}

export const exampleVocabularies: Vocabulary[] = [
  vocabulary('example_cluster', [term('cluster_a', 'Example cluster A', 10), term('cluster_b', 'Example cluster B', 20)]),
  vocabulary('example_domain', [term('domain_a', 'Example domain A', 10), term('domain_b', 'Example domain B', 20)]),
  vocabulary('example_period', [term('period_a', 'Example period A', 10), term('period_b', 'Example period B', 20)]),
  vocabulary('verification_status', [
    term('unverified', 'Unverified', 10),
    term('verified', 'Verified', 20),
    term('disputed', 'Disputed', 30),
  ]),
];

export function exampleItem(id: string, fields: JsonObject, overrides: Partial<Item> = {}): Item {
  return {
    id,
    type: 'project',
    label: typeof fields.name_en === 'string' ? fields.name_en : id,
    version: 1,
    created_at: '2026-01-01T00:00:00.000000Z',
    created_by: 'user',
    updated_at: '2026-01-01T00:00:00.000000Z',
    updated_by: 'user',
    deleted_at: null,
    deleted_by: null,
    merged_into: null,
    fields,
    field_meta: {},
    derived: { period: 'period_a' },
    virtual: { open_comments: 0, comment_count: 0 },
    refs: {},
    search_snippet: null,
    ...overrides,
  };
}

export const listResponse = (items: Item[], total = items.length): ListResponse => ({
  items,
  total,
  page: 1,
  page_size: 50,
});
