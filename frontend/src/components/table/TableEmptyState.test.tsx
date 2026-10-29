import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { EntityTablePage } from '../../pages/EntityTablePage';
import { mockApi } from '../../test/api-mock';
import { exampleMeta, exampleVocabularies, listResponse } from '../../test/fixtures';
import { renderRoute } from '../../test/render';

const ProjectsPage = () => <EntityTablePage type="project" />;

function mockEmptyProjects() {
  return mockApi((url) => {
    if (url.pathname === '/api/meta') return exampleMeta;
    if (url.pathname === '/api/entities/saved_view') return listResponse([]);
    // The filters match no rows.
    if (url.pathname === '/api/entities/project') return listResponse([]);
    if (url.pathname === '/api/entities/project/facets') return { field: 'paper_cluster', values: [], empty_count: 0 };
    return undefined;
  });
}

describe('empty table', () => {
  it('keeps the header with the column filters and removes one filter at a time', async () => {
    mockEmptyProjects();
    const { router, user } = renderRoute(ProjectsPage, {
      url: '/projects?f.paper_cluster=in:cluster_a&f.verification_status=in:verified&q=example',
      path: '/projects',
      vocabularies: exampleVocabularies,
    });

    expect(await screen.findByText('No projects match the current filters')).toBeInTheDocument();
    // Each column filter can still be opened and relaxed.
    expect(screen.getByRole('button', { name: 'Filter Paper cluster (active)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Filter Verification (active)' })).toBeInTheDocument();

    const active = screen.getByRole('list', { name: 'Active filters' });
    expect(within(active).getAllByRole('listitem')).toHaveLength(3);
    await user.click(within(active).getByRole('button', { name: /^Remove: Verification/ }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ 'f.paper_cluster': 'in:cluster_a', q: 'example' });
    });
    await user.click(within(screen.getByRole('list', { name: 'Active filters' })).getByRole('button', { name: /^Remove: Search/ }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ 'f.paper_cluster': 'in:cluster_a' });
    });
  });
});
