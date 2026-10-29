// Undelete from the detail page (docs/UI.md §4): the shared undelete dialog
// (components/trash/UndeleteEntityModal) with the record's delete info. The
// latest revision of a deleted row is its delete revision; the change feed of
// its batch counts the rows deleted together with it (a cascade).
import { useChangeFeed, useMeta, useRevisions } from '../../api/queries';
import type { Item, Meta, RevisionSummary, TableEntityType } from '../../api/types';
import type { DeleteInfo } from '../trash/delete-info';
import { UndeleteEntityModal as SharedUndeleteEntityModal } from '../trash/UndeleteEntityModal';
import { HISTORY_PAGE_SIZE } from './history-constants';

interface UndeleteEntityModalProps {
  type: TableEntityType;
  item: Item;
  opened: boolean;
  onClose: () => void;
}

export function UndeleteEntityModal({ type, item, opened, onClose }: UndeleteEntityModalProps) {
  const meta = useMeta();
  if (!opened || !meta.data) return null;
  return <WithDeleteInfo type={type} item={item} meta={meta.data} onClose={onClose} />;
}

/** Undefined while unknown; `total` is the size of the delete batch. */
export function deleteInfoOf(latest: RevisionSummary | undefined, total: number | undefined): DeleteInfo | undefined {
  if (latest?.action !== 'delete') return undefined;
  if (latest.batch_id === null) return { batchId: null, others: 0, exact: true, note: latest.note };
  if (total === undefined) return undefined;
  return { batchId: latest.batch_id, others: Math.max(0, total - 1), exact: true, note: latest.note };
}

function WithDeleteInfo({ type, item, meta, onClose }: { type: TableEntityType; item: Item; meta: Meta; onClose: () => void }) {
  // Same query as the history tab's first page, so the cache is shared.
  const revisions = useRevisions(type, item.id, 1, HISTORY_PAGE_SIZE);
  const latest = revisions.data?.items[0];
  const batchId = latest?.action === 'delete' ? latest.batch_id : null;
  const batch = useChangeFeed({ batch_id: batchId ?? '', page_size: '1' }, { enabled: batchId !== null, keepPrevious: false });
  const info = deleteInfoOf(latest, batchId === null ? undefined : batch.data?.total);
  return <SharedUndeleteEntityModal target={{ type, item, info }} meta={meta} onClose={onClose} />;
}
