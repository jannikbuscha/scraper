import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import type { EntityTypeMeta, Item, JsonObject, Meta, Vocabulary, VocabTerm } from '../api/types';
import { AUTHOR_STORAGE_KEY } from '../lib/author';
import { callsTo, jsonBody, mockApi, requestsTo } from '../test/api-mock';
import { exampleItem, exampleMeta, fieldSpec } from '../test/fixtures';
import { renderRoute } from '../test/render';
import { CodebookPage } from './CodebookPage';

const termMeta: EntityTypeMeta = {
  label: 'Vocabulary term',
  label_plural: 'Vocabulary terms',
  prefix: 'voc',
  table_view: false,
  default_sort: 'vocabulary,sort_order',
  constraints: [],
  fields: [
    fieldSpec('vocabulary', 'string', { label: 'Vocabulary', required: true, create_only: true, in_create: true }),
    fieldSpec('code', 'string', { label: 'Code', required: true, create_only: true, in_create: true }),
    fieldSpec('label_en', 'string', { label: 'Label (EN)', required: true, in_create: true }),
    fieldSpec('label_uk', 'string', { label: 'Label (UK)', in_create: true }),
    fieldSpec('definition', 'text', { label: 'Definition', in_create: true }),
    fieldSpec('sort_order', 'int', { label: 'Sort order', in_create: true }),
    fieldSpec('active', 'bool', { label: 'Active', default: true }),
    fieldSpec('replaced_by', 'string', { label: 'Replaced by' }),
    fieldSpec('attributes', 'json', { label: 'Attributes' }),
    fieldSpec('created_at', 'datetime', { label: 'Created at', group: 'system', editable: false, system: true }),
  ],
  quick_filters: [],
};

const meta: Meta = { ...exampleMeta, entity_types: { ...exampleMeta.entity_types, vocabulary_term: termMeta } };

function term(id: string, code: string, label: string, overrides: Partial<VocabTerm> = {}): VocabTerm {
  return {
    id,
    code,
    label_en: label,
    label_uk: null,
    definition: `Example definition of ${code}`,
    include_note: null,
    exclude_note: null,
    examples: null,
    sort_order: 10,
    active: true,
    replaced_by: null,
    attributes: {},
    version: 3,
    usage_count: 2,
    open_comments: 0,
    ...overrides,
  };
}

const CLUSTER_A = term('voc_a', 'cluster_a', 'Example cluster A');
const CLUSTER_B = term('voc_b', 'cluster_b', 'Example cluster B', { sort_order: 20 });
const CHANGE_TYPE = term('voc_mod', 'example_change', 'Example change type', {
  attributes: { counts_as_modification: true },
  sort_order: 20,
});

const VOCABULARIES: Vocabulary[] = [
  {
    name: 'example_cluster',
    label: 'Example clusters',
    description: 'Synthetic clusters for tests.',
    multi: false,
    fixed_codes: false,
    terms: [CLUSTER_A, CLUSTER_B],
  },
  {
    name: 'event_type',
    label: 'Event types',
    description: null,
    multi: false,
    fixed_codes: false,
    terms: [
      term('voc_fixed', 'example_fixed', 'Example fixed type', { attributes: { fixed: true, counts_as_modification: false } }),
      CHANGE_TYPE,
    ],
  },
  {
    name: 'example_status',
    label: 'Example statuses',
    description: null,
    multi: false,
    fixed_codes: true,
    terms: [term('voc_s', 'status_a', 'Example status A')],
  },
];

/** The term as the generic entity API returns it. */
function termItem(source: VocabTerm, vocabulary: string, version: number, overrides: JsonObject = {}): Item {
  return exampleItem(
    source.id,
    {
      vocabulary,
      code: source.code,
      label_en: source.label_en,
      label_uk: source.label_uk,
      definition: source.definition,
      sort_order: source.sort_order,
      active: source.active,
      replaced_by: source.replaced_by,
      attributes: source.attributes,
      ...overrides,
    },
    { type: 'vocabulary_term', label: `${vocabulary}:${source.code}`, version, derived: null },
  );
}

/** Server state of the edited terms; tests change it to simulate a colleague. */
let items: Record<string, Item>;
/** What GET /api/vocab returns; tests replace it to simulate a colleague. */
let vocabularies: Vocabulary[];

