// Run status as a coloured badge (docs/UI.md §8.3): running blue, succeeded
// green, partial orange, failed red, cancelled grey.
import { Badge, Loader } from '@mantine/core';

import type { RunStatus } from '../../api/acquisition-types';
import { RUN_STATUS_COLORS } from './run-labels';

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <Badge
      size="sm"
      variant="light"
      color={RUN_STATUS_COLORS[status]}
      leftSection={status === 'running' ? <Loader size={10} color="blue" aria-hidden /> : undefined}
    >
      {status}
    </Badge>
  );
}
