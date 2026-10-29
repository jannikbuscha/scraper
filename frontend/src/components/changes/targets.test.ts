import { describe, expect, it } from 'vitest';

import type { ChangeFeedItem } from '../../api/types';
import { changeTarget, threadTarget } from './targets';

const change = (overrides: Partial<ChangeFeedItem>): ChangeFeedItem => ({
  id: 1,
  entity_type: 'project',
  entity_id: 'prj_A',
  entity_label: 'Example project A',
  version: 2,
  at: '2026-10-28T10:00:00.000000Z',
  author: 'Example Person',
  channel: 'ui',
  action: 'update',
  note: null,
  changed_fields: ['name_en'],
  restored_from_version: null,
  batch_id: null,
  context: null,
  ...overrides,
});

describe('record targets', () => {
  it('opens table types on their detail page', () => {
    expect(changeTarget(change({}))).toEqual({ kind: 'detail', type: 'project', id: 'prj_A', search: {} });
  });

  it('opens comments on their subject with the thread open', () => {
    const comment = change({
      entity_type: 'comment',
      entity_id: 'cmt_1',
      context: { subject_id: 'svc_B', subject_type: 'service', field: null },
    });
    expect(changeTarget(comment)).toEqual({
      kind: 'detail',
      type: 'service',
      id: 'svc_B',
      search: { comments: 'open', thread: 'cmt_1' },
    });
    expect(threadTarget('vocabulary_term', 'voc_1', 'cmt_2')).toEqual({
      kind: 'codebook',
      search: { term: 'voc_1', comments: 'open', thread: 'cmt_2' },
    });
    // A reply opens the thread of its root comment (context.parent_id).
    const reply = change({
      entity_type: 'comment',
      entity_id: 'cmt_reply',
      context: { subject_id: 'svc_B', subject_type: 'service', field: 'name_en', parent_id: 'cmt_root' },
    });
    expect(changeTarget(reply)).toEqual({
      kind: 'detail',
      type: 'service',
      id: 'svc_B',
      search: { comments: 'open', thread: 'cmt_root' },
    });
    // Comments on types without a page in Phase 1 have no target.
    expect(threadTarget('evidence', 'evd_1', 'cmt_3')).toBeNull();
    expect(changeTarget(change({ entity_type: 'comment', entity_id: 'cmt_4', context: null }))).toBeNull();
  });

  it('opens vocabulary terms on the Codebook page and saved views as their table', () => {
    expect(
      changeTarget(change({ entity_type: 'vocabulary_term', entity_id: 'voc_1', context: { vocabulary: 'example_cluster' } })),
    ).toEqual({ kind: 'codebook', search: { vocabulary: 'example_cluster', term: 'voc_1' } });
    expect(changeTarget(change({ entity_type: 'saved_view', entity_id: 'view_1', context: { entity_type: 'event' } }))).toEqual({
      kind: 'saved_view',
      id: 'view_1',
      tableType: 'event',
    });
    expect(changeTarget(change({ entity_type: 'relation', entity_id: 'rel_1' }))).toBeNull();
  });
});
