// One collector (docs/UI.md §8.4): its details and declaration, the recent
// runs, and the read-only observations table with the filters present, bound
// and text. URL: present, bound, q, page, page_size.
import { Badge, Breadcrumbs, Button, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';
import { useParams } from '@tanstack/react-router';
import { IconAlertTriangle, IconPlayerPlay, IconSearch } from '@tabler/icons-react';
import { useState } from 'react';

import { isApiError } from '../api/client';
import { useObservations } from '../api/proposals';
import { useMeta } from '../api/queries';
import { useCollector } from '../api/runs';
import { AnchorLink } from '../components/AnchorLink';
import { DebouncedParamInput } from '../components/changes/DebouncedParamInput';
import { FeedPagination } from '../components/changes/FeedPagination';
import { withParam } from '../components/changes/feed-query';
import { SegmentedFilter } from '../components/changes/SegmentedFilter';
import { ErrorAlert } from '../components/feedback';
import { RunsTable } from '../components/runs/RunsTable';
import { unavailableText } from '../components/runs/run-labels';
import { StartRunModal } from '../components/runs/StartRunModal';
import { DeclarationTable, HostList, LicenceText } from '../components/sources/collector-details';
import { ObservationsTable } from '../components/sources/ObservationsTable';
import { useUrlSearch } from '../hooks/useUrlSearch';
import type { SearchRecord } from '../lib/query-string';

const OBSERVATION_PARAMS = ['present', 'bound', 'q', 'page', 'page_size'];

const observationRequest = (collector: string, search: SearchRecord): SearchRecord => ({
  ...Object.fromEntries(Object.entries(search).filter(([key, value]) => value !== '' && OBSERVATION_PARAMS.includes(key))),
  collector,
});

export function SourceDetailPage() {
  const { collector: name = '' } = useParams({ strict: false });
  const collector = useCollector(name);
  const meta = useMeta();
  const [search, setSearch] = useUrlSearch();
  const observations = useObservations(observationRequest(name, search));
  const [starting, setStarting] = useState(false);
  useDocumentTitle(`${collector.data?.collector.label ?? name} · Sources · MDT Portfolio`);

  if (collector.isPending) return <Loader size="sm" />;
  if (collector.isError) {
    if (isApiError(collector.error, 'not_found')) {
      return (
        <Stack gap="xs" align="flex-start">
          <ErrorAlert title="Collector not found" error={new Error(`There is no collector “${name}”.`)} />
          <AnchorLink to="/sources">Back to the sources</AnchorLink>
        </Stack>
      );
    }
    return <ErrorAlert title="Could not load the collector" error={collector.error} onRetry={() => void collector.refetch()} />;
  }
  const { collector: details, recent_runs: runs } = collector.data;
  const url = { search, setSearch };

  return (
    <Stack gap="md">
      <Breadcrumbs separator="›" fz="sm">
        <AnchorLink to="/sources">Sources</AnchorLink>
        <bdi>{details.label}</bdi>
      </Breadcrumbs>
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Title order={1}>
            <bdi>{details.label}</bdi>
          </Title>
          <Group gap={6}>
            <Text size="sm" c="dimmed">
              <code>{details.name}</code>
              {details.source && ` · source ${details.source}`}
            </Text>
            <Badge size="sm" variant="light" color={details.enabled ? 'green' : 'gray'}>
              {details.enabled ? 'enabled' : 'disabled'}
            </Badge>
            <Badge size="sm" variant="light" color={details.available ? 'green' : 'orange'}>
              {details.available ? 'available' : unavailableText(details.unavailable_reason)}
            </Badge>
          </Group>
        </Stack>
        <Button
          leftSection={<IconPlayerPlay size={14} />}
          disabled={!details.available || details.running_run_id !== null}
          onClick={() => {
            setStarting(true);
          }}
        >
          Run now
        </Button>
      </Group>
      {details.needs_server_check && (
        <Group gap={6} wrap="nowrap">
          <IconAlertTriangle size={16} color="var(--mantine-color-yellow-7)" aria-hidden />
          <Text size="sm">Needs checks from the target server before regular runs (docs/SOURCES.md).</Text>
        </Group>
      )}
      <HostList collector={details} />
      <LicenceText collector={details} />

      <Stack gap="xs" component="section" aria-labelledby="declaration">
        <Title order={2} id="declaration">
          What it may write
        </Title>
        <DeclarationTable collector={details} meta={meta.data} />
      </Stack>

      <Stack gap="xs" component="section" aria-labelledby="recent-runs">
        <Group justify="space-between">
          <Title order={2} id="recent-runs">
            Recent runs
          </Title>
          <AnchorLink to="/runs" search={{ collector: details.name }} size="sm">
            All runs of this collector
          </AnchorLink>
        </Group>
        {runs.length === 0 ? (
          <Text size="sm" c="dimmed">
            No runs yet.
          </Text>
        ) : (
          <RunsTable runs={runs} showCollector={false} />
        )}
      </Stack>

      <Stack gap="xs" component="section" aria-labelledby="observations">
        <Title order={2} id="observations">
          Observations
        </Title>
        <Text size="sm" c="dimmed">
          What the collector saw per key. Keys are bound to records by the matching rules or by an accepted proposal;
          they cannot be edited here.
        </Text>
        <Group gap="sm" align="flex-end" wrap="wrap" role="search" aria-label="Filter observations">
          <SegmentedFilter
            label="Present"
            data={[
              { value: '', label: 'All' },
              { value: 'true', label: 'Present' },
              { value: 'false', label: 'Missing' },
            ]}
            value={search.present ?? ''}
            onChange={(value) => {
              setSearch((previous) => withParam(previous, 'present', value));
            }}
          />
          <SegmentedFilter
            label="Bound"
            data={[
              { value: '', label: 'All' },
              { value: 'true', label: 'Bound' },
              { value: 'false', label: 'Unbound' },
            ]}
            value={search.bound ?? ''}
            onChange={(value) => {
              setSearch((previous) => withParam(previous, 'bound', value));
            }}
          />
          <DebouncedParamInput
            param="q"
            label="Text"
            placeholder="Key, label or URL"
            leftSection={<IconSearch size={14} />}
            width={260}
            {...url}
          />
        </Group>
        {observations.isError ? (
          <ErrorAlert
            title="Could not load the observations"
            error={observations.error}
            onRetry={() => void observations.refetch()}
          />
        ) : observations.isPending ? (
          <Loader size="sm" />
        ) : observations.data.items.length === 0 ? (
          <Text size="sm" c="dimmed">
            No observations match.
          </Text>
        ) : (
          <>
            <div aria-busy={observations.isPlaceholderData}>
              <ObservationsTable observations={observations.data.items} refs={observations.data.refs} variant="source" />
            </div>
            <FeedPagination total={observations.data.total} search={search} setSearch={setSearch} />
          </>
        )}
      </Stack>
      <StartRunModal
        opened={starting}
        collector={details.name}
        onClose={() => {
          setStarting(false);
        }}
      />
    </Stack>
  );
}