const termRevision = (version: number, changed: string[]) => ({
  id: 70 + version,
  version,
  at: `2026-01-0${version}T10:00:00.000000Z`,
  author: version === 1 ? 'seed' : 'Example Colleague',
  channel: version === 1 ? ('seed' as const) : ('ui' as const),
  action: version === 1 ? ('create' as const) : ('update' as const),
  note: null,
  changed_fields: changed,
  restored_from: null,
  restored_from_version: null,
  batch_id: null,
});

/** History of cluster_a (version 3): v2 and v3 changed its definition. */
function termHistory(url: URL, init: RequestInit | undefined): unknown {
  const base = '/api/entities/vocabulary_term/voc_a';
  if (url.pathname === `${base}/revisions`) {
    const items = [termRevision(3, ['definition']), termRevision(2, ['definition']), termRevision(1, ['label_en'])];
    return { items, total: 3, page: 1, page_size: 50, refs: {} };
  }
  const single = /\/revisions\/(\d+)$/.exec(url.pathname);
  if (url.pathname.startsWith(`${base}/revisions/`) && single) {
    const version = Number(single[1]);
    return {
      revision: {
        ...termRevision(version, ['definition']),
        snapshot: { fields: {}, field_meta: {}, state: {} },
        diff: { fields: { definition: [`Definition ${version - 1}`, `Definition ${version}`] } },
        schema_revision: '0001',
      },
      refs: {},
    };
  }
  if (url.pathname === `${base}/diff`) {
    return {
      from: Number(url.searchParams.get('from')),
      to: Number(url.searchParams.get('to')),
      diff: { fields: { definition: ['Original example definition', 'Example definition of cluster_a'] } },
      not_recorded: [],
      refs: {},
    };
  }
  if (url.pathname === `${base}/restore`) {
    const body = jsonBody(init) as { dry_run: boolean };
    const changes = { definition: ['Example definition of cluster_a', 'Original example definition'] };
    if (body.dry_run) return { changes };
    return { item: items.voc_a, changed: true, revision_id: 80, warnings: [], skipped_fields: [], changes };
  }
  return undefined;
}

function mockCodebookApi() {
  return mockApi((url, init) => {
    const history = termHistory(url, init);
    if (history !== undefined) return history;
    if (url.pathname === '/api/meta') return meta;
    if (url.pathname === '/api/vocab') return { vocabularies };
    if (url.pathname === '/api/comments') return { threads: [] };
    if (url.pathname === '/api/entities/vocabulary_term/voc_b') return { item: termItem(CLUSTER_B, 'example_cluster', 1) };
    if (url.pathname === '/api/entities/vocabulary_term' && init?.method === 'POST') {
      return { item: termItem(term('voc_c', 'cluster_c', 'Example cluster C'), 'example_cluster', 1), revision_id: 51, warnings: [] };
    }
    const match = /^\/api\/entities\/vocabulary_term\/(voc_\w+)$/.exec(url.pathname);
    const item = match?.[1] ? items[match[1]] : undefined;
    if (item && init?.method === 'PATCH') return { item, changed: true, revision_id: 50, warnings: [] };
    if (item) return { item };
    return undefined;
  });
}

const patchBodies = (fetchMock: ReturnType<typeof mockApi>, id: string) =>
  callsTo(fetchMock, `/api/entities/vocabulary_term/${id}`)
    .filter((call) => call.init?.method === 'PATCH')
    .map((call) => jsonBody(call.init));

