import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { Proposal, ProposalListResponse, ProposalSummary } from '../api/acquisition-types';
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

/** An inbox of `cards`, `pageSize` per page; `decided` cards have left the open list. */
function mockPagedInbox(cards: Proposal[], pageSize: number, extra: (url: URL, init: RequestInit | undefined) => unknown = () => undefined) {
  const decided = new Set<string>();
  const fetchMock = mockApi((url, init) => {
    const answer = extra(url, init);
    if (answer !== undefined) return answer;
    if (url.pathname === '/api/meta') return p2Meta;
    if (url.pathname === '/api/proposals/summary') return { ...SUMMARY, open: cards.length - decided.size };
    const reject = /^\/api\/proposals\/([^/]+)\/reject$/.exec(url.pathname);
    if (reject?.[1] && init?.method === 'POST') {
      decided.add(reject[1]);
      return { proposal: { ...cards.find((card) => card.id === reject[1]), state: 'rejected' } };
    }
    if (url.pathname === '/api/proposals') {
      const page = Number(url.searchParams.get('page') ?? '1');
      const open = cards.filter((card) => !decided.has(card.id));
      return { items: open.slice((page - 1) * pageSize, page * pageSize), total: open.length, page, page_size: pageSize, refs: LIST.refs };
    }
    if (url.pathname === '/api/entities/project/prj_A') return { item: exampleItem('prj_A', { name_en: 'Example name' }) };
    if (url.pathname === '/api/collectors') return { collectors: [] };
    if (url.pathname === '/api/lookup') return { items: [] };
    return undefined;
  });
  return fetchMock;
}

