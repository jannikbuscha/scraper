import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChangeFeedItem, ChangeFeedResponse, RevisionByIdResponse } from '../api/types';
import { mockApi, requestsTo } from '../test/api-mock';
import { exampleMeta } from '../test/fixtures';
import { renderRoute } from '../test/render';
import { RecentChangesPage } from './RecentChangesPage';

const change = (overrides: Partial<ChangeFeedItem>): ChangeFeedItem => ({
  id: 1,
  entity_type: 'project',
  entity_id: 'prj_A',
  entity_label: 'Example project A',
  version: 2,
  at: '2026-10-01T09:30:00.000000Z',
  author: 'user',
  channel: 'ui',
  action: 'update',
  note: 'Example note',
  changed_fields: ['name_en'],
  restored_from_version: null,
  batch_id: null,
  run_id: null,
  proposal_id: null,
  context: null,
  ...overrides,
});

const FEED: ChangeFeedResponse = {
  items: [
    change({ id: 12, entity_type: 'comment', entity_id: 'cmt_1', entity_label: 'Comment on Example project A', action: 'create', changed_fields: ['body_md'], context: { subject_id: 'prj_A', subject_type: 'project', field: null } }),
    change({ id: 11 }),
  ],
  total: 2,
  page: 2,
  page_size: 50,
};

const REVISION: RevisionByIdResponse = {
  revision: {
    id: 11,
    version: 2,
    at: '2026-10-01T09:30:00.000000Z',
    author: 'user',
    channel: 'ui',
    action: 'update',
    note: 'Example note',
    changed_fields: ['name_en'],
    restored_from: null,
    restored_from_version: null,
    batch_id: null,
    run_id: null,
    proposal_id: null,
    snapshot: { fields: {}, field_meta: {}, state: {} },
    diff: { fields: { name_en: ['Old example name', 'New example name'] } },
    schema_revision: null,
  },
  entity_type: 'project',
  entity_id: 'prj_A',
  entity_label: 'Example project A',
  refs: {},
};

function mockFeedApi() {
  return mockApi((url) => {
    if (url.pathname === '/api/meta') return exampleMeta;
    if (url.pathname === '/api/revisions') return FEED;
    if (url.pathname === '/api/revisions/11') return REVISION;
    return undefined;
  });
}

const feedRequests = (fetchMock: ReturnType<typeof mockApi>) =>
  requestsTo(fetchMock, '/api/revisions').map((url) => Object.fromEntries(url.searchParams));

describe('Recent changes', () => {
  beforeEach(() => {
    vi.stubEnv('TZ', 'Europe/Kyiv');
  });

  it('round-trips the filter state through the URL', async () => {
    const fetchMock = mockFeedApi();
    const { router, user } = renderRoute(RecentChangesPage, {
      url: '/changes?entity_type=project,comment&channel=ui&since=2026-10-01&until=2026-10-02&batch_id=batch_1&page=2',
      path: '/changes',
    });

    // The URL is read into the request: local days become inclusive timestamps.
    await screen.findByText('Example project A');
    expect(feedRequests(fetchMock)).toEqual([
      {
        entity_type: 'project,comment',
        channel: 'ui',
        since: '2026-09-30T21:00:00.000000Z',
        until: '2026-10-02T20:59:59.999999Z',
        batch_id: 'batch_1',
        page: '2',
      },
    ]);
    // ... and into the controls.
    expect(screen.getByRole('textbox', { name: 'From day' })).toHaveValue('2026-10-01');
    expect(screen.getByRole('textbox', { name: 'To day' })).toHaveValue('2026-10-02');
    expect(screen.getByRole('textbox', { name: 'Batch' })).toHaveValue('batch_1');
    const option = (list: string, name: string) =>
      within(screen.getByRole('listbox', { name: list, hidden: true })).getByRole('option', { name, hidden: true });
    expect(option('Record type', 'Comment')).toHaveAttribute('aria-selected', 'true');
    expect(option('Record type', 'Project')).toHaveAttribute('aria-selected', 'true');
    expect(option('Channel', 'manual')).toHaveAttribute('aria-selected', 'true');
    expect(option('Channel', 'seed')).toHaveAttribute('aria-selected', 'false');

    // A control writes the URL; any filter change returns to page 1.
    await user.click(screen.getByRole('combobox', { name: 'Action' }));
    await user.click(await screen.findByRole('option', { name: 'delete' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({
        entity_type: 'project,comment',
        channel: 'ui',
        action: 'delete',
        since: '2026-10-01',
        until: '2026-10-02',
        batch_id: 'batch_1',
      });
    });
    await waitFor(() => {
      expect(feedRequests(fetchMock).at(-1)).toEqual({
        entity_type: 'project,comment',
        channel: 'ui',
        action: 'delete',
        since: '2026-09-30T21:00:00.000000Z',
        until: '2026-10-02T20:59:59.999999Z',
        batch_id: 'batch_1',
      });
    });

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => {
      expect(router.state.location.searchStr).toBe('');
    });
    expect(screen.getByRole('textbox', { name: 'Batch' })).toHaveValue('');
  });

  it('groups rows by local day, links comments to their thread and expands a row to its diff', async () => {
    const fetchMock = mockFeedApi();
    const { user } = renderRoute(RecentChangesPage, { url: '/changes', path: '/changes' });

    expect(await screen.findByRole('rowheader', { name: /2026-10-01/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Comment on Example project A' })).toHaveAttribute(
      'href',
      '/projects/prj_A?comments=open&thread=cmt_1',
    );
    expect(screen.getByRole('link', { name: 'Example project A' })).toHaveAttribute('href', '/projects/prj_A');

    await user.click(screen.getByRole('button', { name: 'Show the changes of Example project A v2' }));
    expect(await screen.findByText('New example name')).toBeInTheDocument();
    expect(screen.getByText('Old example name')).toBeInTheDocument();
    expect(requestsTo(fetchMock, '/api/revisions/11')).toHaveLength(1);
  });
});
