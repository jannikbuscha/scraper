// Renders a page under a memory router that uses the app's search
// serialisation (docs/UI.md §1.2), with Mantine in test mode (no transitions;
// popovers stay visible although jsdom has no layout), a fresh query client
// and optionally a vocabulary index.
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router';
import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';

import type { Vocabulary } from '../api/types';
import { VocabIndexContext } from '../hooks/useVocabIndex';
import { parseSearch, stringifySearch, validateSearch } from '../lib/query-string';
import { buildVocabIndex } from '../lib/vocab';
import { theme } from '../theme';

interface RenderRouteOptions {
  /** Initial URL, e.g. `/projects?f.kind=in:media`. */
  url: string;
  /** Route path the page is mounted at, e.g. `/projects`. */
  path: string;
  vocabularies?: Vocabulary[];
}

export function renderRoute(Page: () => ReactElement, { url, path, vocabularies = [] }: RenderRouteOptions) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const vocabIndex = buildVocabIndex(vocabularies);
  const rootRoute = createRootRoute({ validateSearch, component: Outlet });
  const pageRoute = createRoute({ getParentRoute: () => rootRoute, path, component: Page });
  const router = createRouter({
    routeTree: rootRoute.addChildren([pageRoute]),
    history: createMemoryHistory({ initialEntries: [url] }),
    parseSearch,
    stringifySearch,
  });
  const user = userEvent.setup();
  render(
    <MantineProvider theme={theme} env="test">
      <QueryClientProvider client={queryClient}>
        <VocabIndexContext.Provider value={vocabIndex}>
          <RouterProvider router={router} />
        </VocabIndexContext.Provider>
      </QueryClientProvider>
    </MantineProvider>,
  );
  return { router, queryClient, user };
}
