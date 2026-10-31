// Collectors and runs (docs/API.md §7.2): reads, start and cancel, and the
// polling of running runs (docs/UI.md §8.3): a list or run page refetches
// every 3 s while a run it shows is running, and when such a run turns
// finished the data queries are invalidated, because a run changes data.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { canonicalQuery, type SearchRecord } from '../lib/query-string';
import type {
  CollectorResponse,
  CollectorsResponse,
  FetchLogResponse,
  PageOf,
  Run,
  RunMessagesResponse,
  RunResponse,
  StartRunRequest,
} from './acquisition-types';
import { apiGet, apiWrite } from './client';
import { invalidateKeys, keysAfterRunChange, keysAfterRunFinished, queryKeys, useMutationWithKeys } from './queries';

/** Polling interval while a shown run is running. */
export const RUN_POLL_MS = 3000;

const runPath = (id: string): string => `/api/runs/${encodeURIComponent(id)}`;

/** 3 s while any of the runs is running, else no polling. */
export function runPollInterval(runs: readonly Pick<Run, 'status'>[] | undefined): number | false {
  return runs?.some((run) => run.status === 'running') ? RUN_POLL_MS : false;
}

/**
 * Invalidates the data queries once for every run that was running in an
 * earlier render and is now shown finished (keysAfterRunFinished).
 */
function useInvalidateWhenFinished(runs: readonly Pick<Run, 'id' | 'status'>[] | undefined): void {
  const client = useQueryClient();
  const running = useRef<ReadonlySet<string>>(new Set());
  useEffect(() => {
    if (runs === undefined) return;
    const finished = runs.filter((run) => run.status !== 'running' && running.current.has(run.id));
    running.current = new Set(runs.filter((run) => run.status === 'running').map((run) => run.id));
    for (const run of finished) void invalidateKeys(client, keysAfterRunFinished(run.id));
  }, [client, runs]);
}

/** `pollWhileRunning`: the sources page refetches every 3 s while a collector is running. */
export function useCollectors(options: { pollWhileRunning?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.collectors,
    queryFn: ({ signal }) => apiGet<CollectorsResponse>('/api/collectors', '', signal),
    refetchInterval: (query) =>
      options.pollWhileRunning && query.state.data?.collectors.some((collector) => collector.running_run_id !== null)
        ? RUN_POLL_MS
        : false,
  });
}

export function useCollector(name: string) {
  return useQuery({
    queryKey: queryKeys.collector(name),
    queryFn: ({ signal }) => apiGet<CollectorResponse>(`/api/collectors/${encodeURIComponent(name)}`, '', signal),
    refetchInterval: (query) => runPollInterval(query.state.data?.recent_runs),
  });
}

/** Runs, newest first: `collector, status, trigger, page, page_size`; polls while a listed run is running. */
export function useRuns(search: SearchRecord) {
  const qs = canonicalQuery(search);
  const query = useQuery({
    queryKey: queryKeys.runList(qs),
    queryFn: ({ signal }) => apiGet<PageOf<Run>>('/api/runs', qs, signal),
    placeholderData: keepPreviousData,
    refetchInterval: (current) => runPollInterval(current.state.data?.items),
  });
  useInvalidateWhenFinished(query.isPlaceholderData ? undefined : query.data?.items);
  return query;
}

/** One run; polls every 3 s while it is running and invalidates the data when it finishes. */
export function useRun(id: string) {
  const query = useQuery({
    queryKey: queryKeys.run(id),
    queryFn: ({ signal }) => apiGet<RunResponse>(runPath(id), '', signal),
    refetchInterval: (current) => runPollInterval(current.state.data ? [current.state.data.run] : undefined),
  });
  const run = query.data?.run;
  useInvalidateWhenFinished(run ? [run] : undefined);
  return query;
}

/** The fetch log of a run: `outcome, host, purpose, page, page_size`; `poll` while the run is running. */
export function useRunFetches(id: string, search: SearchRecord, poll: boolean) {
  const qs = canonicalQuery(search);
  return useQuery({
    queryKey: queryKeys.runFetches(id, qs),
    queryFn: ({ signal }) => apiGet<FetchLogResponse>(`${runPath(id)}/fetches`, qs, signal),
    placeholderData: keepPreviousData,
    refetchInterval: poll ? RUN_POLL_MS : false,
  });
}

/** The messages of a run: `level, code, page, page_size`; `poll` while the run is running. */
export function useRunMessages(id: string, search: SearchRecord, poll: boolean) {
  const qs = canonicalQuery(search);
  return useQuery({
    queryKey: queryKeys.runMessages(id, qs),
    queryFn: ({ signal }) => apiGet<RunMessagesResponse>(`${runPath(id)}/messages`, qs, signal),
    placeholderData: keepPreviousData,
    refetchInterval: poll ? RUN_POLL_MS : false,
  });
}

/** POST /api/runs: `202 {run}`. */
/**
 * POST /api/runs. The answer (the run, still running) seeds the run's query, so
 * a page that follows the run sees it running first and refreshes the data when
 * it finishes, even if a short run (the tagger, a replayed run) has finished
 * before the page's first request.
 */
export function useStartRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: StartRunRequest) => apiWrite<RunResponse>('POST', '/api/runs', body),
    onSuccess: async (result) => {
      await invalidateKeys(client, keysAfterRunChange(result.run.id));
      client.setQueryData<RunResponse>(queryKeys.run(result.run.id), result);
    },
  });
}

/** POST /api/runs/{id}/cancel. */
export function useCancelRun() {
  return useMutationWithKeys(
    ({ id }: { id: string }) => apiWrite<RunResponse>('POST', `${runPath(id)}/cancel`, {}),
    ({ id }) => keysAfterRunChange(id),
  );
}

/** Download address of a stored snapshot body (always an attachment, docs/API.md §7.3). */
export const snapshotBodyUrl = (snapshotId: string): string => `/api/snapshots/${encodeURIComponent(snapshotId)}/body`;
