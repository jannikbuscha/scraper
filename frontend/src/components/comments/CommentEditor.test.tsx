import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useCommentThreads } from '../../api/queries';
import type { Comment } from '../../api/types';
import { callsTo, jsonBody, mockApi } from '../../test/api-mock';
import { renderRoute } from '../../test/render';
import { CommentCard } from './CommentCard';

// Synthetic comment texts; nothing here describes the real portfolio.
const SUBJECT = 'prj_EXAMPLE';
const COMMENT_PATH = '/api/comments/cmt_EXAMPLE';

const comment = (overrides: Partial<Comment>): Comment => ({
  id: 'cmt_EXAMPLE',
  subject_id: SUBJECT,
  subject_type: 'project',
  subject_label: 'Example project',
  field: null,
  parent_id: null,
  body_md: 'Original example text',
  body_html: '<p>Original example text</p>',
  status: 'open',
  resolved_by: null,
  resolved_at: null,
  created_at: '2026-01-02T10:00:00.000000Z',
  created_by: 'user',
  updated_at: '2026-01-02T10:00:00.000000Z',
  updated_by: 'user',
  version: 1,
  edited: false,
  deleted_at: null,
  deleted_by: null,
  ...overrides,
});

/** One thread of the subject, as the comments panel shows it. */
function ThreadHarness() {
  const threads = useCommentThreads(SUBJECT);
  const root = threads.data?.threads[0]?.root;
  return root ? <CommentCard comment={root} fieldLabel={null} maxChars={10000} maxNoteChars={2000} /> : <p>Loading</p>;
}

describe('comment editor', () => {
  it('saves the edited text and closes', async () => {
    let server = comment({});
    const fetchMock = mockApi((url, init) => {
      if (url.pathname === '/api/comments') return { threads: [{ root: server, replies: [] }] };
      if (url.pathname === COMMENT_PATH && init?.method === 'PATCH') {
        const body = jsonBody(init) as { body_md: string };
        server = comment({ body_md: body.body_md, body_html: `<p>${body.body_md}</p>`, version: 2, edited: true });
        return { comment: server };
      }
      return undefined;
    });
    const { user } = renderRoute(ThreadHarness, { url: '/', path: '/' });
    await user.click(await screen.findByRole('button', { name: 'Edit comment' }));
    const editor = screen.getByRole('textbox', { name: 'Edit comment' });
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    await user.clear(editor);
    await user.type(editor, 'My example edit');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.queryByRole('textbox', { name: 'Edit comment' })).toBeNull();
    });
    const patches = callsTo(fetchMock, COMMENT_PATH).filter((call) => call.init?.method === 'PATCH');
    expect(patches.map((call) => jsonBody(call.init))).toEqual([{ body_md: 'My example edit', note: null }]);
    expect(await screen.findByText('My example edit')).toBeInTheDocument();
  });
});
