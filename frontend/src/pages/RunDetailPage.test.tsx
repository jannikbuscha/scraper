import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { RunMessagesResponse } from '../api/acquisition-types';
import externalLinkClasses from '../components/ExternalLink.module.css';
import { emptyStats, exampleRun } from '../test/acquisition-fixtures';
import { callsTo, jsonBody, mockApi } from '../test/api-mock';
import { renderRoute } from '../test/render';
import { RunDetailPage } from './RunDetailPage';

const FAILED = exampleRun({
  status: 'failed',
  finished_at: '2026-01-01T10:05:00.000000Z',
  mode: 'full',
  params: { limit: 3, replay: true },
  error: 'example.org: blocked',
  stats: emptyStats({ requests: 12, entities_updated: 4, extra: { example_counter: 7 } }),
  message_counts: { error: 1, warning: 0, info: 0 },
});

const MESSAGES: RunMessagesResponse = {
  items: [
    {
      id: 1,
      at: '2026-01-01T10:01:00.000000Z',
      level: 'error',
      code: 'http_error',
      message: 'Example request failed',
      url: 'https://example.org/page',
      raw_snapshot_id: null,
      subject_id: 'prj_A',
      details: {},
    },
  ],
  total: 1,
  page: 1,
  page_size: 50,
  refs: { prj_A: { id: 'prj_A', type: 'project', label: 'Example project A', deleted: false } },
};

describe('run page (docs/UI.md §8.3)', () => {
  it('shows the fatal error, every counter and the messages; Run again repeats mode and parameters', async () => {
    const fetchMock = mockApi((url, init) => {
      if (url.pathname === '/api/runs/run_EXAMPLE') return { run: FAILED };
      if (url.pathname === '/api/runs/run_EXAMPLE/messages') return MESSAGES;
      if (url.pathname === '/api/runs' && init?.method === 'POST') return { run: exampleRun({ id: 'run_AGAIN' }) };
      return undefined;
    });
    const { user, router } = renderRoute(RunDetailPage, { url: '/runs/run_EXAMPLE', path: '/runs/$id' });

    expect(await screen.findByText('example.org: blocked')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Status' })).toHaveTextContent('failed');
    expect(screen.getByRole('group', { name: 'Status' })).toHaveTextContent('replay');
    const stats = screen.getByRole('region', { name: 'Statistics' });
    expect(within(stats).getByText('Records updated').nextElementSibling).toHaveTextContent('4');
    expect(within(stats).getByText('example_counter').nextElementSibling).toHaveTextContent('7');
    expect(screen.getByRole('link', { name: 'Proposals of this run' })).toHaveAttribute('href', '/review?run_id=run_EXAMPLE&state=all');

    const messages = await screen.findByRole('row', { name: /Example request failed/ });
    expect(within(messages).getByRole('link', { name: 'Example project A' })).toBeInTheDocument();
    // The URL wraps instead of widening the table (docs/UI.md §1.4, §8.3).
    expect(within(messages).getByRole('link', { name: 'https://example.org/page' }).parentElement).toHaveClass(
      externalLinkClasses.wrap ?? 'missing-wrap-class',
    );
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Run again' }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/runs/run_AGAIN');
    });
    // `replay` is recorded by the server, never sent.
    expect(jsonBody(callsTo(fetchMock, '/api/runs')[0]?.init)).toEqual({ collector: 'example_collector', mode: 'full', params: { limit: 3 } });
  });

  it('says that a page of messages or requests is past the end instead of "No messages"', async () => {
    mockApi((url) => {
      if (url.pathname === '/api/runs/run_EXAMPLE') return { run: FAILED };
      // Page 3 of 13 messages at 50 per page, e.g. from an old link.
      if (url.pathname === '/api/runs/run_EXAMPLE/messages') return { ...MESSAGES, items: [], total: 13, page: 3 };
      if (url.pathname === '/api/runs/run_EXAMPLE/fetches') return { items: [], total: 17, page: 3, page_size: 50 };
      return undefined;
    });
    const { user, router } = renderRoute(RunDetailPage, { url: '/runs/run_EXAMPLE?page=3', path: '/runs/$id' });
    expect(await screen.findByText('This page is past the end of the list')).toBeInTheDocument();
    expect(screen.getByText('13 in total; the last page is page 1.')).toBeInTheDocument();
    expect(screen.queryByText('No messages.')).toBeNull();
    expect(screen.getByRole('navigation', { name: 'Pages' })).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Fetch log' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ tab: 'fetches' });
    });
    await router.navigate({ to: '/runs/$id', params: { id: 'run_EXAMPLE' }, search: { tab: 'fetches', page: '3' } });
    expect(await screen.findByText('17 in total; the last page is page 1.')).toBeInTheDocument();
    expect(screen.queryByText('No requests.')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Go to the last page' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ tab: 'fetches' });
    });
  });

  it('offers Cancel while the run is running', async () => {
    let cancelled = false;
    const fetchMock = mockApi((url, init) => {
      if (url.pathname === '/api/runs/run_EXAMPLE/cancel' && init?.method === 'POST') {
        cancelled = true;
        return { run: exampleRun({ cancel_requested_at: '2026-01-01T10:00:40.000000Z' }) };
      }
      if (url.pathname === '/api/runs/run_EXAMPLE') {
        return { run: exampleRun(cancelled ? { cancel_requested_at: '2026-01-01T10:00:40.000000Z' } : {}) };
      }
      if (url.pathname === '/api/runs/run_EXAMPLE/messages') return { ...MESSAGES, items: [], total: 0 };
      return undefined;
    });
    const { user } = renderRoute(RunDetailPage, { url: '/runs/run_EXAMPLE', path: '/runs/$id' });
    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    await waitFor(() => {
      expect(callsTo(fetchMock, '/api/runs/run_EXAMPLE/cancel')).toHaveLength(1);
    });
    expect(await screen.findByText('cancel requested')).toBeInTheDocument();
  });
});
