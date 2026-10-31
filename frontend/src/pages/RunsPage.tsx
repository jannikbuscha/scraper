// Runs (docs/UI.md §8.3): "Start run", filters (collector, status, trigger)
// and the runs table, newest first; the list refetches every 3 s while a
// listed run is running. URL: collector, status, trigger, page, page_size.
import { Button, EmptyState, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';
import { IconFilterOff, IconPlayerPlay, IconRun } from '@tabler/icons-react';
import { useState } from 'react';

import { RUN_STATUSES, RUN_TRIGGERS } from '../api/acquisition-types';
import { useCollectors, useRuns } from '../api/runs';
import { FeedPagination } from '../components/changes/FeedPagination';
import { ListParamFilter } from '../components/changes/ListParamFilter';
import { ErrorAlert } from '../components/feedback';
import { RunsTable } from '../components/runs/RunsTable';
import { StartRunModal } from '../components/runs/StartRunModal';
import { useUrlSearch } from '../hooks/useUrlSearch';
import type { SearchRecord } from '../lib/query-string';

const FILTERS = ['collector', 'status', 'trigger'] as const;
const PAGING = ['page', 'page_size'] as const;

/** The request: exactly the URL's filters and paging. */
const runsRequest = (search: SearchRecord): SearchRecord =>
  Object.fromEntries(Object.entries(search).filter(([key]) => [...FILTERS, ...PAGING].some((name) => name === key)));

const hasFilters = (search: SearchRecord): boolean => FILTERS.some((name) => (search[name] ?? '') !== '');

const count = new Intl.NumberFormat('en-US');

export function RunsPage() {
  useDocumentTitle('Runs · MDT Portfolio');
  const [search, setSearch] = useUrlSearch();
  const runs = useRuns(runsRequest(search));
  const collectors = useCollectors();
  const [starting, setStarting] = useState(false);
  const url = { search, setSearch };
  const collectorOptions = (collectors.data?.collectors ?? []).map((collector) => ({
    value: collector.name,
    label: collector.label,
  }));
  const options = (values: readonly string[]) => values.map((value) => ({ value, label: value }));

  let body;
  if (runs.isError) body = <ErrorAlert title="Could not load the runs" error={runs.error} onRetry={() => void runs.refetch()} />;
  else if (runs.isPending) body = <Loader size="sm" />;
  else if (runs.data.items.length === 0) {
    body = hasFilters(search) ? (
      <EmptyState icon={<IconFilterOff size={28} />} title="No runs match the filters">
        <EmptyState.Actions>
          <Button
            variant="light"
            onClick={() => {
              setSearch((previous) => Object.fromEntries(Object.entries(previous).filter(([key]) => key === 'page_size')));
            }}
          >
            Clear filters
          </Button>
        </EmptyState.Actions>
      </EmptyState>
    ) : (
      <EmptyState icon={<IconRun size={28} />} title="No runs yet">
        Start a collector run to fetch data from a source.
      </EmptyState>
    );
  } else body = <RunsTable runs={runs.data.items} />;

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="center">
        <Group gap="xs" align="baseline">
          <Title order={1}>Runs</Title>
          <Text c="dimmed" size="sm" aria-live="polite">
            {runs.data ? `${count.format(runs.data.total)} ${runs.data.total === 1 ? 'run' : 'runs'}` : ''}
          </Text>
        </Group>
        <Button
          leftSection={<IconPlayerPlay size={14} />}
          onClick={() => {
            setStarting(true);
          }}
        >
          Start run
        </Button>
      </Group>
      <Group gap="sm" align="flex-end" wrap="wrap" role="search" aria-label="Filter runs">
        <ListParamFilter param="collector" label="Collector" options={collectorOptions} width={260} {...url} />
        <ListParamFilter param="status" label="Status" options={options(RUN_STATUSES)} width={220} {...url} />
        <ListParamFilter param="trigger" label="Trigger" options={options(RUN_TRIGGERS)} width={160} {...url} />
      </Group>
      <div aria-busy={runs.isPlaceholderData}>{body}</div>
      {runs.data && runs.data.total > 0 && <FeedPagination total={runs.data.total} search={search} setSearch={setSearch} />}
      <StartRunModal
        opened={starting}
        onClose={() => {
          setStarting(false);
        }}
      />
    </Stack>
  );
}
