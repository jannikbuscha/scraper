import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { EntityTablePage } from '../../pages/EntityTablePage';
import type { EntityTypeMeta } from '../../api/types';
import { mockApi, requestsTo } from '../../test/api-mock';
import { exampleItem, exampleMeta, exampleVocabularies, fieldSpec, listResponse, projectMeta } from '../../test/fixtures';
import { renderRoute } from '../../test/render';

const rows = [
  exampleItem('prj_A', { name_en: 'Example project A', paper_cluster: 'cluster_a', verification_status: 'unverified' }),
  exampleItem('prj_B', { name_en: 'Example project B', paper_cluster: null, verification_status: 'verified' }),
];

function mockProjectsApi() {
  return mockApi((url) => {
    if (url.pathname === '/api/meta') return exampleMeta;
    if (url.pathname === '/api/entities/saved_view') return listResponse([]);
    if (url.pathname === '/api/entities/project') return listResponse(rows);
    return undefined;
  });
}

const ProjectsPage = () => <EntityTablePage type="project" />;
const EventsPage = () => <EntityTablePage type="event" />;

// The server sends the period presets as one quick filter with a `presets` list.
const eventMeta: EntityTypeMeta = {
  ...projectMeta,
  label: 'Event',
  label_plural: 'Events',
  prefix: 'evt',
  default_sort: '-date',
  constraints: [],
  fields: [fieldSpec('date', 'partial_date', { label: 'Date', filter: 'date_range', sortable: true, in_list: true })],
  quick_filters: [
    {
      key: 'period',
      label: 'Period',
      kind: 'preset',
      field: 'date',
      presets: [
        { key: 'pre_ministry', label: 'Example before', query: 'f.date=within:..1999-12-31' },
        { key: 'pre_invasion', label: 'Example between', query: 'f.date=within:2000-01-01..2000-12-31' },
        { key: 'full_scale_war', label: 'Example after', query: 'f.date=within:2001-01-01..' },
      ],
    },
  ],
};

describe('table toolbar quick filters', () => {
  it('activating a toggle replaces the filter on its field; deactivating removes it', async () => {
    const fetchMock = mockProjectsApi();
    const { router, user } = renderRoute(ProjectsPage, {
      url: '/projects?f.verification_status=in:verified&page=2&sort=name_en',
      path: '/projects',
      vocabularies: exampleVocabularies,
    });

    const toggle = await screen.findByRole('checkbox', { name: 'Unverified' });
    // `in:verified` is not the toggle's exact key/value pair.
    expect(toggle).not.toBeChecked();

    await user.click(toggle);
    await waitFor(() => {
      expect(router.state.location.searchStr).toBe('?f.verification_status=in%3Aunverified&sort=name_en');
    });
    expect(toggle).toBeChecked();
    // The URL is the API query: the list is requested with the same string.
    await waitFor(() => {
      expect(requestsTo(fetchMock, '/api/entities/project').map((url) => url.search)).toContain(
        '?f.verification_status=in%3Aunverified&sort=name_en',
      );
    });

    await user.click(toggle);
    await waitFor(() => {
      expect(router.state.location.searchStr).toBe('?sort=name_en');
    });
    expect(toggle).not.toBeChecked();
  });

  it('writes the period chips as one in: list in vocabulary order', async () => {
    mockProjectsApi();
    const { router, user } = renderRoute(ProjectsPage, {
      url: '/projects',
      path: '/projects',
      vocabularies: exampleVocabularies,
    });

    await user.click(await screen.findByRole('checkbox', { name: 'Example period B' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ 'f.period': 'in:period_b' });
    });

    await user.click(screen.getByRole('checkbox', { name: 'Example period A' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ 'f.period': 'in:period_a,period_b' });
    });

    await user.click(screen.getByRole('checkbox', { name: 'Example period B' }));
    await user.click(screen.getByRole('checkbox', { name: 'Example period A' }));
    await waitFor(() => {
      expect(router.state.location.searchStr).toBe('');
    });
  });

  it('renders one group of mutually exclusive period presets from the server list', async () => {
    mockApi((url) => {
      if (url.pathname === '/api/meta') return { ...exampleMeta, entity_types: { event: eventMeta } };
      if (url.pathname === '/api/entities/saved_view') return listResponse([]);
      if (url.pathname === '/api/entities/event') return listResponse([]);
      return undefined;
    });
    const { router, user } = renderRoute(EventsPage, { url: '/events', path: '/events', vocabularies: exampleVocabularies });

    const group = await screen.findByRole('group', { name: 'Period' });
    expect(within(group).getAllByRole('checkbox')).toHaveLength(3);
    expect(screen.getAllByRole('checkbox', { name: 'Example before' })).toHaveLength(1);

    await user.click(screen.getByRole('checkbox', { name: 'Example between' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ 'f.date': 'within:2000-01-01..2000-12-31' });
    });
    // Another preset replaces the filter on the same field.
    await user.click(screen.getByRole('checkbox', { name: 'Example after' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ 'f.date': 'within:2001-01-01..' });
    });
    expect(screen.getByRole('checkbox', { name: 'Example between' })).not.toBeChecked();
  });
});
