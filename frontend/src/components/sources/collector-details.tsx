// Shared parts of the collector card and the source page: hosts with their
// request intervals, excluded hosts, the licence, and the declaration of what
// the collector may write (docs/COLLECTORS.md §2.1, §3, §8).
import { Badge, Group, Stack, Table, Text } from '@mantine/core';

import type { Collector } from '../../api/acquisition-types';
import type { Meta } from '../../api/types';
import { typeMetaOf } from '../../lib/entity';

export function HostList({ collector }: { collector: Collector }) {
  return (
    <Stack gap={0}>
      <Text size="sm">
        <Text span fw={500}>
          Hosts:
        </Text>{' '}
        {collector.hosts.length === 0
          ? 'default interval for every host'
          : collector.hosts.map((host) => `${host.host} (every ${host.min_interval_s} s)`).join(', ')}
      </Text>
      {collector.exclude_hosts.length > 0 && (
        <Text size="sm">
          <Text span fw={500}>
            Excluded:
          </Text>{' '}
          {collector.exclude_hosts.join(', ')}
        </Text>
      )}
    </Stack>
  );
}

export function LicenceText({ collector }: { collector: Collector }) {
  return (
    <Text size="sm">
      <Text span fw={500}>
        Licence:
      </Text>{' '}
      <code>{collector.licence.code}</code>
      {collector.licence.statement && (
        <>
          {' · '}
          <bdi>“{collector.licence.statement}”</bdi>
        </>
      )}
    </Text>
  );
}

/** Field labels of an entity type, for the declaration. */
function labelOf(meta: Meta | undefined, type: string, field: string): string {
  return typeMetaOf(meta, type)?.fields.find((spec) => spec.name === field)?.label ?? field;
}

export function DeclarationTable({ collector, meta }: { collector: Collector; meta: Meta | undefined }) {
  const entries = Object.entries(collector.declaration).flatMap(([type, declaration]) =>
    declaration ? [{ type, declaration }] : [],
  );
  if (entries.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        This collector writes no records of its own.
      </Text>
    );
  }
  return (
    <Table.ScrollContainer minWidth={720}>
      <Table withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Type</Table.Th>
            <Table.Th>New records</Table.Th>
            <Table.Th>Writes</Table.Th>
            <Table.Th>Only proposes</Table.Th>
            <Table.Th>Possibly discontinued</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {entries.map(({ type, declaration }) => (
            <Table.Tr key={type}>
              <Table.Td>{typeMetaOf(meta, type)?.label ?? type}</Table.Td>
              <Table.Td>{declaration.creates ? 'creates them' : 'proposes them'}</Table.Td>
              <Table.Td>
                <Group gap={3}>
                  {declaration.writes.map((field) => (
                    <Badge key={field} size="xs" variant="default" title={field}>
                      {labelOf(meta, type, field)}
                    </Badge>
                  ))}
                </Group>
              </Table.Td>
              <Table.Td>
                <Group gap={3}>
                  {declaration.propose_only.length === 0
                    ? '—'
                    : declaration.propose_only.map((field) => (
                        <Badge key={field} size="xs" variant="default" title={field}>
                          {labelOf(meta, type, field)}
                        </Badge>
                      ))}
                </Group>
              </Table.Td>
              <Table.Td>{declaration.discontinued ? 'yes' : 'no'}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
