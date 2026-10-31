// Source observations (docs/UI.md §8.4, §8.7): what a collector saw per key,
// read-only. The source page lists one collector's keys with their bound
// record; the "Seen in sources" panel of a detail page lists the record's
// observations with their collector and how they were bound.
import { Badge, Table, Text } from '@mantine/core';

import type { Observation } from '../../api/acquisition-types';
import type { Refs } from '../../api/types';
import { pluralize } from '../../lib/format';
import { AnchorLink } from '../AnchorLink';
import { EntityLink } from '../EntityLink';
import { ExternalLink } from '../ExternalLink';
import { Timestamp } from '../Timestamp';

interface ObservationsTableProps {
  observations: readonly Observation[];
  refs?: Refs | undefined;
  /** Detail pages: the collector (linked to its source page) and how the key was bound. */
  variant: 'source' | 'record';
}

function Presence({ observation }: { observation: Observation }) {
  if (observation.present) {
    return (
      <Badge size="xs" variant="light" color="green">
        present
      </Badge>
    );
  }
  return (
    <Text span size="sm" c="orange">
      missing since <Timestamp value={observation.missing_since_at} />, {pluralize(observation.missing_runs, 'run')}
    </Text>
  );
}

const BOUND_BY: Record<'auto' | 'proposal', string> = { auto: 'matching rule', proposal: 'accepted proposal' };

export function ObservationsTable({ observations, refs = {}, variant }: ObservationsTableProps) {
  return (
    <Table.ScrollContainer minWidth={900}>
      <Table withTableBorder>
        <Table.Thead>
          <Table.Tr>
            {variant === 'record' && <Table.Th>Collector</Table.Th>}
            <Table.Th>Key</Table.Th>
            <Table.Th>Label</Table.Th>
            <Table.Th>URL</Table.Th>
            {variant === 'source' ? <Table.Th>Record</Table.Th> : <Table.Th>Bound by</Table.Th>}
            <Table.Th>Present</Table.Th>
            <Table.Th>First seen</Table.Th>
            <Table.Th>Last seen</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {observations.map((observation) => {
            const ref = observation.subject_id ? refs[observation.subject_id] : undefined;
            return (
              <Table.Tr key={observation.id}>
                {variant === 'record' && (
                  <Table.Td>
                    <AnchorLink to="/sources/$collector" params={{ collector: observation.collector }} size="sm">
                      {observation.collector}
                    </AnchorLink>
                  </Table.Td>
                )}
                <Table.Td>
                  <code>{observation.key}</code>
                </Table.Td>
                <Table.Td>{observation.label && <bdi>{observation.label}</bdi>}</Table.Td>
                <Table.Td>{observation.url && <ExternalLink url={observation.url} />}</Table.Td>
                {variant === 'source' ? (
                  <Table.Td>
                    {observation.subject_id ? (
                      <EntityLink id={observation.subject_id} label={ref?.label} type={ref?.type} deleted={ref?.deleted} />
                    ) : (
                      <Text span size="sm" c="dimmed">
                        unbound
                      </Text>
                    )}
                  </Table.Td>
                ) : (
                  <Table.Td>{observation.bound_by ? BOUND_BY[observation.bound_by] : '—'}</Table.Td>
                )}
                <Table.Td>
                  <Presence observation={observation} />
                </Table.Td>
                <Table.Td>
                  <Timestamp value={observation.first_seen_at} />
                </Table.Td>
                <Table.Td>
                  <Timestamp value={observation.last_seen_at} />
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
