// One run (docs/UI.md §8.3): header with times, trigger, mode, parameters,
// code version and listing, Cancel and Run again; the fatal error of a failed
// run; every stats counter; tabs Messages, Fetch log and Changes; a link to
// the run's proposals. While the run is running the page refetches every 3 s;
// when it finishes the data queries are invalidated (api/runs.ts).
// URL: tab=messages|fetches|changes, level, outcome, page, page_size.
import { Alert, Badge, Breadcrumbs, Button, Group, Loader, Select, Stack, Tabs, Text, Title } from '@mantine/core';
import { useDocumentTitle } from '@mantine/hooks';
import { useNavigate, useParams } from '@tanstack/react-router';
import { IconAlertTriangle, IconPlayerPlay, IconPlayerStop } from '@tabler/icons-react';
import { useState, type ReactNode } from 'react';

import { FETCH_OUTCOMES, type Run } from '../api/acquisition-types';
import { invalidState, isApiError, runInProgress } from '../api/client';
import { useChangeFeed, useMeta } from '../api/queries';
import { useCancelRun, useRun, useRunFetches, useRunMessages, useStartRun } from '../api/runs';
import { AnchorLink } from '../components/AnchorLink';
import { ChangeFeedTable } from '../components/changes/ChangeFeedTable';
import { FeedPagination } from '../components/changes/FeedPagination';
import { withParam } from '../components/changes/feed-query';
import { SegmentedFilter } from '../components/changes/SegmentedFilter';
import { ErrorAlert, notifyError, notifySuccess } from '../components/feedback';
import { FetchLogTable } from '../components/runs/FetchLogTable';
import { RunMessagesTable } from '../components/runs/RunMessagesTable';
import { formatDuration, formatParams, isReplay, repeatableParams } from '../components/runs/run-labels';
import classes from '../components/runs/runs.module.css';
import { RunStatusBadge } from '../components/runs/RunStatusBadge';
import { StatsGrid } from '../components/runs/StatsGrid';
import { Timestamp } from '../components/Timestamp';
import { useUrlSearch, type SearchUpdate, type SetSearchOptions } from '../hooks/useUrlSearch';
import type { SearchRecord } from '../lib/query-string';

const TABS = ['messages', 'fetches', 'changes'] as const;
type RunTab = (typeof TABS)[number];

const tabOf = (search: SearchRecord): RunTab => TABS.find((tab) => tab === search.tab) ?? 'messages';

/** The URL's paging, and the filters of one list. */
const listRequest = (search: SearchRecord, filter: string): SearchRecord =>
  Object.fromEntries(Object.entries(search).filter(([key, value]) => value !== '' && [filter, 'page', 'page_size'].includes(key)));

interface UrlState {
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
}

export function RunDetailPage() {
  const { id = '' } = useParams({ strict: false });
  const run = useRun(id);
  useDocumentTitle(`${run.data?.run.collector_label ?? 'Run'} · Runs · MDT Portfolio`);
  if (run.isPending) return <Loader size="sm" />;
  if (run.isError) {
    if (isApiError(run.error, 'not_found')) {
      return (
        <Stack gap="xs" align="flex-start">
          <ErrorAlert title="Run not found" error={new Error(`There is no run with the ID “${id}”.`)} />
          <AnchorLink to="/runs">Back to the runs</AnchorLink>
        </Stack>
      );
    }
    return <ErrorAlert title="Could not load the run" error={run.error} onRetry={() => void run.refetch()} />;
  }
  return <RunScreen run={run.data.run} />;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={classes.stat}>
      <dt>{label}</dt>
      <dd style={{ fontSize: 'var(--mantine-font-size-sm)', fontWeight: 400 }}>{children}</dd>
    </div>
  );
}

