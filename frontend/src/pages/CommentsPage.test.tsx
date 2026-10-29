import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { Comment, CommentFeedResponse } from '../api/types';
import { mockApi, requestsTo } from '../test/api-mock';
import { exampleMeta } from '../test/fixtures';
import { renderRoute } from '../test/render';
import { CommentsPage } from './CommentsPage';

const comment = (overrides: Partial<Comment>): Comment => ({
  id: 'cmt_1',
  subject_id: 'prj_A',
  subject_type: 'project',
  subject_label: 'Example project A',
  field: 'name_en',
  parent_id: null,
  body_md: 'Is the **example** name correct?',
  body_html: '<p>Is the <strong>example</strong> name correct?</p>',
  status: 'open',
  resolved_by: null,
  resolved_at: null,
  created_at: '2026-10-01T09:30:00.000000Z',
  created_by: 'Example Person',
  updated_at: '2026-10-01T09:30:00.000000Z',
  updated_by: 'Example Person',
  version: 1,
  edited: false,
  deleted_at: null,
  deleted_by: null,
  ...overrides,
});

const FEED: CommentFeedResponse = {
  items: [
    { root: comment({}), reply_count: 2, last_activity_at: '2026-10-02T10:00:00.000000Z' },
    {
      root: comment({
        id: 'cmt_2',
        subject_id: 'voc_1',
        subject_type: 'vocabulary_term',
        subject_label: 'example_cluster:cluster_a',
        field: null,
        body_md: 'Example question about the definition',
        status: 'resolved',
      }),
      reply_count: 0,
      last_activity_at: '2026-10-01T08:00:00.000000Z',
    },
  ],
  total: 2,
  page: 1,
  page_size: 50,
};

function mockCommentsApi() {
  return mockApi((url) => {
    if (url.pathname === '/api/meta') return exampleMeta;
    if (url.pathname === '/api/revisions/authors') return { authors: ['Example Person'] };
    if (url.pathname === '/api/comments') return FEED;
    return undefined;
  });
}

describe('Comments page', () => {
  it('requests the URL filters and links each thread to its subject with the thread open', async () => {
    const fetchMock = mockCommentsApi();
    const { router, user } = renderRoute(CommentsPage, {
      url: '/comments?status=open&entity_type=project&page=2',
      path: '/comments',
    });

    const projectThread = await screen.findByRole('link', { name: 'Is the **example** name correct?' });
    expect(requestsTo(fetchMock, '/api/comments').map((url) => Object.fromEntries(url.searchParams))).toEqual([
      { status: 'open', entity_type: 'project', page: '2' },
    ]);
    expect(projectThread).toHaveAttribute('href', '/projects/prj_A?comments=open&thread=cmt_1');
    // Vocabulary terms open the Codebook page.
    expect(screen.getByRole('link', { name: 'Example question about the definition' })).toHaveAttribute(
      'href',
      '/codebook?comments=open&term=voc_1&thread=cmt_2',
    );
    expect(screen.getByRole('link', { name: 'Example project A' })).toHaveAttribute('href', '/projects/prj_A');
    expect(screen.getByText('Name (EN)')).toHaveAttribute('title', 'name_en');
    expect(screen.getByText('whole record')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Open' })).toBeChecked();

    await user.click(screen.getByRole('radio', { name: 'Resolved' }));
    await waitFor(() => {
      expect(router.state.location.search).toEqual({ status: 'resolved', entity_type: 'project' });
    });

    // A click elsewhere in a row opens the thread as well.
    const row = screen.getByRole('row', { name: /Is the \*\*example\*\* name correct/ });
    await user.click(within(row).getByText('Example Person'));
    await waitFor(() => {
      expect(router.state.location.href).toBe('/projects/prj_A?comments=open&thread=cmt_1');
    });
  });
});
