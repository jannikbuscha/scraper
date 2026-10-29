import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import type { Comment, ConflictPayload, EntityTypeMeta, Item, JsonObject, Meta, RevisionSummary } from '../api/types';
import { AUTHOR_STORAGE_KEY } from '../lib/author';
import { callsTo, jsonBody, mockApi } from '../test/api-mock';
import { exampleItem, exampleVocabularies, fieldSpec, listResponse } from '../test/fixtures';
import { renderRoute } from '../test/render';
import { EntityDetailPage } from './EntityDetailPage';

// Synthetic metadata and values; nothing here describes the real portfolio.
const projectMeta: EntityTypeMeta = {
  label: 'Project',
  label_plural: 'Projects',
  prefix: 'prj',
  table_view: true,
  default_sort: 'name_en',
  constraints: [{ one_of_required: ['name_en', 'name_uk'] }],
  fields: [
    fieldSpec('name_en', 'string', { label: 'Name (EN)' }),
    fieldSpec('name_uk', 'string', { label: 'Name (UK)' }),
    fieldSpec('description_en', 'text', { label: 'Description (EN)' }),
    fieldSpec('verification_status', 'vocab', {
      label: 'Verification status',
      vocabulary: 'verification_status',
      required: true,
      default: 'unverified',
    }),
    fieldSpec('period', 'vocab', {
      label: 'Period',
      vocabulary: 'example_period',
      group: 'wartime',
      editable: false,
      derived: true,
    }),
    fieldSpec('notes', 'text', { label: 'Notes', group: 'sources' }),
    fieldSpec('updated_by', 'string', { label: 'Updated by', group: 'system', editable: false, system: true }),
  ],
  quick_filters: [],
};

const meta: Meta = {
  app_version: '0.0.0-test',
  team_members: [],
  focal_org_id: null,
  parameters: { ministry_founded: '2000-01-01', full_scale_invasion: '2001-01-01' },
  limits: {
    max_comment_chars: 10000,
    max_note_chars: 2000,
    max_page_size: 500,
    max_bulk_items: 500,
    max_export_rows: 1000,
  },
  groups: [
    { key: 'basics', label: 'Basics' },
    { key: 'wartime', label: 'Wartime' },
    { key: 'sources', label: 'Sources & Evidence' },
    { key: 'system', label: 'System' },
  ],
  vocabularies: {},
  entity_types: {
    project: projectMeta,
    service: { ...projectMeta, label: 'Service', label_plural: 'Services', prefix: 'svc', fields: [] },
  },
};

const ID = 'prj_EXAMPLE';
const ITEM_PATH = `/api/entities/project/${ID}`;

const baseFields: JsonObject = {
  name_en: 'Example project',
  name_uk: null,
  description_en: 'An example description.',
  verification_status: 'unverified',
  notes: null,
};

/** The record on the "server"; tests change it to simulate a colleague. */
let server: { fields: JsonObject; version: number; updatedBy: string; deletedAt?: string };
/** Queued responses per request path (writes); without one, a write succeeds. */
let responses: Record<string, (() => Response)[]>;

