import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { mockApi, requestsTo } from '../test/api-mock';
import { exampleRun } from '../test/acquisition-fixtures';
import type { RunStatus } from './acquisition-types';
import { RUN_POLL_MS, runPollInterval, useRun, useStartRun } from './runs';

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe('run polling (docs/UI.md §8.3)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('polls only while a run is running', () => {
    expect(runPollInterval([{ status: 'running' }])).toBe(RUN_POLL_MS);
    expect(runPollInterval([{ status: 'succeeded' }, { status: 'running' }])).toBe(RUN_POLL_MS);
    expect(runPollInterval([{ status: 'partial' }, { status: 'cancelled' }])).toBe(false);
    expect(runPollInterval(undefined)).toBe(false);
  });

  it('stops polling and invalidates the data once the run has finished', async () => {
    const statuses: RunStatus[] = ['running', 'running', 'partial'];
    const fetchMock = mockApi((url) =>
      url.pathname === '/api/runs/run_EXAMPLE' ? { run: exampleRun({ status: statuses.shift() ?? 'partial' }) } : undefined,
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useRun('run_EXAMPLE'), { wrapper: wrapper(client) });

    await waitFor(() => {
      expect(result.current.data?.run.status).toBe('running');
    });
    expect(invalidate).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(RUN_POLL_MS);
    await vi.advanceTimersByTimeAsync(RUN_POLL_MS);
    await waitFor(() => {
      expect(result.current.data?.run.status).toBe('partial');
    });
    const calls = requestsTo(fetchMock, '/api/runs/run_EXAMPLE').length;
    expect(calls).toBe(3);
    // A run changes data: lists, items and the inbox are refreshed.
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['list'] });
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['proposals'] });

    // No further requests once it has finished.
    await vi.advanceTimersByTimeAsync(RUN_POLL_MS * 4);
    expect(requestsTo(fetchMock, '/api/runs/run_EXAMPLE')).toHaveLength(calls);
  });

  it('invalidates the data for a started run that finished before its first poll', async () => {
    // The tagger and replayed runs can finish before the run's first GET.
    mockApi((url, init) => {
      if (url.pathname === '/api/runs' && init?.method === 'POST') return { run: exampleRun({ status: 'running' }) };
      if (url.pathname === '/api/runs/run_EXAMPLE') return { run: exampleRun({ status: 'succeeded' }) };
      return undefined;
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const start = renderHook(() => useStartRun(), { wrapper: wrapper(client) });
    await act(async () => {
      await start.result.current.mutateAsync({ collector: 'tagger', params: { document_ids: ['doc_EXAMPLE'] } });
    });
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useRun('run_EXAMPLE'), { wrapper: wrapper(client) });
    await waitFor(() => {
      expect(result.current.data?.run.status).toBe('succeeded');
    });
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['item'] });
    });
  });

  it('does not invalidate for a run that was already finished when loaded', async () => {
    mockApi((url) => (url.pathname === '/api/runs/run_EXAMPLE' ? { run: exampleRun({ status: 'succeeded' }) } : undefined));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useRun('run_EXAMPLE'), { wrapper: wrapper(client) });
    await waitFor(() => {
      expect(result.current.data?.run.status).toBe('succeeded');
    });
    await vi.advanceTimersByTimeAsync(RUN_POLL_MS * 2);
    expect(invalidate).not.toHaveBeenCalled();
  });
});
