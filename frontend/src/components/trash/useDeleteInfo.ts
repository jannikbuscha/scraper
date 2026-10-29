// Delete info (batch, cascade size, note) for the rows of a trash page, from
// one request for the delete revisions around their deletion times. The query
// lives under the `changes` key, so every write refreshes it.
import { useChangeFeed } from '../../api/queries';
import { deleteFeedRequest, deleteInfoByRow, type DeletedRow, type DeleteInfo } from './delete-info';

/** Undefined while loading (or if the rows have no deletion times). */
export function useDeleteInfo(rows: readonly DeletedRow[]): ReadonlyMap<string, DeleteInfo> | undefined {
  const request = deleteFeedRequest(rows);
  const feed = useChangeFeed(request ?? {}, { enabled: request !== null, keepPrevious: false });
  if (request === null || !feed.data) return undefined;
  return deleteInfoByRow(rows, feed.data.items, feed.data.total <= feed.data.items.length);
}