function serverItem(): Item {
  return exampleItem(ID, server.fields, {
    version: server.version,
    updated_by: server.updatedBy,
    updated_at: '2026-01-02T09:30:00.000000Z',
    field_meta: {
      name_en: {
        src: 'seed',
        by: 'seed',
        at: '2026-01-01T00:00:00.000000Z',
        locked: true,
        verified: 'unverified',
        evidence_id: null,
        restored_from_version: null,
      },
    },
    virtual: { open_comments: 0, comment_count: 0, open_comments_by_field: { name_en: 2 } },
    deleted_at: server.deletedAt ?? null,
    deleted_by: server.deletedAt ? 'Example Colleague' : null,
  });
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const queue = (path: string, respond: () => Response) => {
  (responses[path] ??= []).push(respond);
};

const revision = (version: number, author: string, changed: string[]): RevisionSummary => ({
  id: version * 10,
  version,
  at: `2026-01-0${version}T09:30:00.000000Z`,
  author,
  channel: 'ui',
  action: 'update',
  note: `Example note ${version}`,
  changed_fields: changed,
  restored_from: null,
  restored_from_version: null,
  batch_id: null,
});

function conflictResponse(payload: Partial<ConflictPayload> & Pick<ConflictPayload, 'current'>): Response {
  const full: ConflictPayload = {
    action: 'patch',
    entity_type: 'project',
    entity_id: ID,
    base_version: 3,
    current_version: 4,
    base: baseFields,
    base_state: { deleted_at: null, deleted_by: null },
    current_state: { deleted_at: null, deleted_by: null },
    changed_since_base: [],
    your_changes: {},
    conflicting_fields: [],
    meta_changed_since_base: {},
    intervening: [revision(4, 'Example Colleague', ['name_en'])],
    refs: {},
    ...payload,
  };
  return json({ error: { code: 'conflict', message: 'The record was changed.', details: full } }, 409);
}

const exampleComment = (overrides: Partial<Comment>): Comment => ({
  id: 'cmt_EXAMPLE',
  subject_id: ID,
  subject_type: 'project',
  subject_label: 'Example project',
  field: null,
  parent_id: null,
  body_md: 'Example comment',
  body_html: '<p>Example comment</p>',
  status: 'open',
  resolved_by: null,
  resolved_at: null,
  created_at: '2026-01-02T10:00:00.000000Z',
  created_by: 'Example Person',
  updated_at: '2026-01-02T10:00:00.000000Z',
  updated_by: 'Example Person',
  version: 1,
  edited: false,
  deleted_at: null,
  deleted_by: null,
  ...overrides,
});

const evidenceRow = exampleItem(
  'evd_EXAMPLE',
  { subject_id: ID, target: 'field:name_en', url: 'https://example.org/source', quote: 'An example quote' },
  { type: 'evidence', label: 'Name (EN) · Example project' },
);

function mockDetailApi() {
  return mockApi((url, init) => {
    const queued = init?.method && init.method !== 'GET' ? responses[url.pathname]?.shift() : undefined;
    if (queued) return queued();
    if (url.pathname === '/api/meta') return meta;
    if (url.pathname === ITEM_PATH) {
      if (init?.method === 'PATCH') {
        // The tests assert the request bodies; the stored values need not follow.
        server = { ...server, version: server.version + 1, updatedBy: 'Example Person' };
        return { item: serverItem(), changed: true, revision_id: 100, warnings: [] };
      }
      return { item: serverItem() };
    }
    if (url.pathname === `${ITEM_PATH}/verify-field`) {
      server = { ...server, version: server.version + 1 };
      return { item: serverItem(), revision_id: 101 };
    }
    if (url.pathname === `${ITEM_PATH}/delete`) {
      server = { ...server, version: server.version + 1, deletedAt: '2026-01-03T08:00:00.000000Z' };
      return { item: serverItem(), revision_id: 102, batch_id: 'batch_EXAMPLE' };
    }
    if (url.pathname === `${ITEM_PATH}/undelete`) {
      server = { fields: server.fields, version: server.version + 1, updatedBy: 'Example Person' };
      return { item: serverItem(), revision_id: 103, batch_id: 'batch_UNDELETE' };
    }
    if (url.pathname === `${ITEM_PATH}/revisions`) {
      const deletion = server.deletedAt
        ? [{ ...revision(4, 'Example Colleague', ['deleted']), action: 'delete' as const, batch_id: 'batch_EXAMPLE' }]
        : [];
      const items = [
        ...deletion,
        revision(3, 'Example Person', ['notes']),
        revision(2, 'Example Colleague', ['name_en']),
      ];
      return { items, total: items.length, page: 1, page_size: 50, refs: {} };
    }
    // The change feed of one batch: this record and two services deleted with it.
    if (url.pathname === '/api/revisions' && url.searchParams.get('batch_id') === 'batch_EXAMPLE') {
      return { items: [], total: 3, page: 1, page_size: 1 };
    }
    if (url.pathname === '/api/comments') {
      if (init?.method === 'POST') return json({ comment: exampleComment({ id: 'cmt_NEW' }) }, 201);
      return { threads: [{ root: exampleComment({}), replies: [] }] };
    }
    if (url.pathname === '/api/entities/evidence') {
      return listResponse(url.searchParams.get('f.target') === 'eq:field:name_en' ? [evidenceRow] : []);
    }
    // Related panels: no related records.
    if (/^\/api\/entities\/[a-z_]+$/.test(url.pathname)) return listResponse([]);
    return undefined;
  });
}

const DetailPage = () => <EntityDetailPage type="project" id={ID} />;

function renderDetail(url = `/projects/${ID}`) {
  return renderRoute(DetailPage, { url, path: '/projects/$id', vocabularies: exampleVocabularies });
}

type FetchMock = ReturnType<typeof mockDetailApi>;

const bodiesTo = (fetchMock: FetchMock, path: string, method = 'POST'): unknown[] =>
  callsTo(fetchMock, path)
    .filter((call) => call.init?.method === method)
    .map((call) => jsonBody(call.init));

const patchBodies = (fetchMock: FetchMock) => bodiesTo(fetchMock, ITEM_PATH, 'PATCH');

async function startEditing(user: ReturnType<typeof renderDetail>['user']) {
  await user.click(await screen.findByRole('button', { name: 'Edit' }));
  return screen.findByRole('region', { name: 'Save changes' });
}

beforeEach(() => {
  window.localStorage.setItem(AUTHOR_STORAGE_KEY, 'Example Person');
  server = { fields: { ...baseFields }, version: 3, updatedBy: 'Example Person' };
  responses = {};
});

describe('entity detail page: editing', () => {
  it('sends only the changed fields with the version captured when editing started', async () => {
    const fetchMock = mockDetailApi();
    const { user, router } = renderDetail();
    await startEditing(user);
    expect(router.state.location.search).toEqual({ edit: '1' });

    await user.type(screen.getByRole('textbox', { name: 'Name (UK)' }), 'Приклад');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(router.state.location.search).toEqual({});
    });
    expect(patchBodies(fetchMock)).toEqual([{ expected_version: 3, changes: { name_uk: 'Приклад' }, note: null }]);
  });

  it('keeps the frozen base through a refetch and resolves the conflict against the current version', async () => {
    const fetchMock = mockDetailApi();
    const { user, queryClient } = renderDetail();
    await startEditing(user);
    await user.type(screen.getByRole('textbox', { name: 'Name (UK)' }), 'Приклад');

    // A colleague renames the project; a background refetch brings version 4.
    server = {
      fields: { ...server.fields, name_en: 'Renamed by a colleague' },
      version: 4,
      updatedBy: 'Example Colleague',
    };
    await queryClient.invalidateQueries({ queryKey: ['item'] });
    expect(await screen.findByText(/saving will open the conflict dialog/)).toBeInTheDocument();
    // Neither the base nor the form values follow the refetch.
    expect(screen.getByRole('textbox', { name: 'Name (EN)' })).toHaveValue('Example project');
    expect(screen.getByRole('textbox', { name: 'Name (UK)' })).toHaveValue('Приклад');

    queue(ITEM_PATH, () =>
      conflictResponse({
        current: { ...baseFields, name_en: 'Renamed by a colleague' },
        changed_since_base: ['name_en'],
        your_changes: { name_uk: 'Приклад' },
      }),
    );
    await user.click(screen.getByRole('button', { name: 'Save' }));

    const dialog = await screen.findByRole('dialog', { name: 'Your changes conflict with a newer version' });
    expect(within(dialog).getByText('Example Colleague')).toBeInTheDocument();
    expect(within(dialog).getByText('Changed only by you — will be applied')).toBeInTheDocument();
    expect(within(dialog).getByText('Changed only by them — kept')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Apply' }));

    await waitFor(() => {
      expect(patchBodies(fetchMock)).toHaveLength(2);
    });
    expect(patchBodies(fetchMock)).toEqual([
      // The first save: unchanged by the refetch.
      { expected_version: 3, changes: { name_uk: 'Приклад' }, note: null },
      // Re-sent against the current version with only your change: their name survives.
      { expected_version: 4, changes: { name_uk: 'Приклад' }, note: null },
    ]);
    await waitFor(() => {
      expect(screen.queryByRole('region', { name: 'Save changes' })).toBeNull();
    });
  });

  it('requires a choice per conflicting field, sends a merged value and shows a further conflict again', async () => {
    const fetchMock = mockDetailApi();
    const { user, router } = renderDetail();
    await startEditing(user);
    const description = screen.getByRole('textbox', { name: 'Description (EN)' });
    await user.clear(description);
    await user.type(description, 'My description.');
    await user.type(screen.getByRole('textbox', { name: 'Change note (optional)' }), 'Example note');

    queue(ITEM_PATH, () =>
      conflictResponse({
        current: { ...baseFields, description_en: 'Their description.' },
        changed_since_base: ['description_en'],
        conflicting_fields: ['description_en'],
        your_changes: { description_en: 'My description.' },
      }),
    );
    await user.click(screen.getByRole('button', { name: 'Save' }));
    let dialog = await screen.findByRole('dialog', { name: 'Your changes conflict with a newer version' });

    // Nothing is saved without a choice.
    expect(within(dialog).getByRole('button', { name: 'Apply' })).toBeDisabled();
    await user.click(within(dialog).getByRole('radio', { name: 'Edit merged value' }));
    const merged = within(dialog).getByRole('textbox', { name: 'Merged value' });
    expect(merged).toHaveValue('My description.');
    await user.clear(merged);
    await user.type(merged, 'Their description, merged with mine.');

    // The re-sent PATCH meets yet another change (version 5).
    queue(ITEM_PATH, () =>
      conflictResponse({
        base_version: 4,
        current_version: 5,
        base: { ...baseFields, description_en: 'Their description.' },
        current: { ...baseFields, description_en: 'A third description.' },
        changed_since_base: ['description_en'],
        conflicting_fields: ['description_en'],
        your_changes: { description_en: 'Their description, merged with mine.' },
      }),
    );
    await user.click(within(dialog).getByRole('button', { name: 'Apply' }));

    await waitFor(() => {
      expect(patchBodies(fetchMock)).toHaveLength(2);
    });
    expect(patchBodies(fetchMock)[1]).toEqual({
      expected_version: 4,
      changes: { description_en: 'Their description, merged with mine.' },
      note: 'Example note',
    });

    // The dialog shows again for the newer version; keeping theirs leaves nothing to save.
    dialog = await screen.findByRole('dialog', { name: 'Your changes conflict with a newer version' });
    expect(within(dialog).getByText(/changed to version 5/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('radio', { name: 'Keep theirs' }));
    await user.click(within(dialog).getByRole('button', { name: 'Apply' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({});
    });
    expect(patchBodies(fetchMock)).toHaveLength(2);
  });

  it('asks before leaving edit mode with unsaved changes', async () => {
    mockDetailApi();
    const { user, router } = renderDetail();
    await startEditing(user);
    await user.type(screen.getByRole('textbox', { name: 'Notes' }), 'Unsaved example note');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    const prompt = await screen.findByRole('dialog', { name: 'Discard unsaved changes?' });
    await user.click(within(prompt).getByRole('button', { name: 'Keep editing' }));
    expect(router.state.location.search).toEqual({ edit: '1' });
    expect(screen.getByRole('textbox', { name: 'Notes' })).toHaveValue('Unsaved example note');

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await user.click(
      within(await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })).getByRole('button', {
        name: 'Discard changes',
      }),
    );
    await waitFor(() => {
      expect(router.state.location.search).toEqual({});
    });
  });
});

