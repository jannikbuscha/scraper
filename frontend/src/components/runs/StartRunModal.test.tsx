import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { exampleCollector, exampleRun } from '../../test/acquisition-fixtures';
import { callsTo, jsonBody, mockApi } from '../../test/api-mock';
import { renderRoute } from '../../test/render';
import { StartRunModal } from './StartRunModal';

const COLLECTORS = {
  collectors: [
    exampleCollector({ params: ['limit', 'refetch'], needs_server_check: true }),
    exampleCollector({
      name: 'example_unavailable',
      label: 'Example unavailable collector',
      available: false,
      unavailable_reason: 'contact_email_missing',
    }),
  ],
};

function renderModal(startResponse: (init: RequestInit | undefined) => unknown) {
  const fetchMock = mockApi((url, init) => {
    if (url.pathname === '/api/collectors') return COLLECTORS;
    if (url.pathname === '/api/runs' && init?.method === 'POST') return startResponse(init);
    return undefined;
  });
  const Page = () => <StartRunModal opened onClose={vi.fn()} />;
  return { ...renderRoute(Page, { url: '/runs', path: '/runs' }), fetchMock };
}

describe('Start run (docs/UI.md §8.3)', () => {
  it('disables unavailable collectors with their reason and sends mode and parameters', async () => {
    const { user, fetchMock, router } = renderModal(() => ({ run: exampleRun({ id: 'run_NEW' }) }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.click(dialog.getByRole('combobox', { name: 'Collector' }));
    const unavailable = await screen.findByRole('option', { name: /Example unavailable collector/ });
    expect(unavailable).toHaveAttribute('aria-disabled', 'true');
    expect(unavailable).toHaveTextContent('CONTACT_EMAIL is not set in .env');
    await user.click(screen.getByRole('option', { name: /^Example collector/ }));

    expect(dialog.getByText('Needs checks from the target server')).toBeInTheDocument();
    await user.click(dialog.getByText('full'));
    await user.type(dialog.getByRole('textbox', { name: /Limit/ }), '5');
    await user.click(dialog.getByRole('button', { name: 'Start run' }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/runs/run_NEW');
    });
    expect(jsonBody(callsTo(fetchMock, '/api/runs')[0]?.init)).toEqual({
      collector: 'example_collector',
      mode: 'full',
      params: { limit: 5 },
    });
  });

  it('explains that another run is running and links to it', async () => {
    const { user } = renderModal(
      () =>
        new Response(JSON.stringify({ error: { code: 'run_in_progress', message: 'Busy', details: { run_id: 'run_BUSY' } } }), {
          status: 409,
          headers: { 'Content-Type': 'application/json' },
        }),
    );
    const dialog = within(await screen.findByRole('dialog'));
    await user.click(dialog.getByRole('combobox', { name: 'Collector' }));
    await user.click(await screen.findByRole('option', { name: /^Example collector/ }));
    await user.click(dialog.getByRole('button', { name: 'Start run' }));
    expect(await dialog.findByText(/Another run is running/)).toBeInTheDocument();
    expect(dialog.getByRole('link', { name: 'Open the running run' })).toHaveAttribute('href', '/runs/run_BUSY');
  });
});
