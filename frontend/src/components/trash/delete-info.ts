// "Deleted together with n others" (docs/UI.md §5). A cascading delete gives
// every deleted row the same `batch_id` on its delete revision (docs/DATA_MODEL
// §6.4). One feed request loads the delete revisions around the deletion times
// of a trash page; from them each row gets its batch, the size of the batch
// and the note of the deletion.
import type { ChangeFeedItem } from '../../api/types';
import { apiTimestamp, parseTimestamp } from '../../lib/format';
import type { SearchRecord } from '../../lib/query-string';

export interface DeletedRow {
  id: string;
  deleted_at: string | null;
}

export interface DeleteInfo {
  batchId: string | null;
  /** Rows deleted in the same batch besides this one (a cascade). */
  others: number;
  /** False if the feed was cut off: `others` is then a lower bound. */
  exact: boolean;
  note: string | null;
}

/** Margin around the deletion times: the rows of one cascade are written in one transaction. */
const WINDOW_MARGIN_MS = 60_000;

/** The most revisions one feed request returns (docs/API.md §1.4). */
const MAX_FEED_PAGE = 500;

/** The feed request for the delete revisions of `rows`, or null if no row has a deletion time. */
export function deleteFeedRequest(rows: readonly DeletedRow[]): SearchRecord | null {
  const times = rows.flatMap((row) => {
    const date = row.deleted_at === null ? null : parseTimestamp(row.deleted_at);
    return date ? [date.getTime()] : [];
  });
  if (times.length === 0) return null;
  return {
    action: 'delete',
    since: apiTimestamp(new Date(Math.min(...times) - WINDOW_MARGIN_MS)),
    until: apiTimestamp(new Date(Math.max(...times) + WINDOW_MARGIN_MS)),
    page_size: String(MAX_FEED_PAGE),
  };
}

/**
 * Delete info per row from the delete revisions of the window (newest first).
 * `complete` says whether the feed returned every revision of the window.
 */
export function deleteInfoByRow(
  rows: readonly DeletedRow[],
  revisions: readonly ChangeFeedItem[],
  complete: boolean,
): Map<string, DeleteInfo> {
  const deletes = revisions.filter((revision) => revision.action === 'delete');
  const batchSizes = new Map<string, number>();
  for (const { batch_id: batch } of deletes) if (batch !== null) batchSizes.set(batch, (batchSizes.get(batch) ?? 0) + 1);

  const info = new Map<string, DeleteInfo>();
  for (const row of rows) {
    // The newest delete revision of a row in the trash is its current deletion.
    const revision = deletes.find((candidate) => candidate.entity_id === row.id);
    if (!revision) continue;
    const batchId = revision.batch_id;
    info.set(row.id, {
      batchId,
      others: batchId === null ? 0 : Math.max(0, (batchSizes.get(batchId) ?? 1) - 1),
      exact: complete,
      note: revision.note,
    });
  }
  return info;
}