describe('entity detail page: verification, comments, history', () => {
  it('verifies a field with its evidence and retries once when only other fields changed', async () => {
    const fetchMock = mockDetailApi();
    const { user } = renderDetail();
    await user.click(await screen.findByRole('button', { name: /^Verification of Name \(EN\)/ }));
    queue(`${ITEM_PATH}/verify-field`, () =>
      conflictResponse({
        action: 'verify',
        current: { ...baseFields, notes: 'Changed by a colleague' },
        changed_since_base: ['notes'],
        intervening: [revision(4, 'Example Colleague', ['notes'])],
      }),
    );
    await user.click(await screen.findByRole('menuitem', { name: /An example quote/ }));

    await waitFor(() => {
      expect(bodiesTo(fetchMock, `${ITEM_PATH}/verify-field`)).toHaveLength(2);
    });
    expect(bodiesTo(fetchMock, `${ITEM_PATH}/verify-field`)).toEqual([
      { expected_version: 3, field: 'name_en', status: 'verified', evidence_id: 'evd_EXAMPLE', note: null },
      { expected_version: 4, field: 'name_en', status: 'verified', evidence_id: 'evd_EXAMPLE', note: null },
    ]);
    expect(requestedEvidence(fetchMock)).toContain('eq:field:name_en');
  });

  it('asks instead of retrying when a colleague disputed the field meanwhile, showing the reason', async () => {
    const fetchMock = mockDetailApi();
    const { user } = renderDetail();
    await user.click(await screen.findByRole('button', { name: /^Verification of Name \(EN\)/ }));
    // The value is unchanged, but a colleague disputed it (a verify revision with a note).
    queue(`${ITEM_PATH}/verify-field`, () =>
      conflictResponse({
        action: 'verify',
        current: baseFields,
        meta_changed_since_base: { name_en: { verified: ['unverified', 'disputed'] } },
        intervening: [
          { ...revision(4, 'Example Colleague', ['name_en']), action: 'verify', note: 'Example reason: outdated name' },
        ],
      }),
    );
    await user.click(await screen.findByRole('menuitem', { name: /An example quote/ }));

    const dialog = await screen.findByRole('dialog', { name: 'The record changed meanwhile' });
    expect(within(dialog).getByText(/The verification of/)).toHaveTextContent(
      'The verification of Name (EN) was changed by Example Colleague',
    );
    expect(within(dialog).getByText('Disputed')).toBeInTheDocument();
    expect(within(dialog).getByText('Example reason: outdated name')).toBeInTheDocument();
    // Nothing was retried blindly.
    expect(bodiesTo(fetchMock, `${ITEM_PATH}/verify-field`)).toHaveLength(1);

    await user.click(within(dialog).getByRole('button', { name: 'Mark verified' }));
    await waitFor(() => {
      expect(bodiesTo(fetchMock, `${ITEM_PATH}/verify-field`)).toHaveLength(2);
    });
    expect(bodiesTo(fetchMock, `${ITEM_PATH}/verify-field`)[1]).toEqual({
      expected_version: 4,
      field: 'name_en',
      status: 'verified',
      evidence_id: 'evd_EXAMPLE',
      note: null,
    });
  });

  it('verifies with the version shown when the menu opened, so a value changed meanwhile is asked about', async () => {
    const fetchMock = mockDetailApi();
    const { user, queryClient } = renderDetail();
    await user.click(await screen.findByRole('button', { name: /^Verification of Name \(EN\)/ }));
    const evidence = await screen.findByRole('menuitem', { name: /An example quote/ });

    // While the menu is open, a background refetch brings a colleague's rename (version 4).
    server = { fields: { ...server.fields, name_en: 'Renamed by a colleague' }, version: 4, updatedBy: 'Example Colleague' };
    await queryClient.invalidateQueries({ queryKey: ['item'] });
    await waitFor(() => {
      expect(screen.getAllByText('Renamed by a colleague').length).toBeGreaterThan(0);
    });
    queue(`${ITEM_PATH}/verify-field`, () =>
      conflictResponse({
        action: 'verify',
        current: { ...baseFields, name_en: 'Renamed by a colleague' },
        changed_since_base: ['name_en'],
        intervening: [revision(4, 'Example Colleague', ['name_en'])],
      }),
    );
    await user.click(evidence);

    const dialog = await screen.findByRole('dialog', { name: 'The record changed meanwhile' });
    expect(within(dialog).getByText('Mark the new value verified?')).toBeInTheDocument();
    expect(within(dialog).getByText('Renamed by a colleague')).toBeInTheDocument();
    expect(bodiesTo(fetchMock, `${ITEM_PATH}/verify-field`)).toEqual([
      { expected_version: 3, field: 'name_en', status: 'verified', evidence_id: 'evd_EXAMPLE', note: null },
    ]);
  });

  it('disputes with the version and value shown when the menu opened', async () => {
    const fetchMock = mockDetailApi();
    const { user, queryClient } = renderDetail();
    await user.click(await screen.findByRole('button', { name: /^Verification of Name \(EN\)/ }));
    await user.click(await screen.findByRole('menuitem', { name: 'Disputed…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Dispute · Name (EN)' });
    expect(within(dialog).getByRole('group', { name: 'The disputed value' })).toHaveTextContent('Example project');

    // A refetch while the reason is typed: the dialog keeps the value it was opened for.
    server = { fields: { ...server.fields, name_en: 'Renamed by a colleague' }, version: 4, updatedBy: 'Example Colleague' };
    await queryClient.invalidateQueries({ queryKey: ['item'] });
    await waitFor(() => {
      expect(screen.getAllByText('Renamed by a colleague').length).toBeGreaterThan(0);
    });
    expect(within(dialog).getByRole('group', { name: 'The disputed value' })).toHaveTextContent('Example project');
    await user.type(within(dialog).getByRole('textbox', { name: /Note/ }), 'Example reason');
    await user.click(within(dialog).getByRole('button', { name: 'Mark disputed' }));

    await waitFor(() => {
      expect(bodiesTo(fetchMock, `${ITEM_PATH}/verify-field`)).toEqual([
        { expected_version: 3, field: 'name_en', status: 'disputed', evidence_id: null, note: 'Example reason' },
      ]);
    });
  });

  it('opens the comments panel for a field and posts a comment about it', async () => {
    const fetchMock = mockDetailApi();
    const { user, router } = renderDetail();
    await user.click(await screen.findByRole('button', { name: 'Comments on Name (EN) (2 open)' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ comments: 'open' });
    });
    const panel = await screen.findByRole('complementary', { name: 'Comments' });
    expect(await within(panel).findByText('Example comment')).toBeInTheDocument();
    expect(requestedComments(fetchMock)).toContainEqual({ subject_id: ID, status: 'open', field: 'name_en' });

    await user.type(within(panel).getByRole('textbox', { name: /New comment/ }), 'Is this name current?');
    await user.click(within(panel).getByRole('button', { name: 'Comment' }));
    await waitFor(() => {
      expect(bodiesTo(fetchMock, '/api/comments')).toEqual([
        { subject_id: ID, field: 'name_en', parent_id: null, body_md: 'Is this name current?' },
      ]);
    });
  });

  it('restores a version with the selected fields after a dry run', async () => {
    const fetchMock = mockDetailApi();
    const restorePath = `${ITEM_PATH}/restore`;
    queue(restorePath, () =>
      json({ changes: { name_en: ['Example project', 'Older name'], notes: ['Current note', null] } }),
    );
    const { user } = renderDetail(`/projects/${ID}?tab=history`);
    await user.click(await screen.findByRole('button', { name: 'Restore version 2' }));
    const dialog = await screen.findByRole('dialog', { name: 'Restore version 2' });
    await within(dialog).findByText('Older name');
    // Version 3 changed the notes, which this restore would undo.
    expect(within(dialog).getByText(/Undoes changes by/)).toHaveTextContent(
      'Undoes changes by: Example Person (1 revision)',
    );

    await user.click(within(dialog).getByRole('checkbox', { name: 'Restore Notes' }));
    queue(restorePath, () =>
      json({ item: serverItem(), changed: true, revision_id: 102, warnings: [], skipped_fields: [], changes: {} }),
    );
    await user.click(within(dialog).getByRole('button', { name: 'Restore' }));
    expect(within(dialog).getByText(/A note is required/)).toBeInTheDocument();
    await user.type(within(dialog).getByRole('textbox', { name: /Note/ }), 'Back to the older name');
    await user.click(within(dialog).getByRole('button', { name: 'Restore' }));

    await waitFor(() => {
      expect(bodiesTo(fetchMock, restorePath)).toHaveLength(2);
    });
    expect(bodiesTo(fetchMock, restorePath)).toEqual([
      { expected_version: 3, version: 2, dry_run: true },
      { expected_version: 3, version: 2, fields: ['name_en'], note: 'Back to the older name', dry_run: false },
    ]);
  });
});

