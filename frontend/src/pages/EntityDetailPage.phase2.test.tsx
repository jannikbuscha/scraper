import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { Item, Meta } from '../api/types';
import { exampleObservation } from '../test/acquisition-fixtures';
import { callsTo, jsonBody, mockApi } from '../test/api-mock';
import { exampleItem, exampleMeta, exampleVocabularies, fieldSpec, listResponse, projectMeta } from '../test/fixtures';
import { renderRoute } from '../test/render';
import { EntityDetailPage } from './EntityDetailPage';

// Synthetic metadata and values; nothing here describes the real portfolio.
const META: Meta = {
  ...exampleMeta,
  groups: [...exampleMeta.groups, { key: 'sources', label: 'Sources & Evidence' }],
  entity_types: {
    project: {
      ...projectMeta,
      fields: [
        ...projectMeta.fields,
        fieldSpec('description_uk', 'text', { label: 'Description (UK)' }),
        fieldSpec('notes', 'text', { label: 'Notes', group: 'sources' }),
      ],
    },
  },
};

const collected = {
  src: 'collector:example_collector@run_EXAMPLE',
  by: 'collector:example_collector',
  at: '2026-01-01T00:00:00.000000Z',
  locked: false,
  verified: 'unverified' as const,
  evidence_id: null,
  restored_from_version: null,
  raw_snapshot_ids: ['raw_ONE', 'raw_TWO'],
};

function project(overrides: Partial<Item> = {}): Item {
  return exampleItem(
    'prj_A',
    { name_en: 'Example project A', description_uk: 'Example collected text', notes: null },
    {
      field_meta: { description_uk: collected },
      virtual: { open_comments: 0, comment_count: 0, open_proposals: 2, open_proposals_by_field: { description_uk: 1 } },
      observations: [exampleObservation({ key: 'entry:example-a', collector: 'example_collector' })],
      ...overrides,
    },
  );
}

function renderDetail(item: Item) {
  const fetchMock = mockApi((url, init) => {
    if (url.pathname === '/api/meta') return META;
    if (url.pathname === '/api/entities/project/prj_A' && (init?.method ?? 'GET') === 'GET') return { item };
    if (url.pathname === '/api/entities/project/prj_A/unmerge') {
      return { item: { ...item, deleted_at: null, merged_into: null }, merge_id: 'mrg_1', batch_id: 'b', revision_ids: [3], skipped: [] };
    }
    if (url.pathname === '/api/lookup') {
      return { items: [{ id: 'prj_SURVIVOR', type: 'project', label: 'Example survivor', deleted: false, context: null }] };
    }
    if (url.pathname.startsWith('/api/entities/')) return listResponse([]);
    if (url.pathname === '/api/comments') return { threads: [] };
    return undefined;
  });
  const DetailPage = () => <EntityDetailPage type="project" id="prj_A" />;
  const rendered = renderRoute(DetailPage, { url: '/projects/prj_A', path: '/projects/$id', vocabularies: exampleVocabularies });
  return { ...rendered, fetchMock };
}

describe('detail page additions (docs/UI.md §8.7)', () => {
  it('links the open proposals, offers the snapshots of a collected value and lists the observations', async () => {
    const { user } = renderDetail(project());
    const badge = await screen.findByRole('link', { name: '2 open proposals' });
    expect(badge).toHaveAttribute('href', '/review?subject_id=prj_A');
    expect(screen.getByRole('link', { name: '1 proposal' })).toHaveAttribute('href', '/review?field=description_uk&subject_id=prj_A');

    await user.click(screen.getByRole('button', { name: 'Provenance: collector:example_collector@run_EXAMPLE' }));
    const popover = within(await screen.findByRole('dialog'));
    expect(popover.getByRole('link', { name: 'run run_EXAMPLE' })).toHaveAttribute('href', '/runs/run_EXAMPLE');
    expect(popover.getByRole('link', { name: 'example_collector' })).toHaveAttribute('href', '/sources/example_collector');
    expect(popover.getByRole('link', { name: 'snapshot 2' })).toHaveAttribute('href', '/api/snapshots/raw_TWO/body');

    const seen = screen.getByRole('region', { name: 'Seen in sources' });
    expect(within(seen).getByText('entry:example-a')).toBeInTheDocument();
    expect(within(seen).getByText('matching rule')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Merge…' })).toBeInTheDocument();
  });

  it('opens the collector provenance from the keyboard: focus moves into it, and Escape closes it and returns to the badge', async () => {
    const { user } = renderDetail(project());
    const badge = await screen.findByRole('button', { name: 'Provenance: collector:example_collector@run_EXAMPLE' });
    badge.focus();
    await user.keyboard('{Enter}');
    const popover = await screen.findByRole('dialog');
    // The dropdown is portaled: without moving focus into it, Tab would never reach its links.
    await waitFor(() => {
      expect(popover).toContainElement(document.activeElement as HTMLElement | null);
    });
    const visited = new Set<string>();
    for (let step = 0; step < 4; step += 1) {
      visited.add(document.activeElement?.textContent ?? '');
      expect(popover).toContainElement(document.activeElement as HTMLElement | null);
      await user.tab();
    }
    expect(visited).toContain('run run_EXAMPLE');
    expect(visited).toContain('snapshot 1');

    await user.keyboard('{Escape}');
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
    expect(badge).toHaveFocus();
  });

  it('shows a merged record as merged into its survivor and unmerges it instead of undeleting', async () => {
    const { user, fetchMock } = renderDetail(
      project({ deleted_at: '2026-01-02T00:00:00.000000Z', deleted_by: 'user', merged_into: 'prj_SURVIVOR' }),
    );
    expect(await screen.findByText('This record is merged')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Example survivor' })).toHaveAttribute('href', '/projects/prj_SURVIVOR');
    expect(screen.queryByRole('button', { name: 'Undelete' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Merge…' })).toBeNull();

    const [unmerge] = screen.getAllByRole('button', { name: 'Unmerge…' });
    if (!unmerge) throw new Error('no Unmerge button');
    await user.click(unmerge);
    const dialog = within(await screen.findByRole('dialog', { name: 'Unmerge' }));
    await user.type(dialog.getByRole('textbox', { name: /Note/ }), 'Example unmerge note');
    await user.click(dialog.getByRole('button', { name: 'Unmerge' }));
    expect(await dialog.findByText(/is live again/)).toBeInTheDocument();
    await waitFor(() => {
      expect(callsTo(fetchMock, '/api/entities/project/prj_A/unmerge')).toHaveLength(1);
    });
    expect(jsonBody(callsTo(fetchMock, '/api/entities/project/prj_A/unmerge')[0]?.init)).toEqual({ note: 'Example unmerge note' });
  });
});
