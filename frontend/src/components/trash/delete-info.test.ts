import { describe, expect, it } from 'vitest';

import type { ChangeFeedItem } from '../../api/types';
import { deleteFeedRequest, deleteInfoByRow } from './delete-info';

const deletion = (id: number, entityId: string, batchId: string | null, note: string | null = null): ChangeFeedItem => ({
  id,
  entity_type: 'service',
  entity_id: entityId,
  entity_label: entityId,
  version: 3,
  at: '2026-10-28T10:00:00.000000Z',
  author: 'user',
  channel: 'ui',
  action: 'delete',
  note,
  changed_fields: ['deleted'],
  restored_from_version: null,
  batch_id: batchId,
  run_id: null,
  proposal_id: null,
  context: null,
});

describe('trash delete info', () => {
  it('requests the delete revisions around the deletion times of the rows', () => {
    expect(
      deleteFeedRequest([
        { id: 'prj_A', deleted_at: '2026-10-28T10:00:00.000000Z' },
        { id: 'prj_B', deleted_at: '2026-10-27T09:00:00.500000Z' },
        { id: 'prj_C', deleted_at: null },
      ]),
    ).toEqual({
      action: 'delete',
      since: '2026-10-27T08:59:00.500000Z',
      until: '2026-10-28T10:01:00.000000Z',
      page_size: '500',
    });
    expect(deleteFeedRequest([{ id: 'prj_C', deleted_at: null }])).toBeNull();
  });

  it('counts the other rows of a cascade and takes the newest deletion of each row', () => {
    const revisions = [
      deletion(9, 'svc_1', 'batch_2', 'Example cascade'),
      deletion(8, 'prj_A', 'batch_2', 'Example cascade'),
      deletion(7, 'svc_2', 'batch_2', 'Example cascade'),
      deletion(5, 'prj_B', 'batch_1'),
      // An older deletion of prj_A (undeleted since) does not count.
      deletion(3, 'prj_A', null, 'Older deletion'),
    ];
    const info = deleteInfoByRow(
      [
        { id: 'prj_A', deleted_at: '2026-10-28T10:00:00.000000Z' },
        { id: 'prj_B', deleted_at: '2026-10-28T09:00:00.000000Z' },
        { id: 'prj_C', deleted_at: '2026-10-28T08:00:00.000000Z' },
      ],
      revisions,
      true,
    );
    expect(info.get('prj_A')).toEqual({ batchId: 'batch_2', others: 2, exact: true, note: 'Example cascade' });
    expect(info.get('prj_B')).toEqual({ batchId: 'batch_1', others: 0, exact: true, note: null });
    expect(info.has('prj_C')).toBe(false);
    expect(deleteInfoByRow([{ id: 'prj_B', deleted_at: null }], revisions, false).get('prj_B')?.exact).toBe(false);
  });
});
