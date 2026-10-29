import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';

import { ApiError } from './api/client';
import { router } from './router';
import { cssVariablesResolver, theme } from './theme';

/** Client errors (4xx) are final; network and server errors are retried twice. */
const shouldRetry = (failureCount: number, error: unknown): boolean =>
  failureCount < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: shouldRetry },
    // Writes are never retried blindly (docs/UI.md §1.3).
    mutations: { retry: false },
  },
});

export function App() {
  return (
    <MantineProvider
      theme={theme}
      cssVariablesResolver={cssVariablesResolver}
      defaultColorScheme="light"
      forceColorScheme="light"
    >
      <Notifications position="bottom-right" limit={4} />
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>
  );
}
