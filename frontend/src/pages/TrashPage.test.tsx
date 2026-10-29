import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import type { ChangeFeedItem, ConflictPayload, StatsResponse } from '../api/types';
import { AUTHOR_STORAGE_KEY } from '../lib/author';
import { callsTo, jsonBody, mockApi, requestsTo } from '../test/api-mock';
import { exampleItem, exampleMeta, listResponse } from '../test/fixtures';
import { renderRoute } from '../test/render';
import { TrashPage } from './TrashPage';

const DELETED_AT = '2026-10-28T10:00:00.000000Z';

const deletedProject = exampleItem(
  'prj_A',
  { name_en: 'Example project A' },
  { version: 4, deleted_at: DELETED_AT, deleted_by: 'Example Person' },
);

const deletion = (id: number, entityId: string): ChangeFeedItem => ({
  id,
  entity_type: entityId.startsWith('svc') ? 'service' : 'project',
  entity_id: entityId,
  entity_label: entityId,
  version: 4,
  at: DELETED_AT,
  author: 'Example Person',
  channel: 'ui',
  action: 'delete',
  note: 'Example duplicate',
  changed_fields: ['deleted'],
  restored_from_version: null,
  batch_id: 'batch_1',
  context: null,
});

const STATS: StatsResponse = { entities: { project: { total: 19, unverified: 0, deleted: 1 } }, open_comments: 0 };

const conflict: ConflictPayload = {
  action: 'undelete',
  entity_type: 'project',
  entity_id: 'prj_A',
  base_version: 4,
  current_version: 6,
  base: null,
  current: {},
  base_state: null,
  current_state: { deleted_at: DELETED_AT, deleted_by: 'Another Person' },
  changed_since_base: [],
  your_changes: {},
  conflicting_fields: [],
  meta_changed_since_base: {},
  intervening: [
    {
      id: 40,
      version: 6,
      at: '2026-10-28T11:00:00.000000Z',
      author: 'Another Person',
      channel: 'ui',
      action: 'delete',
      note: 'Example second deletion',
      changed_fields: ['deleted'],
      restored_from: null,
      restored_from_version: null,
      batch_id: 'batch_2',
    },
  ],
  refs: {},
};

const conflictResponse = () =>
  new Response(JSON.stringify({ error: { code: 'conflict', message: 'Changed in the meantime', details: conflict } }), {
    status: 409,
    headers: { 'Content-Type': 'application/json' },
  });

/** Undelete responses in request order: a Response (an error) or undefined (success). */
let undeleteResponses: (Response | undefined)[];

function mockTrashApi() {
  return mockApi((url, init) => {
    if (url.pathname === '/api/meta') return exampleMeta;
    if (url.pathname === '/api/stats') return STATS;
    if (url.pathname === '/api/entities/project') return listResponse([deletedProject]);
    if (url.pathname === '/api/revisions') {
      return { items: [deletion(31, 'svc_2'), deletion(30, 'svc_1'), deletion(29, 'prj_A')], total: 3, page: 1, page_size: 500 };
    }
    if (url.pathname === '/api/entities/project/prj_A/undelete' && init?.method === 'POST') {
      return undeleteResponses.shift() ?? { item: { ...deletedProject, deleted_at: null }, revision_id: 41, batch_id: 'batch_3' };
    }
    return undefined;
  });
}

describe('Trash', () => {
  beforeEach(() => {
    window.localStorage.setItem(AUTHOR_STORAGE_KEY, 'Example Person');
    undeleteResponses = [];
  });

  it('lists deleted rows newest first with their cascade and undeletes with the expected version', async () => {
    const fetchMock = mockTrashApi();
    const { user } = renderRoute(TrashPage, { url: '/trash?type=project', path: '/trash' });

    const cells = within(await screen.findByRole('row', { name: /Example project A/ }));
    expect(await cells.findByText('with 2 others')).toBeInTheDocument();
    expect(cells.getByText('Example duplicate')).toBeInTheDocument();
    expect(Object.fromEntries(requestsTo(fetchMock, '/api/entities/project')[0]?.searchParams ?? [])).toEqual({
      deleted: 'only',
      sort: '-deleted_at',
    });

    await user.click(cells.getByRole('button', { name: 'Undelete Example project A' }));
    const dialog = await screen.findByRole('dialog', { name: 'Undelete record' });
    expect(within(dialog).getByRole('checkbox', { name: 'Also undelete the 2 records deleted together with it' })).toBeChecked();
    await user.type(within(dialog).getByRole('textbox', { name: /Note/ }), 'Example reason');
    await user.click(within(dialog).getByRole('button', { name: 'Undelete' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Undelete record' })).toBeNull();
    });
    const [call] = callsTo(fetchMock, '/api/entities/project/prj_A/undelete');
    expect(jsonBody(call?.init)).toEqual({ expected_version: 4, note: 'Example reason', cascade: true });
    expect(new Headers(call?.init?.headers).get('X-Author')).toBe('Example%20Person');
  });

  it('asks again after a conflict and resends with the current version only on confirm', async () => {
    const fetchMock = mockTrashApi();
    undeleteResponses = [conflictResponse()];
    const { user } = renderRoute(TrashPage, { url: '/trash?type=project', path: '/trash' });

    await user.click(await screen.findByRole('button', { name: 'Undelete Example project A' }));
    const dialog = await screen.findByRole('dialog', { name: 'Undelete record' });
    await user.click(within(dialog).getByRole('checkbox', { name: /Also undelete/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Undelete' }));

    expect(await within(dialog).findByText('Changed since you opened this dialog')).toBeInTheDocument();
    expect(within(dialog).getByText('Another Person')).toBeInTheDocument();
    expect(within(dialog).getByText('Example second deletion')).toBeInTheDocument();
    expect(callsTo(fetchMock, '/api/entities/project/prj_A/undelete')).toHaveLength(1);

    await user.click(within(dialog).getByRole('button', { name: 'Undelete anyway' }));
    await waitFor(() => {
      expect(callsTo(fetchMock, '/api/entities/project/prj_A/undelete')).toHaveLength(2);
    });
    const bodies = callsTo(fetchMock, '/api/entities/project/prj_A/undelete').map((call) => jsonBody(call.init));
    expect(bodies).toEqual([
      { expected_version: 4, note: null, cascade: false },
      { expected_version: 6, note: null, cascade: false },
    ]);
  });
});
