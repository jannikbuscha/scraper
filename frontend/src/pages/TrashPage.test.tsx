import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { ChangeFeedItem, Meta, StatsResponse } from '../api/types';
import { callsTo, jsonBody, mockApi, requestsTo } from '../test/api-mock';
import { exampleItem, exampleMeta, fieldSpec, listResponse, projectMeta } from '../test/fixtures';
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
  run_id: null,
  proposal_id: null,
  context: null,
});

const STATS: StatsResponse = {
  entities: { project: { total: 19, unverified: 0, deleted: 1 } },
  open_comments: 0,
  open_proposals: 0,
  runs: { running: null, last_finished: null },
};

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

describe('Trash: merged records and pages past the end (docs/UI.md §5, §8.7)', () => {
  // Synthetic: a service type with a parent reference, for the unmerge result.
  const meta: Meta = {
    ...exampleMeta,
    entity_types: {
      ...exampleMeta.entity_types,
      service: {
        ...projectMeta,
        label: 'Service',
        label_plural: 'Services',
        prefix: 'svc',
        fields: [fieldSpec('name_en', 'string', { label: 'Name (EN)' }), fieldSpec('parent_service_id', 'ref', { label: 'Parent service', ref_types: ['service'] })],
      },
    },
  };
  const merged = exampleItem(
    'svc_B',
    { name_en: 'Example service B' },
    { type: 'service', version: 3, deleted_at: DELETED_AT, deleted_by: 'user', merged_into: 'svc_A' },
  );
  const LABELS: Record<string, string> = { svc_A: 'Example service A', svc_C: 'Example service C', svc_D: 'Example service D' };

  it('names the survivor of a merged record, and the references an unmerge left as they are, by their labels', async () => {
    mockApi((url, init) => {
      if (url.pathname === '/api/meta') return meta;
      if (url.pathname === '/api/stats') return STATS;
      if (url.pathname === '/api/entities/service') return listResponse([merged]);
      if (url.pathname === '/api/revisions') return { items: [], total: 0, page: 1, page_size: 500 };
      if (url.pathname === '/api/lookup') {
        const ids = (url.searchParams.get('ids') ?? '').split(',').filter((id) => id in LABELS);
        return { items: ids.map((id) => ({ id, type: 'service', label: LABELS[id], deleted: false, context: null })) };
      }
      if (url.pathname === '/api/entities/service/svc_B/unmerge' && init?.method === 'POST') {
        return {
          item: { ...merged, deleted_at: null, merged_into: null },
          merge_id: 'mrg_1',
          batch_id: 'batch_U',
          revision_ids: [5],
          skipped: [{ entity_type: 'service', id: 'svc_C', field: 'parent_service_id', current: 'svc_D' }],
        };
      }
      return undefined;
    });
    const { user } = renderRoute(TrashPage, { url: '/trash?type=service', path: '/trash' });
    const row = within(await screen.findByRole('row', { name: /Example service B/ }));
    expect(await row.findByRole('link', { name: 'Example service A' })).toHaveAttribute('href', '/services/svc_A');
    expect(row.getByText(/Merged into/)).toBeInTheDocument();

    await user.click(row.getByRole('button', { name: 'Unmerge Example service B' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Unmerge' }));
    await user.click(dialog.getByRole('button', { name: 'Unmerge' }));
    expect(await dialog.findByText('Left as they are (changed after the merge):')).toBeInTheDocument();
    expect(await dialog.findByRole('link', { name: 'Example service C' })).toHaveAttribute('href', '/services/svc_C');
    expect(dialog.getByRole('link', { name: 'Example service D' })).toHaveAttribute('href', '/services/svc_D');
  });

  it('says that a page is past the end instead of showing an empty table', async () => {
    mockApi((url) => {
      if (url.pathname === '/api/meta') return meta;
      if (url.pathname === '/api/stats') return STATS;
      if (url.pathname === '/api/entities/project') return { items: [], total: 1, page: 3, page_size: 50 };
      if (url.pathname === '/api/comments') return { items: [], total: 1, page: 3, page_size: 50 };
      return undefined;
    });
    const { router } = renderRoute(TrashPage, { url: '/trash?type=project&page=3', path: '/trash' });
    expect(await screen.findByText('This page is past the end of the list')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
    await router.navigate({ to: '/trash', search: { type: 'comment', page: '3' } });
    expect(await screen.findByText('This page is past the end of the list')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });
});
