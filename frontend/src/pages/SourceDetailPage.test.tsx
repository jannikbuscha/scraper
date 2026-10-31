import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { exampleCollector, exampleObservation, p2Meta } from '../test/acquisition-fixtures';
import { mockApi } from '../test/api-mock';
import { renderRoute } from '../test/render';
import { SourceDetailPage } from './SourceDetailPage';

function mockSource(observations: (url: URL) => unknown) {
  return mockApi((url) => {
    if (url.pathname === '/api/meta') return p2Meta;
    if (url.pathname === '/api/collectors/example_collector') return { collector: exampleCollector(), recent_runs: [] };
    if (url.pathname === '/api/observations') return observations(url);
    return undefined;
  });
}

describe('source page (docs/UI.md §8.4)', () => {
  it('says that a page of observations is past the end instead of "No observations match"', async () => {
    mockSource((url) => {
      const page = Number(url.searchParams.get('page') ?? '1');
      // 30 observations at 25 per page: page 5 is past the end.
      const items = page === 2 ? [exampleObservation({ key: 'entry:example-last' })] : [];
      return { items, total: 30, page, page_size: 25, refs: {} };
    });
    const { user, router } = renderRoute(SourceDetailPage, {
      url: '/sources/example_collector?page=5&page_size=25',
      path: '/sources/$collector',
    });
    const section = within(await screen.findByRole('region', { name: 'Observations' }));
    expect(await section.findByText('This page is past the end of the list')).toBeInTheDocument();
    expect(section.queryByText('No observations match.')).toBeNull();
    expect(section.getByRole('navigation', { name: 'Pages' })).toBeInTheDocument();
    await user.click(section.getByRole('button', { name: 'Go to the last page' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ page: '2', page_size: '25' });
    });
    expect(await section.findByText('entry:example-last')).toBeInTheDocument();
  });

  it('still says "No observations match" when nothing matches', async () => {
    mockSource(() => ({ items: [], total: 0, page: 1, page_size: 50, refs: {} }));
    renderRoute(SourceDetailPage, { url: '/sources/example_collector?q=nothing', path: '/sources/$collector' });
    expect(await screen.findByText('No observations match.')).toBeInTheDocument();
  });
});
