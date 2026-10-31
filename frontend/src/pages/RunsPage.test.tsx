import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { mockApi } from '../test/api-mock';
import { renderRoute } from '../test/render';
import { RunsPage } from './RunsPage';

describe('runs list (docs/UI.md §8.3)', () => {
  it('says that a page is past the end instead of "No runs yet", and leads to the last page', async () => {
    mockApi((url) => {
      // Page 2 of 14 runs at 25 per page, e.g. from an old link.
      if (url.pathname === '/api/runs') return { items: [], total: 14, page: 2, page_size: 25 };
      if (url.pathname === '/api/collectors') return { collectors: [] };
      return undefined;
    });
    const { user, router } = renderRoute(RunsPage, { url: '/runs?page=2&page_size=25', path: '/runs' });
    expect(await screen.findByText('This page is past the end of the list')).toBeInTheDocument();
    expect(screen.getByText('14 in total; the last page is page 1.')).toBeInTheDocument();
    expect(screen.queryByText('No runs yet')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Go to the last page' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ page_size: '25' });
    });
  });
});
