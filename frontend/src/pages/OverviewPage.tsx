// Overview (docs/UI.md §2, §8.8): counts per entity type from /api/stats,
// open comments, open proposals, the last finished collector run with a
// running-run indicator, and links. The dashboard proper arrives in Phase 3.
import { Card, Group, Loader, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';

import type { RunsSummary } from '../api/acquisition-types';
import { useMeta, useStats } from '../api/queries';
import { ENTITY_TYPES, TABLE_ENTITY_TYPES, type EntityStats, type Meta, type TableEntityType } from '../api/types';
import { AnchorLink } from '../components/AnchorLink';
import { ErrorAlert } from '../components/feedback';
import { RunStatusBadge } from '../components/runs/RunStatusBadge';
import { Timestamp } from '../components/Timestamp';
import { TABLE_PATHS } from '../lib/entity';
import { searchFromQuery } from '../lib/query-string';

const count = new Intl.NumberFormat('en-US');

function StatCard({ type, meta, stats }: { type: TableEntityType; meta: Meta; stats: EntityStats | undefined }) {
  const typeMeta = meta.entity_types[type];
  // The type's "unverified" quick filter (docs/API.md §3.1), if it has one.
  const unverified = typeMeta?.quick_filters.find((filter) => filter.key === 'unverified');
  return (
    <Card withBorder padding="sm">
      <AnchorLink to={TABLE_PATHS[type]} fw={600}>
        {typeMeta?.label_plural ?? type}
      </AnchorLink>
      <Text fz={28} fw={600} lh={1.2} mt={4}>
        {stats ? count.format(stats.total) : '–'}
      </Text>
      <Group gap="md" mt={4}>
        {unverified?.kind === 'toggle' ? (
          <AnchorLink to={TABLE_PATHS[type]} search={searchFromQuery(unverified.query)} size="sm">
            {count.format(stats?.unverified ?? 0)} unverified
          </AnchorLink>
        ) : (
          <Text size="sm">{count.format(stats?.unverified ?? 0)} unverified</Text>
        )}
        <AnchorLink to="/trash" search={{ type }} size="sm" c="dimmed">
          {count.format(stats?.deleted ?? 0)} in trash
        </AnchorLink>
      </Group>
    </Card>
  );
}

/** The last finished run and, while one runs, the running run (docs/UI.md §8.8). */
function RunsCard({ runs }: { runs: RunsSummary }) {
  const { running, last_finished: last } = runs;
  return (
    <Card withBorder padding="sm">
      <AnchorLink to="/runs" fw={600}>
        Collector runs
      </AnchorLink>
      {last ? (
        <Stack gap={4} mt={6}>
          <Text size="sm">Last finished run:</Text>
          <Group gap={6}>
            <AnchorLink to="/runs/$id" params={{ id: last.id }}>
              <code>{last.collector}</code>
            </AnchorLink>
            <RunStatusBadge status={last.status} />
            <Text span size="sm" c="dimmed">
              <Timestamp value={last.finished_at} />
            </Text>
          </Group>
        </Stack>
      ) : (
        <Text size="sm" c="dimmed" mt={6}>
          No run has finished yet.
        </Text>
      )}
      {running && (
        <Group gap={6} mt={6}>
          <RunStatusBadge status="running" />
          <AnchorLink to="/runs/$id" params={{ id: running.id }} size="sm">
            <code>{running.collector}</code> since <Timestamp value={running.started_at} />
          </AnchorLink>
        </Group>
      )}
      <Group gap="md" mt={6}>
        <AnchorLink to="/sources" size="sm">
          Sources
        </AnchorLink>
        <AnchorLink to="/import" size="sm">
          Import
        </AnchorLink>
      </Group>
    </Card>
  );
}

export function OverviewPage() {
  useDocumentTitle('Overview · MDT Portfolio');
  const meta = useMeta();
  const stats = useStats();

  if (meta.isPending || stats.isPending) return <Loader size="sm" />;
  if (meta.isError) return <ErrorAlert title="Could not load the metadata" error={meta.error} onRetry={() => void meta.refetch()} />;
  if (stats.isError) return <ErrorAlert title="Could not load the statistics" error={stats.error} onRetry={() => void stats.refetch()} />;

  const otherTypes = ENTITY_TYPES.filter((type) => !TABLE_ENTITY_TYPES.some((t) => t === type));
  return (
    <Stack gap="lg" maw={1200}>
      <Stack gap={4}>
        <Title order={1}>Overview</Title>
        <Text c="dimmed" size="sm">
          Portfolio of projects and digital services of the Ministry of Digital Transformation of Ukraine, with the
          document corpus for the paper “Digital Innovation for Governments under Crisis”.
        </Text>
      </Stack>

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
        {TABLE_ENTITY_TYPES.map((type) => (
          <StatCard key={type} type={type} meta={meta.data} stats={stats.data.entities[type]} />
        ))}
        <Card withBorder padding="sm">
          <AnchorLink to="/comments" search={{ status: 'open' }} fw={600}>
            Open comments
          </AnchorLink>
          <Text fz={28} fw={600} lh={1.2} mt={4}>
            {count.format(stats.data.open_comments)}
          </Text>
          <Group gap="md" mt={4}>
            <AnchorLink to="/changes" size="sm">
              Recent changes
            </AnchorLink>
            <AnchorLink to="/codebook" size="sm">
              Codebook
            </AnchorLink>
          </Group>
        </Card>
        <Card withBorder padding="sm">
          <AnchorLink to="/review" fw={600}>
            Open proposals
          </AnchorLink>
          <Text fz={28} fw={600} lh={1.2} mt={4}>
            {count.format(stats.data.open_proposals)}
          </Text>
          <Group gap="md" mt={4}>
            <AnchorLink to="/review" size="sm">
              Review inbox
            </AnchorLink>
            <AnchorLink to="/review" search={{ tab: 'unverified' }} size="sm">
              New unverified records
            </AnchorLink>
          </Group>
        </Card>
        <RunsCard runs={stats.data.runs} />
      </SimpleGrid>

      <Stack gap={4}>
        <Title order={2}>Other records</Title>
        <Table withTableBorder maw={560}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Type</Table.Th>
              <Table.Th ta="right">Total</Table.Th>
              <Table.Th ta="right">Unverified</Table.Th>
              <Table.Th ta="right">In trash</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {otherTypes.map((type) => {
              const row = stats.data.entities[type];
              return (
                <Table.Tr key={type}>
                  <Table.Td>{meta.data.entity_types[type]?.label_plural ?? type}</Table.Td>
                  <Table.Td ta="right">{count.format(row?.total ?? 0)}</Table.Td>
                  <Table.Td ta="right">{count.format(row?.unverified ?? 0)}</Table.Td>
                  <Table.Td ta="right">{count.format(row?.deleted ?? 0)}</Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Stack>

      <Text size="sm" c="dimmed">
        The dashboard with periods, trajectories and field completeness arrives in Phase 3.
      </Text>
    </Stack>
  );
}
