import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { FacetsResponse } from '../../../api/types';
import { EntityTablePage } from '../../../pages/EntityTablePage';
import { mockApi, requestsTo } from '../../../test/api-mock';
import { exampleItem, exampleMeta, exampleVocabularies, listResponse } from '../../../test/fixtures';
import { renderRoute } from '../../../test/render';

const FACETS: Record<string, FacetsResponse> = {
  paper_cluster: {
    field: 'paper_cluster',
    values: [
      { value: 'cluster_a', label: 'Example cluster A', count: 3 },
      { value: 'cluster_b', label: 'Example cluster B', count: 0 },
    ],
    empty_count: 2,
  },
  policy_domains: {
    field: 'policy_domains',
    values: [
      { value: 'domain_a', label: 'Example domain A', count: 1 },
      { value: 'domain_b', label: 'Example domain B', count: 4 },
    ],
    empty_count: 0,
  },
};

function mockProjectsApi() {
  return mockApi((url) => {
    if (url.pathname === '/api/meta') return exampleMeta;
    if (url.pathname === '/api/entities/saved_view') return listResponse([]);
    if (url.pathname === '/api/entities/project') {
      return listResponse([exampleItem('prj_A', { name_en: 'Example project A', verification_status: 'unverified' })]);
    }
    if (url.pathname === '/api/entities/project/facets') return FACETS[url.searchParams.get('field') ?? ''];
    return undefined;
  });
}

const ProjectsPage = () => <EntityTablePage type="project" />;

describe('multiselect filter popover', () => {
  it('loads facet counts when opened and applies the selection including (empty)', async () => {
    const fetchMock = mockProjectsApi();
    const { router, user } = renderRoute(ProjectsPage, {
      url: '/projects?f.paper_cluster=in:cluster_b&f.verification_status=in:unverified&page=2&sort=name_en',
      path: '/projects',
      vocabularies: exampleVocabularies,
    });

    const filterButton = await screen.findByRole('button', { name: 'Filter Paper cluster (active)' });
    // Facets are loaded lazily, only when the popover opens.
    expect(requestsTo(fetchMock, '/api/entities/project/facets')).toHaveLength(0);

    await user.click(filterButton);
    const optionA = await screen.findByRole('checkbox', { name: 'Example cluster A (3 rows)' });
    const facetRequests = requestsTo(fetchMock, '/api/entities/project/facets');
    expect(facetRequests).toHaveLength(1);
    // All filters apply except the field's own; paging and sort are irrelevant.
    expect(Object.fromEntries(facetRequests[0]?.searchParams ?? [])).toEqual({
      field: 'paper_cluster',
      'f.verification_status': 'in:unverified',
    });
    // The current URL filter is preselected.
    expect(screen.getByRole('checkbox', { name: 'Example cluster B (0 rows)' })).toBeChecked();
    expect(optionA).not.toBeChecked();

    await user.click(optionA);
    await user.click(screen.getByRole('checkbox', { name: '(empty) (2 rows)' }));
    await user.click(screen.getByRole('button', { name: 'Apply' }));

    // Values in facet order, the ~empty token last; a filter change returns to page 1.
    await waitFor(() => {
      expect(router.state.location.search).toEqual({
        'f.paper_cluster': 'in:cluster_a,cluster_b,~empty',
        'f.verification_status': 'in:unverified',
        sort: 'name_en',
      });
    });
  });

  it('offers any / all / none for list fields, where "all" cannot take (empty)', async () => {
    mockProjectsApi();
    const { router, user } = renderRoute(ProjectsPage, {
      url: '/projects',
      path: '/projects',
      vocabularies: exampleVocabularies,
    });

    await user.click(await screen.findByRole('button', { name: 'Filter Policy domains' }));
    const empty = await screen.findByRole('checkbox', { name: '(empty) (0 rows)' });
    expect(screen.queryByRole('radio', { name: 'is any of' })).toBeNull();

    await user.click(screen.getByRole('radio', { name: 'has all of' }));
    expect(empty).toBeDisabled();

    await user.click(screen.getByRole('radio', { name: 'has none of' }));
    expect(empty).toBeEnabled();
    await user.click(screen.getByRole('checkbox', { name: 'Example domain B (4 rows)' }));
    await user.click(screen.getByRole('button', { name: 'Apply' }));

    await waitFor(() => {
      expect(router.state.location.search).toEqual({ 'f.policy_domains': 'none:domain_b' });
    });
  });

  it('clears the field filter', async () => {
    mockProjectsApi();
    const { router, user } = renderRoute(ProjectsPage, {
      url: '/projects?f.paper_cluster=nin:cluster_a',
      path: '/projects',
      vocabularies: exampleVocabularies,
    });

    await user.click(await screen.findByRole('button', { name: 'Filter Paper cluster (active)' }));
    expect(await screen.findByRole('radio', { name: 'is none of' })).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Clear' }));

    await waitFor(() => {
      expect(router.state.location.searchStr).toBe('');
    });
  });
});
