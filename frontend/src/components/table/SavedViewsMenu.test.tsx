import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { EntityTablePage } from '../../pages/EntityTablePage';
import { mockApi } from '../../test/api-mock';
import { exampleItem, exampleMeta, exampleVocabularies, listResponse } from '../../test/fixtures';
import { renderRoute } from '../../test/render';

/** Many synthetic views of the team: more than fit into a window. */
const views = Array.from({ length: 40 }, (_, index) =>
  exampleItem(
    `view_${index}`,
    {
      name: `Example view ${String(index + 1).padStart(2, '0')}`,
      entity_type: 'project',
      query: `f.paper_cluster=in%3Acluster_a&page_size=${index + 25}`,
      description: 'A synthetic description of the view.',
    },
    { type: 'saved_view' },
  ),
);

describe('saved views menu', () => {
  it('scrolls a long list inside the dropdown and keeps "Save current view…" outside it', async () => {
    mockApi((url) => {
      if (url.pathname === '/api/meta') return exampleMeta;
      if (url.pathname === '/api/entities/saved_view') return listResponse(views);
      if (url.pathname === '/api/entities/project') return listResponse([]);
      return undefined;
    });
    const { user } = renderRoute(() => <EntityTablePage type="project" />, {
      url: '/projects',
      path: '/projects',
      vocabularies: exampleVocabularies,
    });
    await user.click(await screen.findByRole('button', { name: 'Saved views' }));

    const list = await screen.findByRole('list', { name: 'Saved views' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(40);
    // The list sits in a scroll area (its viewport scrolls; jsdom has no layout to measure).
    const viewport = list.closest('.mantine-ScrollArea-viewport');
    expect(viewport).not.toBeNull();
    // The save action is not part of the scrolled list: it stays visible below it.
    const save = screen.getByRole('button', { name: 'Save current view…' });
    expect(viewport?.contains(save)).toBe(false);
  });
});
