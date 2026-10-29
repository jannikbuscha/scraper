// Per-row results of a bulk edit (docs/UI.md §3): counts per status, deleted
// rows (not changed) and errors.
import { Badge, Button, Group, List, Stack, Title } from '@mantine/core';

import type { BulkResult, BulkStatus } from '../../api/types';
import { BULK_STATUSES, countBulkResults, type BulkTarget } from '../../lib/bulk';
import { EntityLink } from '../EntityLink';

const STATUS_LABELS: Record<BulkStatus, string> = {
  updated: 'Updated',
  unchanged: 'Unchanged',
  entity_deleted: 'Deleted',
  error: 'Error',
};

const STATUS_COLORS: Record<BulkStatus, string> = {
  updated: 'green',
  unchanged: 'gray',
  entity_deleted: 'red',
  error: 'red',
};

interface BulkResultSummaryProps {
  targets: readonly BulkTarget[];
  results: readonly BulkResult[];
  onClose: () => void;
}

export function BulkResultSummary({ targets, results, onClose }: BulkResultSummaryProps) {
  const counts = countBulkResults(results);
  const rowsWith = (status: BulkStatus) =>
    targets.flatMap((target) => {
      const result = results.find((candidate) => candidate.id === target.id);
      return result?.status === status ? [{ target, result }] : [];
    });
  const deleted = rowsWith('entity_deleted');
  const errors = rowsWith('error');

  return (
    <Stack gap="sm">
      <Group gap="xs" role="list" aria-label="Results per status">
        {BULK_STATUSES.map((status) => (
          <Badge key={status} role="listitem" variant="light" color={counts[status] > 0 ? STATUS_COLORS[status] : 'gray'}>
            {STATUS_LABELS[status]}: {counts[status]}
          </Badge>
        ))}
      </Group>

      {deleted.length > 0 && (
        <Stack gap={4}>
          <Title order={4}>Deleted (not changed)</Title>
          <List size="sm">
            {deleted.map(({ target }) => (
              <List.Item key={target.id}>
                <EntityLink id={target.id} label={target.label} deleted />
              </List.Item>
            ))}
          </List>
        </Stack>
      )}

      {errors.length > 0 && (
        <Stack gap={4}>
          <Title order={4}>Errors (not changed)</Title>
          <List size="sm">
            {errors.map(({ target, result }) => (
              <List.Item key={target.id}>
                <EntityLink id={target.id} label={target.label} />: {result.error?.message ?? 'Unknown error.'}
              </List.Item>
            ))}
          </List>
        </Stack>
      )}

      <Group justify="flex-end" gap="xs">
        <Button onClick={onClose}>Close</Button>
      </Group>
    </Stack>
  );
}
