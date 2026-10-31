import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { PlanRow } from '../../api/acquisition-types';
import { LOOKUP_IDS_PER_REQUEST } from '../../api/lookup';
import { useUrlSearch } from '../../hooks/useUrlSearch';
import { p2Meta, p2ProjectMeta } from '../../test/acquisition-fixtures';
import { mockApi, requestsTo } from '../../test/api-mock';
import { renderRoute } from '../../test/render';
import { ImportHistory } from './ImportHistory';
import { PlanRows } from './PlanView';

const row = (n: number): PlanRow => ({
  row: n + 2,
  action: 'update',
  id: `prj_${String(n).padStart(3, '0')}`,
  changes: { notes: [null, `Example note ${n}`] },
  conflicts: [],
  errors: {},
});

/** Answers `?ids=` lookups with "Example project <n>" for every ID asked. */
function mockLookup() {
  return mockApi((url) => {
    if (url.pathname !== '/api/lookup') return undefined;
    const ids = (url.searchParams.get('ids') ?? '').split(',');
    return { items: ids.map((id) => ({ id, type: 'project', label: `Example project ${id.slice(4)}`, deleted: false, context: null })) };
  });
}

describe('import plan rows (docs/UI.md §8.5)', () => {
  it('names each matched record by its label, so the dry run shows which record a row updates', async () => {
    mockLookup();
    const Page = () => <PlanRows rows={[row(1), row(2)]} type="project" typeMeta={p2ProjectMeta} />;
    renderRoute(Page, { url: '/import', path: '/import' });
    const table = within(await screen.findByRole('table'));
    expect(await table.findByRole('link', { name: 'Example project 001' })).toHaveAttribute('href', '/projects/prj_001');
    expect(table.getByRole('link', { name: 'Example project 002' })).toHaveAttribute('href', '/projects/prj_002');
  });

  it('looks up the labels of a long plan in several short requests', async () => {
    const fetchMock = mockLookup();
    const rows = Array.from({ length: 150 }, (_, n) => row(n));
    const Page = () => <PlanRows rows={rows} type="project" typeMeta={p2ProjectMeta} />;
    renderRoute(Page, { url: '/import', path: '/import' });
    // Text queries: role queries over 150 rows are slow in jsdom.
    expect(await screen.findByText('Example project 149', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText('Example project 000')).toBeInTheDocument();
    const asked = requestsTo(fetchMock, '/api/lookup').map((url) => (url.searchParams.get('ids') ?? '').split(','));
    expect(asked).toHaveLength(2);
    for (const ids of asked) expect(ids.length).toBeLessThanOrEqual(LOOKUP_IDS_PER_REQUEST);
    expect(new Set(asked.flat()).size).toBe(150);
  });
});

describe('import history (docs/UI.md §8.5)', () => {
  it('says that a page is past the end instead of "No imports yet"', async () => {
    mockApi((url) => {
      if (url.pathname === '/api/imports') return { items: [], total: 3, page: 3, page_size: 50 };
      return undefined;
    });
    const Page = () => {
      const [search, setSearch] = useUrlSearch();
      return <ImportHistory meta={p2Meta} search={search} setSearch={setSearch} />;
    };
    const { user, router } = renderRoute(Page, { url: '/import?page=3', path: '/import' });
    expect(await screen.findByText('This page is past the end of the list')).toBeInTheDocument();
    expect(screen.queryByText('No imports yet.')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Go to the last page' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({});
    });
  });
});
