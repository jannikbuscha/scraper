import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useCommentThreads } from '../../api/queries';
import type { Comment, ConflictPayload } from '../../api/types';
import { AUTHOR_STORAGE_KEY } from '../../lib/author';
import { callsTo, jsonBody, mockApi } from '../../test/api-mock';
import { renderRoute } from '../../test/render';
import { CommentCard } from './CommentCard';

// Synthetic comment texts and names; nothing here describes the real portfolio.
const SUBJECT = 'prj_EXAMPLE';
const COMMENT_PATH = '/api/comments/cmt_EXAMPLE';

/** The comment on the "server"; tests change it to simulate a colleague. */
let server: Comment;

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
  created_by: 'Example Colleague',
  updated_at: '2026-01-02T10:00:00.000000Z',
  updated_by: 'Example Colleague',
  version: 1,
  edited: false,
  deleted_at: null,
  deleted_by: null,
  ...overrides,
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function conflict(base: Comment, current: Comment): Response {
  const payload: ConflictPayload = {
    action: 'comment',
    entity_type: 'comment',
    entity_id: current.id,
    base_version: base.version,
    current_version: current.version,
    base: { body_md: base.body_md },
    current: { body_md: current.body_md },
    base_state: { deleted_at: null, deleted_by: null },
    current_state: { deleted_at: null, deleted_by: null },
    changed_since_base: ['body_md'],
    your_changes: {},
    conflicting_fields: ['body_md'],
    meta_changed_since_base: {},
    intervening: [
      {
        id: 20,
        version: current.version,
        at: current.updated_at,
        author: current.updated_by,
        channel: 'ui',
        action: 'update',
        note: null,
        changed_fields: ['body_md'],
        restored_from: null,
        restored_from_version: null,
        batch_id: null,
      },
    ],
    refs: {},
  };
  return json({ error: { code: 'conflict', message: 'The comment was changed.', details: payload } }, 409);
}

/** Answers like the server: a PATCH with an outdated version is refused with 409. */
function mockCommentApi() {
  const original = server;
  return mockApi((url, init) => {
    if (url.pathname === '/api/comments') return { threads: [{ root: server, replies: [] }] };
    if (url.pathname === COMMENT_PATH && init?.method === 'PATCH') {
      const body = jsonBody(init) as { expected_version: number; body_md: string };
      if (body.expected_version !== server.version) return conflict(original, server);
      server = comment({ ...server, body_md: body.body_md, version: server.version + 1, updated_by: 'Example Person' });
      return { comment: server, changed: true, revision_id: 30 };
    }
    return undefined;
  });
}

/** One thread of the subject, as the comments panel shows it (refetched by the query). */
function ThreadHarness() {
  const threads = useCommentThreads(SUBJECT);
  const root = threads.data?.threads[0]?.root;
  return root ? <CommentCard comment={root} fieldLabel={null} maxChars={10000} maxNoteChars={2000} /> : <p>Loading</p>;
}

const patchBodies = (fetchMock: ReturnType<typeof mockCommentApi>) =>
  callsTo(fetchMock, COMMENT_PATH)
    .filter((call) => call.init?.method === 'PATCH')
    .map((call) => jsonBody(call.init));

beforeEach(() => {
  window.localStorage.setItem(AUTHOR_STORAGE_KEY, 'Example Person');
  server = comment({});
});

describe('comment editor', () => {
  it('keeps the version it started from through a refetch, so a newer edit opens the conflict dialog', async () => {
    const fetchMock = mockCommentApi();
    const { user, queryClient } = renderRoute(ThreadHarness, { url: '/', path: '/' });
    await user.click(await screen.findByRole('button', { name: 'Edit comment' }));
    const editor = screen.getByRole('textbox', { name: 'Edit comment' });
    await user.clear(editor);
    await user.type(editor, 'My example edit');

    // A colleague edits the comment; a background refetch brings version 2.
    server = comment({
      body_md: 'Their example edit',
      body_html: '<p>Their example edit</p>',
      version: 2,
      updated_by: 'Example Colleague',
      updated_at: '2026-01-03T10:00:00.000000Z',
      edited: true,
    });
    await queryClient.invalidateQueries({ queryKey: ['comments'] });
    expect(await screen.findByText(/saving will open the conflict dialog/)).toBeInTheDocument();
    // The typed text survives the refetch.
    expect(screen.getByRole('textbox', { name: 'Edit comment' })).toHaveValue('My example edit');

    await user.click(screen.getByRole('button', { name: 'Save' }));
    const dialog = await screen.findByRole('dialog', { name: 'The comment was changed meanwhile' });
    expect(within(dialog).getByText('Example Colleague')).toBeInTheDocument();
    // Nothing was overwritten: the first PATCH carried the version editing started from.
    expect(patchBodies(fetchMock)).toEqual([{ expected_version: 1, body_md: 'My example edit', note: null }]);
    expect(server.body_md).toBe('Their example edit');

    await user.click(within(dialog).getByRole('button', { name: 'Save my version' }));
    await waitFor(() => {
      expect(patchBodies(fetchMock)).toHaveLength(2);
    });
    // Resent against the current version only after the confirmation.
    expect(patchBodies(fetchMock)[1]).toEqual({ expected_version: 2, body_md: 'My example edit', note: null });
    await waitFor(() => {
      expect(screen.queryByRole('textbox', { name: 'Edit comment' })).toBeNull();
    });
  });

  it('discarding in the conflict dialog keeps their text', async () => {
    const fetchMock = mockCommentApi();
    const { user } = renderRoute(ThreadHarness, { url: '/', path: '/' });
    await user.click(await screen.findByRole('button', { name: 'Edit comment' }));
    await user.type(screen.getByRole('textbox', { name: 'Edit comment' }), ' with my addition');

    // The colleague's edit arrives without any refetch on this page.
    server = comment({ body_md: 'Their example edit', version: 2, updated_by: 'Example Colleague' });
    await user.click(screen.getByRole('button', { name: 'Save' }));
    const dialog = await screen.findByRole('dialog', { name: 'The comment was changed meanwhile' });
    await user.click(within(dialog).getByRole('button', { name: 'Discard my edit' }));

    await waitFor(() => {
      expect(screen.queryByRole('textbox', { name: 'Edit comment' })).toBeNull();
    });
    expect(patchBodies(fetchMock)).toHaveLength(1);
    expect(server.body_md).toBe('Their example edit');
  });
});
