import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { Item } from '../../api/types';
import { callsTo, jsonBody, mockApi } from '../../test/api-mock';
import { exampleItem } from '../../test/fixtures';
import { renderRoute } from '../../test/render';
import { linkActions, linksAfter, linksWithAdded, asDocLinks } from './doc-links';
import { DocumentLinksPanel } from './DocumentLinksPanel';

const LINKS = [
  { subject_id: 'prj_A', origin: 'auto', state: 'suggested', matched_aliases: ['Example A'], match_count: 2, snippet: 'about Example A' },
  { subject_id: 'prj_B', origin: 'manual', state: 'confirmed', matched_aliases: [], match_count: 0, snippet: null },
  { subject_id: 'svc_C', origin: 'auto', state: 'rejected', matched_aliases: ['Example C'], match_count: 1, snippet: 'Example C' },
];

const documentItem = (): Item =>
  exampleItem(
    'doc_X',
    { title: 'Example document', links: LINKS },
    {
      type: 'document',
      label: 'Example document',
      refs: {
        'links.prj_A': { id: 'prj_A', type: 'project', label: 'Example project A', deleted: false },
        'links.prj_B': { id: 'prj_B', type: 'project', label: 'Example project B', deleted: false },
        'links.svc_C': { id: 'svc_C', type: 'service', label: 'Example service C', deleted: false },
      },
    },
  );

function renderPanel() {
  const item = documentItem();
  const fetchMock = mockApi((url, init) =>
    url.pathname === '/api/entities/document/doc_X' && init?.method === 'PATCH'
      ? { item, changed: true, revision_id: 9, warnings: [] }
      : undefined,
  );
  const Page = () => <DocumentLinksPanel item={item} />;
  const rendered = renderRoute(Page, { url: '/documents/doc_X', path: '/documents/$id' });
  const sentLinks = () =>
    callsTo(fetchMock, '/api/entities/document/doc_X')
      .filter((call) => call.init?.method === 'PATCH')
      .map((call) => (jsonBody(call.init) as { changes: { links: unknown[] } }).changes.links);
  return { ...rendered, sentLinks };
}

describe('document links (docs/UI.md §8.7)', () => {
  it('offers Confirm and Reject for suggestions and never Remove for automatic links', () => {
    expect(linkActions({ origin: 'auto', state: 'suggested' })).toEqual(['confirm', 'reject']);
    expect(linkActions({ origin: 'auto', state: 'rejected' })).toEqual(['confirm']);
    expect(linkActions({ origin: 'auto', state: 'confirmed' })).toEqual(['reject']);
    expect(linkActions({ origin: 'manual', state: 'confirmed' })).toEqual(['remove']);
    const links = asDocLinks(LINKS);
    // Removing applies to manual links only.
    expect(linksAfter(links, 'prj_A', 'remove')).toHaveLength(3);
    expect(linksAfter(links, 'prj_B', 'remove').map((link) => link.subject_id)).toEqual(['prj_A', 'svc_C']);
    expect(linksWithAdded(links, 'prj_A')).toBeNull();
    expect(linksWithAdded(links, 'prj_D')?.at(-1)).toEqual({ subject_id: 'prj_D', origin: 'manual', state: 'confirmed' });
  });

  it('confirming sends the full list with only that link changed', async () => {
    const { user, sentLinks } = renderPanel();
    const row = (await screen.findByRole('link', { name: 'Example project A' })).closest('tr');
    if (!row) throw new Error('no row');
    expect(within(row).queryByRole('button', { name: /^Remove/ })).toBeNull();
    await user.click(within(row).getByRole('button', { name: 'Confirm the link to Example project A' }));
    await waitFor(() => {
      expect(sentLinks()).toHaveLength(1);
    });
    expect(sentLinks()[0]).toEqual([{ ...LINKS[0], state: 'confirmed' }, LINKS[1], LINKS[2]]);
  });

  it('rejecting a suggestion keeps every other link as it is; automatic links offer no Remove', async () => {
    const { user, sentLinks } = renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Reject the link to Example project A' }));
    await waitFor(() => {
      expect(sentLinks()).toHaveLength(1);
    });
    expect(sentLinks()[0]).toEqual([{ ...LINKS[0], state: 'rejected' }, LINKS[1], LINKS[2]]);
    expect(screen.queryByRole('button', { name: 'Remove the link to Example service C' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Remove the link to Example project B' })).toBeInTheDocument();
  });
});
