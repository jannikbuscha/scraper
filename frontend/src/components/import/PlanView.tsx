// The plan of a dry run, or the result of an import (docs/UI.md §8.5): count
// tiles and the row table (row number, action, record, changes as
// "field: current → new", conflicts with their reason, errors). At most 500
// rows are listed (errors first, then conflicts). The plan names records by ID
// only; their labels come from the lookup, so the person sees which record
// each row matched before writing.
import { Badge, Group, Paper, SimpleGrid, Stack, Table, Text } from '@mantine/core';

import type { ImportConflictReason, Plan, PlanRow, PlanStats } from '../../api/acquisition-types';
import { useLookupIds } from '../../api/lookup';
import type { EntityTypeMeta, JsonValue, TableEntityType } from '../../api/types';
import { jsonText, pluralize } from '../../lib/format';
import { EntityLink } from '../EntityLink';

const ACTION_COLORS: Record<PlanRow['action'], string> = {
  create: 'green',
  update: 'blue',
  unchanged: 'gray',
  error: 'red',
};

export const CONFLICT_REASONS: Record<ImportConflictReason, string> = {
  manual: 'set by a person',
  seed: 'from the seed',
  verified: 'verified or disputed',
  restored: 'restored from an older version',
};

const TILES: readonly [keyof PlanStats, string][] = [
  ['rows', 'Rows'],
  ['create', 'Create'],
  ['update', 'Update'],
  ['unchanged', 'Unchanged'],
  ['conflicts', 'Conflicts'],
  ['errors', 'Errors'],
];

export function PlanTiles({ stats }: { stats: Partial<PlanStats> }) {
  return (
    <SimpleGrid cols={{ base: 3, md: 6 }} spacing="xs" maw={900}>
      {TILES.map(([key, label]) => (
        <Paper key={key} withBorder p={6} aria-label={`${label}: ${stats[key] ?? 0}`}>
          <Text size="xs" c="dimmed">
            {label}
          </Text>
          <Text fw={600} size="lg">
            {stats[key] ?? 0}
          </Text>
        </Paper>
      ))}
    </SimpleGrid>
  );
}

const valueText = (value: JsonValue): string => (Array.isArray(value) ? value.map((entry) => jsonText(entry)).join('; ') : jsonText(value));

/** Row items: changes, conflicts and errors of each listed row. */
export function PlanRows({ rows, type, typeMeta }: { rows: readonly PlanRow[]; type: TableEntityType; typeMeta: EntityTypeMeta | undefined }) {
  const labelOf = (field: string) => typeMeta?.fields.find((spec) => spec.name === field)?.label ?? field;
  const records = useLookupIds(rows.flatMap((row) => (row.id ? [row.id] : []))).byId;
  if (rows.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No rows.
      </Text>
    );
  }
  return (
    <Table.ScrollContainer minWidth={860}>
      <Table withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={60}>Row</Table.Th>
            <Table.Th w={100}>Action</Table.Th>
            <Table.Th>Record</Table.Th>
            <Table.Th>Changes</Table.Th>
            <Table.Th>Conflicts (not written)</Table.Th>
            <Table.Th>Errors</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.row}>
              <Table.Td>{row.row}</Table.Td>
              <Table.Td>
                <Badge size="sm" variant="light" color={ACTION_COLORS[row.action]}>
                  {row.action}
                </Badge>
              </Table.Td>
              <Table.Td>
                {row.id ? (
                  <EntityLink id={row.id} type={type} label={records.get(row.id)?.label} deleted={records.get(row.id)?.deleted} />
                ) : (
                  '—'
                )}
              </Table.Td>
              <Table.Td>
                <Stack gap={2}>
                  {Object.entries(row.changes).map(([field, [current, next]]) => (
                    <Text key={field} size="xs">
                      <Text span fw={500} size="xs">
                        {labelOf(field)}:
                      </Text>{' '}
                      <bdi>{valueText(current)}</bdi> → <bdi>{valueText(next)}</bdi>
                    </Text>
                  ))}
                </Stack>
              </Table.Td>
              <Table.Td>
                <Stack gap={2}>
                  {row.conflicts.map((conflict) => (
                    <Text key={conflict.field} size="xs" c="orange.8">
                      <Text span fw={500} size="xs">
                        {labelOf(conflict.field)}
                      </Text>{' '}
                      ({CONFLICT_REASONS[conflict.reason]}): keeps <bdi>{valueText(conflict.current)}</bdi>, file has{' '}
                      <bdi>{valueText(conflict.new)}</bdi>
                    </Text>
                  ))}
                </Stack>
              </Table.Td>
              <Table.Td>
                <Stack gap={2}>
                  {Object.entries(row.errors).map(([field, messages]) => (
                    <Text key={field} size="xs" c="red">
                      {labelOf(field)}: {messages.join(' ')}
                    </Text>
                  ))}
                </Stack>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

export function PlanView({ plan, type, typeMeta }: { plan: Plan; type: TableEntityType; typeMeta: EntityTypeMeta | undefined }) {
  return (
    <Stack gap="xs">
      <PlanTiles stats={plan.stats} />
      {plan.rows.length < plan.stats.rows && (
        <Group gap={4}>
          <Text size="xs" c="dimmed">
            Showing {pluralize(plan.rows.length, 'row')} of {plan.stats.rows}: errors first, then conflicts, then the rest.
          </Text>
        </Group>
      )}
      <PlanRows rows={plan.rows} type={type} typeMeta={typeMeta} />
    </Stack>
  );
}
