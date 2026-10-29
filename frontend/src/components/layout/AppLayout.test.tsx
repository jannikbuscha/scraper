import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { AUTHOR_STORAGE_KEY, READ_ONLY_SESSION_KEY } from '../../lib/author';
import { parseSearch, stringifySearch, validateSearch } from '../../lib/query-string';
import { mockApi } from '../../test/api-mock';
import { exampleMeta } from '../../test/fixtures';
import { theme } from '../../theme';
import { AppLayout } from './AppLayout';

/** Renders the app shell at `url`, like a full page load (a fresh router and query client). */
function loadPage(url = '/') {
  const rootRoute = createRootRoute({ component: AppLayout, validateSearch });
  const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: () => <p>Example page</p> });
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
    history: createMemoryHistory({ initialEntries: [url] }),
    parseSearch,
    stringifySearch,
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <MantineProvider theme={theme} env="test">
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>,
  );
  return { ...view, user: userEvent.setup() };
}

function mockShellApi() {
  return mockApi((url) => {
    if (url.pathname === '/api/meta') return exampleMeta;
    if (url.pathname === '/api/vocab') return { vocabularies: [] };
    return undefined;
  });
}

describe('the author prompt (docs/UI.md §1.5)', () => {
  it('asks on the first visit; "Continue read-only" is remembered for the session, also across page loads', async () => {
    mockShellApi();
    const first = loadPage();
    const dialog = await screen.findByRole('dialog', { name: 'Who are you?' });
    await first.user.click(within(dialog).getByRole('button', { name: 'Continue read-only' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Who are you?' })).toBeNull();
    });
    expect(window.sessionStorage.getItem(READ_ONLY_SESSION_KEY)).toBe('1');
    expect(window.localStorage.getItem(AUTHOR_STORAGE_KEY)).toBeNull();

    // A reload (or a deep link in the same tab) does not ask again.
    first.unmount();
    loadPage();
    expect(await screen.findByText('Example page')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Who are you?' })).toBeNull();
  });

  it('asks again until a choice is made, and never once a name is stored', async () => {
    mockShellApi();
    const first = loadPage();
    expect(await screen.findByRole('dialog', { name: 'Who are you?' })).toBeInTheDocument();
    first.unmount();
    // No choice was made (the page was left with the prompt open): it asks again.
    const second = loadPage();
    expect(await screen.findByRole('dialog', { name: 'Who are you?' })).toBeInTheDocument();
    second.unmount();

    window.localStorage.setItem(AUTHOR_STORAGE_KEY, 'Example Person');
    loadPage();
    expect(await screen.findByText('Example page')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Who are you?' })).toBeNull();
  });
});