describe('entity detail page: delete and undelete', () => {
  it('deletes with a note and asks before deleting dependent records too', async () => {
    const fetchMock = mockDetailApi();
    const deletePath = `${ITEM_PATH}/delete`;
    queue(deletePath, () =>
      json({ error: { code: 'has_dependents', message: 'The project has services.', details: { service: 2 } } }, 409),
    );
    const { user } = renderDetail();
    await user.click(await screen.findByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('dialog', { name: 'Delete record' });
    await user.type(within(dialog).getByRole('textbox', { name: 'Note (optional)' }), 'Example duplicate');
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(await within(dialog).findByText(/2 services that are not deleted belong to it/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Delete with dependents' }));

    expect(await screen.findByText('This record is deleted')).toBeInTheDocument();
    expect(bodiesTo(fetchMock, deletePath)).toEqual([
      { expected_version: 3, note: 'Example duplicate', cascade: false },
      { expected_version: 3, note: 'Example duplicate', cascade: true },
    ]);
    // A deleted record is read-only.
    expect(screen.getByRole('button', { name: 'Edit' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /^Verification of/ })).toBeNull();
  });

  it('offers to undelete the records deleted together with this one', async () => {
    const fetchMock = mockDetailApi();
    server = { ...server, version: 4, deletedAt: '2026-01-03T08:00:00.000000Z' };
    const { user } = renderDetail();
    // The banner of a deleted record offers Undelete (as does the header).
    const banner = await screen.findByRole('alert', { name: 'This record is deleted' });
    await user.click(within(banner).getByRole('button', { name: 'Undelete' }));
    const dialog = await screen.findByRole('dialog', { name: 'Undelete record' });
    // The shared undelete dialog preselects undoing a known cascade as a whole.
    const cascade = await within(dialog).findByRole('checkbox', {
      name: 'Also undelete the 2 records deleted together with it',
    });
    await waitFor(() => {
      expect(cascade).toBeChecked();
    });
    await user.click(within(dialog).getByRole('button', { name: 'Undelete' }));

    await waitFor(() => {
      expect(bodiesTo(fetchMock, `${ITEM_PATH}/undelete`)).toEqual([
        { expected_version: 4, note: null, cascade: true },
      ]);
    });
    await waitFor(() => {
      expect(screen.queryByText('This record is deleted')).toBeNull();
    });
  });
});

function requestedEvidence(fetchMock: FetchMock): string[] {
  return callsTo(fetchMock, '/api/entities/evidence').map((call) => call.url.searchParams.get('f.target') ?? '');
}

function requestedComments(fetchMock: FetchMock): Record<string, string>[] {
  return callsTo(fetchMock, '/api/comments')
    .filter((call) => call.init?.method === undefined || call.init.method === 'GET')
    .map((call) => Object.fromEntries(call.url.searchParams));
}
