import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { ChangeFeedItem, StatsResponse } from '../api/types';
import { callsTo, jsonBody, mockApi, requestsTo } from '../test/api-mock';
import { exampleItem, exampleMeta, listResponse } from '../test/fixtures';
import { renderRoute } from '../test/render';
import { TrashPage } from './TrashPage';

const DELETED_AT = '2026-10-28T10:00:00.000000Z';

const deletedProject = exampleItem(
  'prj_A',
  { name_en: 'Example project A' },
  { version: 4, deleted_at: DELETED_AT, deleted_by: 'user' },
);

const deletion = (id: number, entityId: string): ChangeFeedItem => ({
  id,
  entity_type: entityId.startsWith('svc') ? 'service' : 'project',
  entity_id: entityId,
  entity_label: entityId,
  version: 4,
  at: DELETED_AT,
  author: 'user',
  channel: 'ui',
  action: 'delete',
  note: 'Example duplicate',
  changed_fields: ['deleted'],
  restored_from_version: null,
  batch_id: 'batch_1',
  context: null,
});

const STATS: StatsResponse = { entities: { project: { total: 19, unverified: 0, deleted: 1 } }, open_comments: 0 };

/** Undelete responses in request order: a Response (an error) or undefined (success). */
let undeleteResponses: (Response | undefined)[] = [];

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
  it('lists deleted rows newest first with their cascade and undeletes them together', async () => {
    undeleteResponses = [];
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
    expect(jsonBody(call?.init)).toEqual({ note: 'Example reason', cascade: true });
  });

  it('explains a refused undelete and keeps the dialog open', async () => {
    undeleteResponses = [
      new Response(
        JSON.stringify({
          error: {
            code: 'unique_violation',
            message: 'The value is already used.',
            details: { field: 'name_en', existing: { id: 'prj_B', label: 'Example project B', deleted: false } },
          },
        }),
        { status: 409, headers: { 'Content-Type': 'application/json' } },
      ),
    ];
    mockTrashApi();
    const { user } = renderRoute(TrashPage, { url: '/trash?type=project', path: '/trash' });

    await user.click(await screen.findByRole('button', { name: 'Undelete Example project A' }));
    const dialog = await screen.findByRole('dialog', { name: 'Undelete record' });
    await user.click(within(dialog).getByRole('button', { name: 'Undelete' }));

    const alert = await within(dialog).findByRole('alert', { name: 'The record was not undeleted' });
    expect(alert).toHaveTextContent('is already used by Example project B');
  });
});
