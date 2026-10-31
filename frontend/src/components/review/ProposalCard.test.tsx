import { screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Proposal } from '../../api/acquisition-types';
import { exampleProposal, p2Meta, p2Vocabularies } from '../../test/acquisition-fixtures';
import { mockApi } from '../../test/api-mock';
import { exampleItem } from '../../test/fixtures';
import { renderRoute } from '../../test/render';
import { ProposalCard, type CardAction } from './ProposalCard';

const subject = exampleItem(
  'prj_A',
  { name_en: 'Example project A', description_uk: 'Manual example text about the portal', official_urls: ['https://example.org/a'] },
  {
    field_meta: {
      description_uk: {
        src: 'manual',
        by: 'user',
        at: '2026-01-01T00:00:00.000000Z',
        locked: true,
        verified: 'unverified',
        evidence_id: null,
        restored_from_version: null,
      },
    },
  },
);

function renderCard(proposal: Proposal, onAction: (action: CardAction) => void = vi.fn()) {
  mockApi((url) => (url.pathname === '/api/entities/project/prj_A' ? { item: subject } : undefined));
  const Page = () => (
    <ProposalCard
      proposal={proposal}
      refs={{ prj_A: { id: 'prj_A', type: 'project', label: 'Example project A', deleted: false } }}
      meta={p2Meta}
      expanded={false}
      onToggleExpanded={vi.fn()}
      selected={false}
      onSelect={vi.fn()}
      onAction={onAction}
      busy={false}
    />
  );
  return renderRoute(Page, { url: '/review', path: '/review', vocabularies: p2Vocabularies });
}

describe('proposal value rendering (docs/UI.md §8.2)', () => {
  it('shows a long text as a word diff of current (with provenance) and proposed', async () => {
    renderCard(
      exampleProposal({
        field: 'description_uk',
        live_value: 'Manual example text about the portal',
        current_value: 'Manual example text about the portal',
        proposed_value: 'Collected example text about the portal',
      }),
    );
    const card = await screen.findByRole('article');
    expect(await within(card).findByText('manual')).toBeInTheDocument();
    expect(within(card).getByRole('img', { name: 'Locked' })).toBeInTheDocument();
    expect(within(card).getByText('collector')).toBeInTheDocument();
    const removed = card.querySelector('del');
    const added = card.querySelector('ins');
    expect(removed).toHaveTextContent('Manual');
    expect(added).toHaveTextContent('Collected');
  });

  it('marks added and removed list items', async () => {
    renderCard(
      exampleProposal({
        field: 'policy_domains',
        live_value: ['domain_a'],
        current_value: ['domain_a'],
        proposed_value: ['domain_b'],
      }),
    );
    const list = await screen.findByRole('group', { name: 'Proposed list' });
    expect(within(list).getByText('Example domain B').closest('[title]')).toHaveAttribute('title', 'added');
    expect(within(list).getByText('Example domain A').closest('[title]')).toHaveAttribute('title', 'removed');
  });

  it('shows only the new URLs of an add-only list as additions', async () => {
    renderCard(
      exampleProposal({
        field: 'official_urls',
        live_value: ['https://example.org/a'],
        current_value: ['https://example.org/a'],
        proposed_value: ['https://example.org/b'],
      }),
    );
    const additions = await screen.findByRole('group', { name: 'URLs to add' });
    expect(within(additions).getByRole('link', { name: 'https://example.org/b' })).toBeInTheDocument();
    expect(within(additions).queryByRole('link', { name: 'https://example.org/a' })).toBeNull();
  });

  it('offers the decisions of the kind', async () => {
    renderCard(exampleProposal({ kind: 'possible_duplicate', field: null, related_id: 'prj_B', entity_type: 'project' }));
    const card = await screen.findByRole('article');
    expect(within(card).getByRole('button', { name: 'Merge…' })).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Not duplicates…' })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Accept' })).toBeNull();
  });

  it('accepts a text version only as it is', async () => {
    renderCard(exampleProposal({ entity_type: 'project', field: 'text_hash', payload: { char_count: 120 } }));
    const card = await screen.findByRole('article');
    expect(within(card).getByRole('button', { name: 'Accept' })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Edit & accept…' })).toBeNull();
    expect(within(card).getByText(/120 characters/)).toBeInTheDocument();
  });
});