describe('Review inbox paging (docs/UI.md §8.1, §8.2)', () => {
  it('keeps the page when a card is expanded or collapsed, so the card is not shown again as a linked proposal', async () => {
    mockPagedInbox([exampleProposal({ id: 'prp_ONE' }), exampleProposal({ id: 'prp_TWO' })], 1);
    const { user, router } = renderRoute(ReviewPage, { url: '/review?page=2&page_size=1', path: '/review', vocabularies: p2Vocabularies });
    expect(await screen.findByRole('checkbox', { name: 'Select proposal prp_TWO' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Details' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ page: '2', page_size: '1', proposal: 'prp_TWO' });
    });
    expect(screen.getAllByRole('article')).toHaveLength(1);
    expect(screen.queryByText('Linked proposal')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Less' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ page: '2', page_size: '1' });
    });
  });

  it('says that a page is past the end, instead of "No open proposals", after its last card was decided', async () => {
    mockPagedInbox([exampleProposal({ id: 'prp_ONE' }), exampleProposal({ id: 'prp_TWO' })], 1);
    const { user, router } = renderRoute(ReviewPage, { url: '/review?page=2&page_size=1', path: '/review', vocabularies: p2Vocabularies });
    await user.click(await screen.findByRole('button', { name: 'Reject…' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Reject proposal' }));
    await user.type(dialog.getByRole('textbox', { name: /Reason/ }), 'Example reason');
    await user.click(dialog.getByRole('button', { name: 'Reject' }));

    expect(await screen.findByText('This page is past the end of the list')).toBeInTheDocument();
    expect(screen.getByText('1 in total; the last page is page 1.')).toBeInTheDocument();
    expect(screen.queryByText('No open proposals')).toBeNull();
    expect(screen.getByText('Rejected the proposal.')).toBeInTheDocument();
    // The footer keeps its page links, with no page marked current.
    const pages = screen.getByRole('navigation', { name: 'Pages' });
    expect(within(pages).getByRole('button', { name: 'Page 1' })).not.toHaveAttribute('data-active');

    await user.click(screen.getByRole('button', { name: 'Go to the last page' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ page_size: '1' });
    });
    expect(await screen.findByRole('checkbox', { name: 'Select proposal prp_ONE' })).toBeInTheDocument();
  });

  it('shows "No open proposals" only when there are none', async () => {
    mockPagedInbox([], 50);
    renderRoute(ReviewPage, { url: '/review?page=3', path: '/review', vocabularies: p2Vocabularies });
    expect(await screen.findByText('No open proposals')).toBeInTheDocument();
    expect(screen.queryByText('This page is past the end of the list')).toBeNull();
  });
});

describe('Review decisions in dialogs (docs/UI.md §8.2)', () => {
  it('words linking to an existing record as linking, not as a new record', async () => {
    const created = exampleProposal({
      id: 'prp_NEW',
      kind: 'create_entity',
      subject_id: null,
      field: null,
      live_value: null,
      proposed_value: null,
      payload: { fields: { name_uk: 'Приклад' }, candidates: ['prj_B'] },
    });
    const fetchMock = mockPagedInbox([created], 50, (url, init) => {
      if (url.pathname === '/api/proposals') {
        return {
          items: [created],
          total: 1,
          page: 1,
          page_size: 50,
          refs: { prj_B: { id: 'prj_B', type: 'project', label: 'Example project B', deleted: false } },
        };
      }
      if (url.pathname === '/api/proposals/prp_NEW/accept' && init?.method === 'POST') {
        return { proposal: { ...created, state: 'accepted_modified', result_id: 'prj_B' }, changed: true, result_id: 'prj_B', revision_ids: [], batch_id: null };
      }
      if (url.pathname === '/api/lookup') {
        return { items: [{ id: 'prj_B', type: 'project', label: 'Example project B', deleted: false, context: null }] };
      }
      return undefined;
    });
    const { user } = renderRoute(ReviewPage, { url: '/review', path: '/review', vocabularies: p2Vocabularies });
    await user.click(await screen.findByRole('button', { name: 'Link to Example project B' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Link to an existing record' }));
    await user.click(dialog.getByRole('button', { name: 'Link' }));

    const notice = within(await screen.findByRole('alert'));
    expect(notice.getByText(/Linked the source entry to an existing record; nothing else was written\./)).toBeInTheDocument();
    expect(screen.queryByText(/Accepted the new record/)).toBeNull();
    expect(await notice.findByRole('link', { name: 'Example project B' })).toHaveAttribute('href', '/projects/prj_B');
    expect(jsonBody(callsTo(fetchMock, '/api/proposals/prp_NEW/accept')[0]?.init)).toEqual({ match_id: 'prj_B', note: null });
  });

  it('chooses the duplicate document by its label and opens a document only from its own link', async () => {
    const pair = exampleProposal({
      id: 'prp_DUP',
      kind: 'possible_duplicate',
      entity_type: 'document',
      subject_id: 'doc_A',
      related_id: 'doc_B',
      field: null,
      current_value: null,
      proposed_value: null,
      live_value: null,
      payload: { basis: 'same_title', similarity: 0.9 },
    });
    const documentRefs = {
      doc_A: { id: 'doc_A', type: 'document' as const, label: 'Example document A', deleted: false },
      doc_B: { id: 'doc_B', type: 'document' as const, label: 'Example document B', deleted: false },
    };
    mockPagedInbox([pair], 50, (url) => {
      if (url.pathname === '/api/proposals') return { items: [pair], total: 1, page: 1, page_size: 50, refs: documentRefs };
      return undefined;
    });
    const { user, router } = renderRoute(ReviewPage, { url: '/review', path: '/review', vocabularies: p2Vocabularies });
    await user.click(await screen.findByRole('button', { name: 'Mark as duplicate…' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Mark as duplicate' }));
    expect(dialog.getByRole('button', { name: 'Mark as duplicate' })).toBeDisabled();

    // Clicking the title (the radio's label) chooses it and stays in the dialog.
    await user.click(dialog.getByText('Example document B'));
    expect(dialog.getByRole('radio', { name: 'Example document B' })).toBeChecked();
    expect(dialog.getByRole('button', { name: 'Mark as duplicate' })).toBeEnabled();
    expect(router.state.location.pathname).toBe('/review');

    const open = dialog.getByRole('link', { name: 'Open Example document B in a new tab' });
    expect(open).toHaveAttribute('href', '/documents/doc_B');
    expect(open).toHaveAttribute('target', '_blank');
  });
});