describe('Codebook', () => {
  beforeEach(() => {
    window.localStorage.setItem(AUTHOR_STORAGE_KEY, 'Example Person');
    vocabularies = VOCABULARIES;
    items = {
      voc_a: termItem(CLUSTER_A, 'example_cluster', 3),
      voc_mod: termItem(CHANGE_TYPE, 'event_type', 5),
    };
  });

  it('edits a term with code and vocabulary read-only and sends only the changed fields', async () => {
    const fetchMock = mockCodebookApi();
    const { user, queryClient } = renderRoute(CodebookPage, { url: '/codebook?vocabulary=example_cluster', path: '/codebook' });

    await user.click(await screen.findByRole('button', { name: 'Edit cluster_a' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit term example_cluster:cluster_a' });
    const label = await within(dialog).findByRole('textbox', { name: /Label \(EN\)/ });

    const code = within(dialog).getByRole('textbox', { name: 'Code' });
    expect(code).toHaveValue('cluster_a');
    expect(code).toHaveAttribute('readonly');
    const vocabulary = within(dialog).getByRole('textbox', { name: 'Vocabulary' });
    expect(vocabulary).toHaveValue('example_cluster');
    expect(vocabulary).toHaveAttribute('readonly');
    // JSON attributes are not edited generically; nothing changed yet.
    expect(within(dialog).queryByRole('textbox', { name: 'Attributes' })).toBeNull();
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled();

    await user.clear(label);
    await user.type(label, 'Example cluster A, revised');
    // A colleague's save refetches the term; the form keeps its base and values.
    items.voc_a = termItem(CLUSTER_A, 'example_cluster', 4, { definition: 'Changed elsewhere' });
    await queryClient.invalidateQueries({ queryKey: ['item'] });
    await user.type(within(dialog).getByRole('textbox', { name: /Change note/ }), 'Example note');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(patchBodies(fetchMock, 'voc_a')).toEqual([
        { expected_version: 3, changes: { label_en: 'Example cluster A, revised' }, note: 'Example note' },
      ]);
    });
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
  });

  it('deactivates with the version shown when the dialog opened, also after a refetch', async () => {
    const fetchMock = mockCodebookApi();
    const { user, queryClient } = renderRoute(CodebookPage, { url: '/codebook?vocabulary=example_cluster', path: '/codebook' });

    await user.click(await screen.findByRole('button', { name: 'Deactivate cluster_b' }));
    const dialog = await screen.findByRole('dialog', { name: 'Deactivate example_cluster:cluster_b' });
    // A colleague edits the term meanwhile; the vocabularies are refetched with version 4.
    vocabularies = VOCABULARIES.map((vocabulary) => ({
      ...vocabulary,
      terms: vocabulary.terms.map((candidate) =>
        candidate.id === CLUSTER_B.id ? { ...candidate, version: 4, definition: 'Changed elsewhere' } : candidate,
      ),
    }));
    await queryClient.invalidateQueries({ queryKey: ['vocab'] });
    await waitFor(() => {
      expect(requestsTo(fetchMock, '/api/vocab')).toHaveLength(2);
    });
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }));

    // Version 3 was shown when the dialog opened: the server answers with the
    // confirmation listing the colleague's revision instead of a silent write.
    await waitFor(() => {
      expect(patchBodies(fetchMock, 'voc_b')).toEqual([{ expected_version: 3, changes: { active: false }, note: null }]);
    });
  });

  it('compares any two versions of a term and restores one after a dry run (assignment §6)', async () => {
    const fetchMock = mockCodebookApi();
    const { user } = renderRoute(CodebookPage, { url: '/codebook?vocabulary=example_cluster', path: '/codebook' });

    await user.click(await screen.findByRole('button', { name: 'History of cluster_a' }));
    const dialog = await screen.findByRole('dialog', { name: 'History of example_cluster:cluster_a' });
    expect(await within(dialog).findByText('Changes of version 3')).toBeInTheDocument();

    // Compare mode: pick versions 1 and 3.
    await user.click(within(dialog).getByRole('switch', { name: 'Compare two versions' }));
    await user.click(within(dialog).getByRole('checkbox', { name: 'Compare version 3' }));
    await user.click(within(dialog).getByRole('checkbox', { name: 'Compare version 1' }));
    expect(await within(dialog).findByText('Changes from v1 to v3')).toBeInTheDocument();
    // The word diff of the definition (old → new).
    await waitFor(() => {
      expect(dialog).toHaveTextContent(/Original/);
    });
    expect(requestsTo(fetchMock, '/api/entities/vocabulary_term/voc_a/diff').map((url) => url.search)).toEqual([
      '?from=1&to=3',
    ]);

    // Restore version 1: the current version cannot be restored, the others can.
    expect(within(dialog).getByRole('button', { name: 'Restore version 3' })).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: 'Restore version 1' }));
    const panel = await within(dialog).findByRole('region', { name: 'Restore version 1' });
    expect(await within(panel).findByRole('checkbox', { name: 'Restore Definition' })).toBeChecked();
    await user.type(within(panel).getByRole('textbox', { name: /Note/ }), 'Back to the original definition');
    await user.click(within(panel).getByRole('button', { name: 'Restore' }));

    await waitFor(() => {
      expect(
        callsTo(fetchMock, '/api/entities/vocabulary_term/voc_a/restore').map((call) => jsonBody(call.init)),
      ).toEqual([
        { expected_version: 3, version: 1, dry_run: true },
        {
          expected_version: 3,
          version: 1,
          fields: ['definition'],
          note: 'Back to the original definition',
          dry_run: false,
        },
      ]);
    });
    await waitFor(() => {
      expect(within(dialog).queryByRole('region', { name: 'Restore version 1' })).toBeNull();
    });
  });

  it('offers the counts_as_modification switch for event types and warns about recomputation', async () => {
    const fetchMock = mockCodebookApi();
    const { user } = renderRoute(CodebookPage, { url: '/codebook?vocabulary=event_type', path: '/codebook' });

    // Fixed codes cannot be deactivated.
    expect(await screen.findByRole('button', { name: 'Deactivate example_fixed' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Deactivate example_change' })).toBeEnabled();

    await user.click(screen.getByRole('button', { name: 'Edit example_change' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit term event_type:example_change' });
    const toggle = await within(dialog).findByRole('switch', { name: /Counts as modification/ });
    expect(toggle).toBeChecked();
    expect(within(dialog).queryByText('Derived values will be recomputed')).toBeNull();

    await user.click(toggle);
    expect(within(dialog).getByText('Derived values will be recomputed')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(patchBodies(fetchMock, 'voc_mod')).toEqual([
        { expected_version: 5, changes: { attributes: { counts_as_modification: false } }, note: null },
      ]);
    });
  });

  it('disables adding terms to a fixed vocabulary and opens the comments panel of a term', async () => {
    const fetchMock = mockCodebookApi();
    const { router, user } = renderRoute(CodebookPage, { url: '/codebook?vocabulary=example_status', path: '/codebook' });

    expect(await screen.findByRole('button', { name: 'Add term' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Deactivate status_a' })).toBeDisabled();

    await user.click(screen.getByRole('link', { name: /Example clusters/ }));
    await user.click(await screen.findByRole('button', { name: 'Comments on cluster_b (0 open)' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ vocabulary: 'example_cluster', term: 'voc_b', comments: 'open' });
    });
    const panel = await screen.findByRole('complementary', { name: 'Comments on example_cluster:cluster_b' });
    expect(await within(panel).findByText('No comments with these filters.')).toBeInTheDocument();
    expect(requestsTo(fetchMock, '/api/comments').map((url) => Object.fromEntries(url.searchParams))).toEqual([
      { subject_id: 'voc_b', status: 'open' },
    ]);

    await user.click(within(panel).getByRole('button', { name: 'Close the comments panel' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ vocabulary: 'example_cluster' });
    });
  });

  it('adds a term to the vocabulary of the page and checks the code format first', async () => {
    const fetchMock = mockCodebookApi();
    const { user } = renderRoute(CodebookPage, { url: '/codebook?vocabulary=example_cluster', path: '/codebook' });

    await user.click(await screen.findByRole('button', { name: 'Add term' }));
    const dialog = await screen.findByRole('dialog', { name: 'Add a term to Example clusters' });
    expect(within(dialog).getByRole('textbox', { name: 'Vocabulary' })).toHaveAttribute('readonly');
    await user.type(within(dialog).getByRole('textbox', { name: /Code/ }), 'Cluster C');
    await user.type(within(dialog).getByRole('textbox', { name: /Label \(EN\)/ }), 'Example cluster C');
    await user.click(within(dialog).getByRole('button', { name: 'Add term' }));
    const code = within(dialog).getByRole('textbox', { name: /Code/ });
    expect(code).toHaveAttribute('aria-invalid', 'true');
    expect(within(dialog).getByText('Use only lowercase letters, digits and underscores.')).toBeInTheDocument();
    expect(callsTo(fetchMock, '/api/entities/vocabulary_term')).toHaveLength(0);

    await user.clear(code);
    await user.type(code, 'cluster_c');
    await user.click(within(dialog).getByRole('button', { name: 'Add term' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
    const posts = callsTo(fetchMock, '/api/entities/vocabulary_term').filter((call) => call.init?.method === 'POST');
    expect(posts.map((call) => jsonBody(call.init))).toEqual([
      { data: { code: 'cluster_c', label_en: 'Example cluster C', vocabulary: 'example_cluster' }, note: null },
    ]);
  });
});
