import { Stack } from '@mantine/core';
import type { ErrorComponentProps } from '@tanstack/react-router';

import { ErrorAlert } from '../components/feedback';

/** Last-resort error display for a route that failed to render. */
export function RouteErrorPage({ error, reset }: ErrorComponentProps) {
  return (
    <Stack maw={720}>
      <ErrorAlert title="This page failed to load" error={error} onRetry={reset} />
    </Stack>
  );
}
