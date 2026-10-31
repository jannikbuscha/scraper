import { describe, expect, it } from 'vitest';

import type { RevisionSummary } from '../../api/types';
import { deleteInfoOf } from './UndeleteEntityModal';

const revision = (overrides: Partial<RevisionSummary>): RevisionSummary => ({
  id: 7,
  version: 4,
  at: '2026-01-03T08:00:00.000000Z',
  author: 'user',
  channel: 'ui',
  action: 'delete',
  note: 'Example note',
  changed_fields: ['deleted'],
  restored_from: null,
  restored_from_version: null,
  batch_id: 'batch_A',
  run_id: null,
  proposal_id: null,
  ...overrides,
});

describe('delete info of a deleted record', () => {
  it('counts the other rows of the delete batch', () => {
    expect(deleteInfoOf(revision({}), 3)).toEqual({ batchId: 'batch_A', others: 2, exact: true, note: 'Example note' });
    expect(deleteInfoOf(revision({}), 1)).toEqual({ batchId: 'batch_A', others: 0, exact: true, note: 'Example note' });
  });

  it('is unknown while loading or when the latest revision is not a deletion', () => {
    expect(deleteInfoOf(undefined, undefined)).toBeUndefined();
    expect(deleteInfoOf(revision({}), undefined)).toBeUndefined();
    expect(deleteInfoOf(revision({ action: 'update' }), 3)).toBeUndefined();
  });

  it('treats a deletion without batch as a single one', () => {
    expect(deleteInfoOf(revision({ batch_id: null }), undefined)).toEqual({
      batchId: null,
      others: 0,
      exact: true,
      note: 'Example note',
    });
  });
});
