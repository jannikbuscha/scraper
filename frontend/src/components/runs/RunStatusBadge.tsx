// Run status as a coloured badge (docs/UI.md §8.3): running blue, succeeded
// green, partial orange, failed red, cancelled grey. `TABLE_BADGE_MIN_WIDTH`
// keeps it whole in a narrow table column (Mantine cuts a badge's label with
// an ellipsis, so a table would otherwise squeeze it to its first letter).
import { Badge, Loader } from '@mantine/core';

import type { RunStatus } from '../../api/acquisition-types';
import { RUN_STATUS_COLORS, TABLE_BADGE_MIN_WIDTH } from './run-labels';

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <Badge
      size="sm"
      variant="light"
      color={RUN_STATUS_COLORS[status]}
      miw={TABLE_BADGE_MIN_WIDTH}
      leftSection={status === 'running' ? <Loader size={10} color="blue" aria-hidden /> : undefined}
    >
      {status}
    </Badge>
  );
}
