import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { callsTo, jsonBody, mockApi } from '../../test/api-mock';
import { exampleItem } from '../../test/fixtures';
import { renderRoute } from '../../test/render';
import { SaveViewModal } from './SaveViewModal';

const noop = () => undefined;

describe('SaveViewModal', () => {
  it('does not offer to save the default view, whose query would be empty', async () => {
    const fetchMock = mockApi(() => undefined);
    const Page = () => <SaveViewModal opened onClose={noop} type="project" query="" />;
    renderRoute(Page, { url: '/projects', path: '/projects' });

    expect(await screen.findByText(/This is the default view/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save view' })).toBeDisabled();
    expect(callsTo(fetchMock, '/api/entities/saved_view')).toHaveLength(0);
  });

  it('saves a non-default view with its canonical query', async () => {
    const fetchMock = mockApi((url, init) => {
      if (url.pathname === '/api/entities/saved_view' && init?.method === 'POST') {
        return { item: exampleItem('view_A', { name: 'Example view' }, { type: 'saved_view' }), revision_id: 1, warnings: [] };
      }
      return undefined;
    });
    const Page = () => <SaveViewModal opened onClose={noop} type="project" query="f.paper_cluster=in%3Acluster_a&sort=name_en" />;
    const { user } = renderRoute(Page, { url: '/projects', path: '/projects' });

    await user.type(await screen.findByRole('textbox', { name: 'Name' }), 'Example view');
    await user.click(screen.getByRole('button', { name: 'Save view' }));
    await waitFor(() => {
      expect(callsTo(fetchMock, '/api/entities/saved_view')).toHaveLength(1);
    });
    const [call] = callsTo(fetchMock, '/api/entities/saved_view');
    expect(jsonBody(call?.init)).toEqual({
      data: { name: 'Example view', entity_type: 'project', query: 'f.paper_cluster=in%3Acluster_a&sort=name_en', description: null },
    });
  });
});
