// Per-row results of a bulk edit (docs/UI.md §3): counts per status;
// conflicted rows with their current values and "Retry with current
// versions"; rows deleted in the meantime; errors.
import { Badge, Button, Group, List, Stack, Table, Text, Title } from '@mantine/core';

import type { BulkResult, BulkStatus, FieldSpec } from '../../api/types';
import { BULK_STATUSES, countBulkResults, type BulkTarget } from '../../lib/bulk';
import { guessFieldType, syntheticField } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { ValueDisplay } from '../fields/FieldValue';

const STATUS_LABELS: Record<BulkStatus, string> = {
  updated: 'Updated',
  unchanged: 'Unchanged',
  conflict: 'Conflict',
  entity_deleted: 'Deleted',
  error: 'Error',
};

const STATUS_COLORS: Record<BulkStatus, string> = {
  updated: 'green',
  unchanged: 'gray',
  conflict: 'yellow',
  entity_deleted: 'red',
  error: 'red',
};

interface BulkResultSummaryProps {
  targets: readonly BulkTarget[];
  results: ReadonlyMap<string, BulkResult>;
  /** Registry fields of the type, to label and show current values. */
  fields: readonly FieldSpec[];
  retrying: boolean;
  onRetry: () => void;
  onClose: () => void;
}

export function BulkResultSummary({ targets, results, fields, retrying, onRetry, onClose }: BulkResultSummaryProps) {
  const counts = countBulkResults(results);
  const rowsWith = (status: BulkStatus) =>
    targets.flatMap((target) => {
      const result = results.get(target.id);
      return result?.status === status ? [{ target, result }] : [];
    });
  const conflicts = rowsWith('conflict');
  const deleted = rowsWith('entity_deleted');
  const errors = rowsWith('error');
  const specOf = (name: string, value: BulkResult['current_values']) =>
    fields.find((field) => field.name === name) ?? syntheticField(name, guessFieldType(value?.[name] ?? null));

  return (
    <Stack gap="sm">
      <Group gap="xs" role="list" aria-label="Results per status">
        {BULK_STATUSES.map((status) => (
          <Badge key={status} role="listitem" variant="light" color={counts[status] > 0 ? STATUS_COLORS[status] : 'gray'}>
            {STATUS_LABELS[status]}: {counts[status]}
          </Badge>
        ))}
      </Group>

      {conflicts.length > 0 && (
        <Stack gap={4}>
          <Title order={4}>Changed by someone else since you opened this dialog</Title>
          <Text size="sm" c="dimmed">
            Review the current values. Retrying applies your change to these rows on top of their current version.
          </Text>
          <Table withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Row</Table.Th>
                <Table.Th w={80}>Version</Table.Th>
                <Table.Th>Current values</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {conflicts.map(({ target, result }) => (
                <Table.Tr key={target.id}>
                  <Table.Td>
                    <EntityLink id={target.id} label={target.label} />
                  </Table.Td>
                  <Table.Td>v{result.current_version ?? '?'}</Table.Td>
                  <Table.Td>
                    <Stack gap={2}>
                      {Object.entries(result.current_values ?? {}).map(([name, value]) => {
                        const spec = specOf(name, result.current_values);
                        return (
                          <Group key={name} gap={6} wrap="nowrap" align="flex-start">
                            <Text span size="sm" c="dimmed">
                              {spec.label}:
                            </Text>
                            <ValueDisplay field={spec} value={value} />
                          </Group>
                        );
                      })}
                    </Stack>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      )}

      {deleted.length > 0 && (
        <Stack gap={4}>
          <Title order={4}>Deleted in the meantime (not changed)</Title>
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
        {conflicts.length > 0 && (
          <Button variant="light" color="yellow" loading={retrying} onClick={onRetry}>
            Retry with current versions ({conflicts.length})
          </Button>
        )}
        <Button onClick={onClose}>Close</Button>
      </Group>
    </Stack>
  );
}
