import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { ProposalListResponse, ProposalSummary } from '../api/acquisition-types';
import { exampleProposal, p2Meta, p2Vocabularies } from '../test/acquisition-fixtures';
import { callsTo, jsonBody, mockApi, requestsTo } from '../test/api-mock';
import { exampleItem } from '../test/fixtures';
import { renderRoute } from '../test/render';
import { ReviewPage } from './ReviewPage';

const LIST: ProposalListResponse = {
  items: [
    exampleProposal({ id: 'prp_FIELD' }),
    exampleProposal({
      id: 'prp_NEW',
      kind: 'create_entity',
      subject_id: null,
      field: null,
      live_value: null,
      proposed_value: null,
      payload: { fields: { name_uk: 'Приклад' }, candidates: [] },
    }),
  ],
  total: 2,
  page: 1,
  page_size: 50,
  refs: { prj_A: { id: 'prj_A', type: 'project', label: 'Example project A', deleted: false } },
};

const SUMMARY: ProposalSummary = {
  open: 2,
  by_kind: { update_field: 1, create_entity: 1 },
  by_collector: { example_collector: 2 },
  by_entity_type: { project: 2 },
  patterns: [{ pattern_id: 'example_pattern', open: 1, accepted: 3, accepted_modified: 1, rejected: 4, precision: 0.5 }],
};

function mockReview() {
  return mockApi((url, init) => {
    if (url.pathname === '/api/meta') return p2Meta;
    if (url.pathname === '/api/proposals/summary') return SUMMARY;
    if (url.pathname === '/api/proposals/bulk' && init?.method === 'POST') {
      return {
        batch_id: 'batch_X',
        results: [
          { id: 'prp_FIELD', status: 'accepted', error: null },
          { id: 'prp_NEW', status: 'needs_values', error: null },
        ],
      };
    }
    if (url.pathname === '/api/proposals') return LIST;
    if (url.pathname === '/api/entities/project/prj_A') return { item: exampleItem('prj_A', { name_en: 'Example name' }) };
    if (url.pathname === '/api/collectors') return { collectors: [] };
    if (url.pathname === '/api/lookup') return { items: [] };
    return undefined;
  });
}

describe('Review inbox (docs/UI.md §8.2)', () => {
  it('passes the URL filters to the API and removes a chip filter', async () => {
    const fetchMock = mockReview();
    const { user, router } = renderRoute(ReviewPage, {
      url: '/review?run_id=run_EXAMPLE&kind=update_field&proposal=prp_FIELD',
      path: '/review',
      vocabularies: p2Vocabularies,
    });
    expect(await screen.findByRole('tab', { name: 'Proposals (2)' })).toBeInTheDocument();
    await waitFor(() => {
      expect(requestsTo(fetchMock, '/api/proposals').length).toBeGreaterThan(0);
    });
    // The page-state parameter `proposal` is not sent.
    expect(Object.fromEntries(requestsTo(fetchMock, '/api/proposals')[0]?.searchParams ?? [])).toEqual({
      run_id: 'run_EXAMPLE',
      kind: 'update_field',
    });
    await user.click(await screen.findByRole('button', { name: 'Remove the filter Run: run_EXAMPLE' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ kind: 'update_field', proposal: 'prp_FIELD' });
    });
  });

  it('bulk-accepts the selection and lists what was left open', async () => {
    const fetchMock = mockReview();
    const { user } = renderRoute(ReviewPage, { url: '/review', path: '/review', vocabularies: p2Vocabularies });
    await user.click(await screen.findByRole('checkbox', { name: 'Select proposal prp_FIELD' }));
    await user.click(screen.getByRole('checkbox', { name: 'Select proposal prp_NEW' }));
    await user.click(screen.getByRole('button', { name: 'Accept selected' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Accept the selected proposals' }));
    await user.click(dialog.getByRole('button', { name: 'Accept 2' }));
    expect(await dialog.findByText('Accepted: 1')).toBeInTheDocument();
    expect(dialog.getByText('Left open: needs your values: 1')).toBeInTheDocument();
    expect(dialog.getByRole('heading', { name: 'Left open: needs your values' })).toBeInTheDocument();
    expect(jsonBody(callsTo(fetchMock, '/api/proposals/bulk')[0]?.init)).toEqual({
      action: 'accept',
      note: null,
      ids: ['prp_FIELD', 'prp_NEW'],
    });
  });

  it('shows the pattern precision of event proposals', async () => {
    mockReview();
    const { user } = renderRoute(ReviewPage, { url: '/review', path: '/review', vocabularies: p2Vocabularies });
    await user.click(await screen.findByRole('button', { name: /Pattern precision/ }));
    const table = await screen.findByRole('table');
    expect(within(table).getByText('example_pattern')).toBeInTheDocument();
    expect(within(table).getByText('50%')).toBeInTheDocument();
  });
});