function RunScreen({ run }: { run: Run }) {
  const [search, setSearch] = useUrlSearch();
  const navigate = useNavigate();
  const cancel = useCancelRun();
  const start = useStartRun();
  const [problem, setProblem] = useState<ReactNode>(null);
  const running = run.status === 'running';
  const tab = tabOf(search);
  const url: UrlState = { search, setSearch };

  const runAgain = async () => {
    setProblem(null);
    try {
      const result = await start.mutateAsync({ collector: run.collector, mode: run.mode, params: repeatableParams(run.params) });
      notifySuccess(`Started a new run of ${run.collector_label ?? run.collector}.`);
      void navigate({ to: '/runs/$id', params: { id: result.run.id } });
    } catch (error) {
      const busy = runInProgress(error);
      if (busy) {
        setProblem(
          <>
            Another run is running; try again when it has finished.{' '}
            {busy.runId && (
              <AnchorLink to="/runs/$id" params={{ id: busy.runId }}>
                Open the running run
              </AnchorLink>
            )}
          </>,
        );
      } else notifyError(error, 'Could not start the run');
    }
  };

  const requestCancel = async () => {
    try {
      await cancel.mutateAsync({ id: run.id });
      notifySuccess('Cancel requested; the run stops at its next checkpoint.');
    } catch (error) {
      if (invalidState(error)) notifySuccess('The run has already finished.');
      else notifyError(error, 'Could not cancel the run');
    }
  };

  return (
    <Stack gap="md">
      <Breadcrumbs separator="›" fz="sm">
        <AnchorLink to="/runs">Runs</AnchorLink>
        <span>{run.id}</span>
      </Breadcrumbs>
      <Group justify="space-between" align="flex-start" gap="sm">
        <Stack gap={6}>
          <Title order={1}>
            <AnchorLink to="/sources/$collector" params={{ collector: run.collector }} inherit>
              <bdi>{run.collector_label ?? run.collector}</bdi>
            </AnchorLink>
          </Title>
          <Group gap={6} role="group" aria-label="Status">
            <RunStatusBadge status={run.status} />
            {isReplay(run) && (
              <Badge size="sm" variant="outline" color="gray" title="Answered from stored fixtures">
                replay
              </Badge>
            )}
            {run.cancel_requested_at && running && (
              <Badge size="sm" variant="light" color="gray">
                cancel requested
              </Badge>
            )}
          </Group>
        </Stack>
        <Group gap="xs">
          {running && (
            <Button
              variant="light"
              color="red"
              leftSection={<IconPlayerStop size={14} />}
              loading={cancel.isPending}
              disabled={run.cancel_requested_at !== null}
              onClick={() => void requestCancel()}
            >
              Cancel
            </Button>
          )}
          <Button
            variant="light"
            leftSection={<IconPlayerPlay size={14} />}
            loading={start.isPending}
            disabled={running}
            title={running ? 'The run is still running.' : 'Start a new run with the same mode and parameters.'}
            onClick={() => void runAgain()}
          >
            Run again
          </Button>
        </Group>
      </Group>
      {problem && (
        <Alert color="orange" variant="light">
          {problem}
        </Alert>
      )}

      <dl className={classes.stats} aria-label="Run">
        <Fact label="Started">
          <Timestamp value={run.started_at} />
        </Fact>
        <Fact label="Finished">
          <Timestamp value={run.finished_at} />
        </Fact>
        <Fact label="Duration">{formatDuration(run.duration_s)}</Fact>
        {running && (
          <Fact label="Last heartbeat">
            <Timestamp value={run.heartbeat_at} />
          </Fact>
        )}
        <Fact label="Trigger">{run.trigger}</Fact>
        <Fact label="Mode">{run.mode}</Fact>
        <Fact label="Parameters">{formatParams(run.params)}</Fact>
        <Fact label="Code version">
          <code>{run.code_version}</code>
        </Fact>
        <Fact label="Complete listing">{run.complete_listing ? 'yes' : 'no'}</Fact>
      </dl>

      {run.error && (
        <Alert color="red" variant="light" icon={<IconAlertTriangle size={18} />} title="The run failed">
          <Text size="sm" className={classes.message}>
            {run.error}
          </Text>
        </Alert>
      )}

      <StatsGrid stats={run.stats} />

      <Group justify="space-between" align="center">
        <Title order={2}>Details</Title>
        <AnchorLink to="/review" search={{ run_id: run.id, state: 'all' }} size="sm">
          Proposals of this run
        </AnchorLink>
      </Group>
      <Tabs
        value={tab}
        keepMounted={false}
        onChange={(value) => {
          setSearch((previous) => {
            const next = withParam(previous, 'tab', value === 'messages' ? null : value);
            return withParam(withParam(next, 'level', null), 'outcome', null);
          });
        }}
      >
        <Tabs.List mb="sm">
          <Tabs.Tab value="messages">
            Messages ({(run.message_counts.error ?? 0) + (run.message_counts.warning ?? 0) + (run.message_counts.info ?? 0)})
          </Tabs.Tab>
          <Tabs.Tab value="fetches">Fetch log</Tabs.Tab>
          <Tabs.Tab value="changes">Changes</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="messages">
          <MessagesPanel run={run} {...url} />
        </Tabs.Panel>
        <Tabs.Panel value="fetches">
          <FetchesPanel run={run} {...url} />
        </Tabs.Panel>
        <Tabs.Panel value="changes">
          <ChangesPanel run={run} {...url} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

function MessagesPanel({ run, search, setSearch }: { run: Run } & UrlState) {
  const messages = useRunMessages(run.id, listRequest(search, 'level'), run.status === 'running');
  const counts = run.message_counts;
  const levels = [
    { value: '', label: 'All' },
    { value: 'error', label: `Errors (${counts.error ?? 0})` },
    { value: 'warning', label: `Warnings (${counts.warning ?? 0})` },
    { value: 'info', label: `Info (${counts.info ?? 0})` },
  ];
  return (
    <Stack gap="sm">
      <SegmentedFilter
        label="Level"
        data={levels}
        value={search.level ?? ''}
        onChange={(value) => {
          setSearch((previous) => withParam(previous, 'level', value));
        }}
      />
      {messages.isError ? (
        <ErrorAlert title="Could not load the messages" error={messages.error} onRetry={() => void messages.refetch()} />
      ) : messages.isPending ? (
        <Loader size="sm" />
      ) : (
        <>
          <div aria-busy={messages.isPlaceholderData}>
            <RunMessagesTable messages={messages.data.items} refs={messages.data.refs} />
          </div>
          {messages.data.total > 0 && <FeedPagination total={messages.data.total} search={search} setSearch={setSearch} />}
        </>
      )}
    </Stack>
  );
}

function FetchesPanel({ run, search, setSearch }: { run: Run } & UrlState) {
  const fetches = useRunFetches(run.id, listRequest(search, 'outcome'), run.status === 'running');
  return (
    <Stack gap="sm">
      <Select
        size="xs"
        w={220}
        label="Outcome"
        placeholder="Any"
        clearable
        data={FETCH_OUTCOMES.map((outcome) => ({ value: outcome, label: outcome }))}
        value={search.outcome ?? null}
        onChange={(value) => {
          setSearch((previous) => withParam(previous, 'outcome', value));
        }}
        comboboxProps={{ withinPortal: true }}
      />
      {fetches.isError ? (
        <ErrorAlert title="Could not load the fetch log" error={fetches.error} onRetry={() => void fetches.refetch()} />
      ) : fetches.isPending ? (
        <Loader size="sm" />
      ) : (
        <>
          <div aria-busy={fetches.isPlaceholderData}>
            <FetchLogTable entries={fetches.data.items} />
          </div>
          {fetches.data.total > 0 && <FeedPagination total={fetches.data.total} search={search} setSearch={setSearch} />}
        </>
      )}
    </Stack>
  );
}

function ChangesPanel({ run, search, setSearch }: { run: Run } & UrlState) {
  const meta = useMeta();
  const navigate = useNavigate();
  const feed = useChangeFeed({ ...listRequest(search, 'run_id'), run_id: run.id });
  if (meta.isPending || feed.isPending) return <Loader size="sm" />;
  if (meta.isError) return <ErrorAlert title="Could not load the metadata" error={meta.error} onRetry={() => void meta.refetch()} />;
  if (feed.isError) return <ErrorAlert title="Could not load the changes" error={feed.error} onRetry={() => void feed.refetch()} />;
  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          {feed.data.total === 0 ? 'This run changed no records.' : `${feed.data.total} revisions written by this run.`}
        </Text>
        <AnchorLink to="/changes" search={{ run_id: run.id }} size="sm">
          Open in Recent changes
        </AnchorLink>
      </Group>
      {feed.data.items.length > 0 && (
        <ChangeFeedTable
          items={feed.data.items}
          meta={meta.data}
          batchFilter={undefined}
          onShowBatch={(batchId) => {
            void navigate({ to: '/changes', search: { batch_id: batchId } });
          }}
        />
      )}
      {feed.data.total > 0 && <FeedPagination total={feed.data.total} search={search} setSearch={setSearch} />}
    </Stack>
  );
}
