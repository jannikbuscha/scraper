// One collector on the Sources page (docs/UI.md §8.4): label and source ID,
// enabled and available (with the reason), the target-server notice, hosts
// with their intervals and the excluded hosts, the licence, the last run and
// a running indicator, observation counts (links to the detail page,
// filtered), open proposals (link to the review inbox) and "Run now".
import { Badge, Button, Card, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { IconAlertTriangle, IconPlayerPlay } from '@tabler/icons-react';

import type { Collector } from '../../api/acquisition-types';
import { AnchorLink } from '../AnchorLink';
import { RunStatusBadge } from '../runs/RunStatusBadge';
import { formatCount, unavailableText } from '../runs/run-labels';
import { Timestamp } from '../Timestamp';
import { HostList, LicenceText } from './collector-details';

interface CollectorCardProps {
  collector: Collector;
  onRun: (name: string) => void;
}

export function CollectorCard({ collector, onRun }: CollectorCardProps) {
  const { observations } = collector;
  return (
    <Card withBorder padding="sm" component="section" aria-label={collector.label}>
      <Stack gap={6}>
        <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
          <Stack gap={2}>
            <Title order={2} fz="md">
              <AnchorLink to="/sources/$collector" params={{ collector: collector.name }} inherit>
                <bdi>{collector.label}</bdi>
              </AnchorLink>
            </Title>
            <Text size="xs" c="dimmed">
              <code>{collector.name}</code>
              {collector.source && ` · source ${collector.source}`}
              {collector.builtin && ' · built-in'}
            </Text>
          </Stack>
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlayerPlay size={12} />}
            disabled={!collector.available || collector.running_run_id !== null}
            title={collector.available ? undefined : unavailableText(collector.unavailable_reason)}
            onClick={() => {
              onRun(collector.name);
            }}
          >
            Run now
          </Button>
        </Group>
        <Group gap={6}>
          <Badge size="sm" variant="light" color={collector.enabled ? 'green' : 'gray'}>
            {collector.enabled ? 'enabled' : 'disabled'}
          </Badge>
          <Badge size="sm" variant="light" color={collector.available ? 'green' : 'orange'}>
            {collector.available ? 'available' : 'unavailable'}
          </Badge>
          {!collector.available && (
            <Text span size="xs" c="orange">
              {unavailableText(collector.unavailable_reason)}
            </Text>
          )}
        </Group>
        {collector.needs_server_check && (
          <Group gap={4} wrap="nowrap">
            <IconAlertTriangle size={14} color="var(--mantine-color-yellow-7)" aria-hidden />
            <Text size="xs">Needs checks from the target server (docs/SOURCES.md).</Text>
          </Group>
        )}
        <HostList collector={collector} />
        <LicenceText collector={collector} />
        <Group gap={6} wrap="wrap">
          <Text size="sm" fw={500}>
            Last run:
          </Text>
          {collector.running_run_id ? (
            <Group gap={4}>
              <Loader size={12} aria-hidden />
              <AnchorLink to="/runs/$id" params={{ id: collector.running_run_id }} size="sm">
                running now
              </AnchorLink>
            </Group>
          ) : collector.last_run ? (
            <>
              <RunStatusBadge status={collector.last_run.status} />
              <AnchorLink to="/runs/$id" params={{ id: collector.last_run.id }} size="sm">
                <Timestamp value={collector.last_run.finished_at ?? collector.last_run.started_at} />
              </AnchorLink>
            </>
          ) : (
            <Text size="sm" c="dimmed">
              never
            </Text>
          )}
        </Group>
        <Group gap="md" wrap="wrap">
          <Text size="sm">
            Observations:{' '}
            <AnchorLink to="/sources/$collector" params={{ collector: collector.name }} search={{ present: 'true' }}>
              {formatCount(observations.present)} present
            </AnchorLink>
            {' · '}
            <AnchorLink to="/sources/$collector" params={{ collector: collector.name }} search={{ present: 'false' }}>
              {formatCount(observations.missing)} missing
            </AnchorLink>
          </Text>
          <AnchorLink to="/review" search={{ collector: collector.name }} size="sm">
            {formatCount(collector.open_proposals)} open {collector.open_proposals === 1 ? 'proposal' : 'proposals'}
          </AnchorLink>
        </Group>
      </Stack>
    </Card>
  );
}
