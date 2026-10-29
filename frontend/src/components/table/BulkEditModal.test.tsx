import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import type { BulkRequest, BulkResult } from '../../api/types';
import { AUTHOR_STORAGE_KEY } from '../../lib/author';
import { EntityTablePage } from '../../pages/EntityTablePage';
import { callsTo, jsonBody, mockApi, requestsTo } from '../../test/api-mock';
import { exampleItem, exampleMeta, exampleVocabularies, listResponse } from '../../test/fixtures';
import { renderRoute } from '../../test/render';

const result = (id: string, status: BulkResult['status'], extra: Partial<BulkResult> = {}): BulkResult => ({
  id,
  status,
  version: null,
  current_version: null,
  current_values: null,
  error: null,
  ...extra,
});

/** The rows' versions on the server; bumped to simulate a colleague's edits. */
let versions: Record<string, number>;
/** Bulk responses, in request order. */
let bulkResponses: BulkResult[][];
let bulkBodies: BulkRequest[];

function mockProjectsApi() {
  return mockApi((url, init) => {
    if (url.pathname === '/api/meta') return exampleMeta;
    if (url.pathname === '/api/entities/saved_view') return listResponse([]);
    if (url.pathname === '/api/entities/project') {
      return listResponse([
        exampleItem('prj_A', { name_en: 'Example project A', paper_cluster: 'cluster_a' }, { version: versions.prj_A }),
        exampleItem('prj_B', { name_en: 'Example project B', paper_cluster: null }, { version: versions.prj_B }),
      ]);
    }
    if (url.pathname === '/api/entities/project/bulk' && init?.method === 'POST') {
      bulkBodies.push(jsonBody(init) as BulkRequest);
      return { batch_id: `batch_${bulkBodies.length}`, results: bulkResponses.shift() ?? [] };
    }
    return undefined;
  });
}

const ProjectsPage = () => <EntityTablePage type="project" />;

async function selectBothRows(user: ReturnType<typeof renderRoute>['user']) {
  await user.click(await screen.findByRole('checkbox', { name: 'Select Example project A' }));
  await user.click(screen.getByRole('checkbox', { name: 'Select Example project B' }));
  expect(screen.getByText('2 selected')).toBeInTheDocument();
}

describe('bulk edit', () => {
  beforeEach(() => {
    window.localStorage.setItem(AUTHOR_STORAGE_KEY, 'Example Person');
    versions = { prj_A: 3, prj_B: 7 };
    bulkResponses = [];
    bulkBodies = [];
  });

  it('sends the versions captured at opening and retries conflicted rows with their current versions', async () => {
    const fetchMock = mockProjectsApi();
    const { user, queryClient } = renderRoute(ProjectsPage, {
      url: '/projects',
      path: '/projects',
      vocabularies: exampleVocabularies,
    });
    await selectBothRows(user);
    await user.click(screen.getByRole('button', { name: 'Bulk edit…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Bulk edit · 2 projects' });

    // A colleague edits both rows while the dialog is open; the list refetches.
    versions = { prj_A: 4, prj_B: 9 };
    await queryClient.invalidateQueries({ queryKey: ['list'] });
    await waitFor(() => {
      expect(requestsTo(fetchMock, '/api/entities/project').length).toBeGreaterThan(1);
    });

    await user.click(within(dialog).getByRole('combobox', { name: 'Field' }));
    await user.click(await screen.findByRole('option', { name: 'Paper cluster' }));
    await user.click(within(dialog).getByRole('combobox', { name: 'New value' }));
    await user.click(await screen.findByRole('option', { name: /Example cluster B/ }));

    bulkResponses.push([
      result('prj_A', 'updated', { version: 5 }),
      result('prj_B', 'conflict', { current_version: 9, current_values: { paper_cluster: 'cluster_a' } }),
    ]);
    await user.click(within(dialog).getByRole('button', { name: 'Apply' }));

    await within(dialog).findByText('Updated: 1');
    expect(bulkBodies[0]).toEqual({
      items: [
        { id: 'prj_A', expected_version: 3 },
        { id: 'prj_B', expected_version: 7 },
      ],
      set: { paper_cluster: 'cluster_b' },
      note: null,
    });
    const [bulkCall] = callsTo(fetchMock, '/api/entities/project/bulk');
    const headers = new Headers(bulkCall?.init?.headers);
    expect(headers.get('X-Author')).toBe('Example%20Person');
    expect(headers.get('X-Requested-With')).toBe('mdt');

    // The conflicted row is listed with its current value.
    expect(within(dialog).getByText('Conflict: 1')).toBeInTheDocument();
    const conflictTable = within(dialog).getByRole('table');
    expect(within(conflictTable).getByText('Example project B')).toBeInTheDocument();
    expect(within(conflictTable).getByText('Example cluster A')).toBeInTheDocument();

    bulkResponses.push([result('prj_B', 'updated', { version: 10 })]);
    await user.click(within(dialog).getByRole('button', { name: 'Retry with current versions (1)' }));

    await within(dialog).findByText('Updated: 2');
    expect(bulkBodies[1]).toEqual({
      items: [{ id: 'prj_B', expected_version: 9 }],
      set: { paper_cluster: 'cluster_b' },
      note: null,
    });
    expect(within(dialog).getByText('Conflict: 0')).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: /Retry/ })).toBeNull();
  });

  it('requires a note to mark rows verified', async () => {
    mockProjectsApi();
    const { user } = renderRoute(ProjectsPage, { url: '/projects', path: '/projects', vocabularies: exampleVocabularies });
    await selectBothRows(user);
    await user.click(screen.getByRole('button', { name: 'Mark verified…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Mark verified · 2 projects' });

    await user.click(within(dialog).getByRole('button', { name: 'Mark verified' }));
    expect(within(dialog).getByText('Setting verified or disputed needs a note.')).toBeInTheDocument();
    expect(bulkBodies).toHaveLength(0);

    bulkResponses.push([result('prj_A', 'updated', { version: 4 }), result('prj_B', 'unchanged', { version: 7 })]);
    await user.type(within(dialog).getByRole('textbox', { name: /Change note/ }), 'Checked against the example source');
    await user.click(within(dialog).getByRole('button', { name: 'Mark verified' }));

    await within(dialog).findByText('Unchanged: 1');
    expect(bulkBodies[0]).toEqual({
      items: [
        { id: 'prj_A', expected_version: 3 },
        { id: 'prj_B', expected_version: 7 },
      ],
      set: { verification_status: 'verified' },
      note: 'Checked against the example source',
    });
  });
});
