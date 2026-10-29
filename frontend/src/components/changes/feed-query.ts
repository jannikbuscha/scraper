// URL state of the Recent changes and Comments pages (docs/UI.md §5). The
// page URL keeps the filters under the API's parameter names (docs/API.md
// §3.3, §3.4); only the date range of Recent changes differs: the URL holds
// local days (`YYYY-MM-DD`), the request sends the first and the last instant
// of those days, because `since` and `until` are inclusive timestamps.
import { localDayEnd, localDayStart } from '../../lib/format';
import { isIsoDate } from '../../lib/partial-date';
import { splitList, type SearchRecord } from '../../lib/query-string';

/** List filters of GET /api/revisions, comma-separated in the URL and the request. */
const CHANGE_LIST_PARAMS = ['entity_type', 'channel', 'action'] as const;
export type ChangeListParam = (typeof CHANGE_LIST_PARAMS)[number];

/** Every filter of the Recent changes page (paging excluded). */
const CHANGE_FILTER_PARAMS: readonly string[] = [...CHANGE_LIST_PARAMS, 'since', 'until', 'batch_id'];

/** Filters of the Comments page: GET /api/comments without `subject_id`. */
const COMMENT_FILTER_PARAMS: readonly string[] = ['status', 'entity_type', 'q', 'deleted'];

const PAGING_PARAMS: readonly string[] = ['page', 'page_size'];

function keepKeys(search: SearchRecord, keys: readonly string[]): SearchRecord {
  return Object.fromEntries(Object.entries(search).filter(([key, value]) => keys.includes(key) && value !== ''));
}

/** The URL's `page` and `page_size`, for requests that add their own filters (trash). */
export const pagingParams = (search: SearchRecord): SearchRecord => keepKeys(search, PAGING_PARAMS);

/** Values of a comma-separated list parameter. */
export const listParam = (search: SearchRecord, key: string): string[] =>
  splitList(search[key] ?? '').filter((value) => value !== '');

/** Sets (or, when empty, removes) one parameter; every filter change returns to page 1. */
export function withParam(search: SearchRecord, key: string, value: string | null): SearchRecord {
  const next = Object.fromEntries(Object.entries(search).filter(([name]) => name !== key && name !== 'page'));
  if (value !== null && value !== '') next[key] = value;
  return next;
}

export const withListParam = (search: SearchRecord, key: string, values: readonly string[]): SearchRecord =>
  withParam(search, key, values.join(','));

/** A valid local day of the URL (`since`/`until`), else null. */
export function dayParam(search: SearchRecord, key: 'since' | 'until'): string | null {
  const value = search[key];
  return value !== undefined && isIsoDate(value) ? value : null;
}

/** The request of the change feed: the URL's filters and paging, local days as timestamps. */
export function changeFeedRequest(search: SearchRecord): SearchRecord {
  const request = keepKeys(search, [...CHANGE_LIST_PARAMS, 'batch_id', ...PAGING_PARAMS]);
  const since = dayParam(search, 'since');
  const until = dayParam(search, 'until');
  const start = since === null ? null : localDayStart(since);
  const end = until === null ? null : localDayEnd(until);
  if (start !== null) request.since = start;
  if (end !== null) request.until = end;
  return request;
}

export const hasChangeFilters = (search: SearchRecord): boolean =>
  Object.keys(keepKeys(search, CHANGE_FILTER_PARAMS)).length > 0;

/** Removes every filter (and the page), keeps the page size. */
export const clearFilterParams = (search: SearchRecord): SearchRecord => keepKeys(search, ['page_size']);

/** The request of the comment feed: exactly the URL's filters and paging. */
export const commentFeedRequest = (search: SearchRecord): SearchRecord =>
  keepKeys(search, [...COMMENT_FILTER_PARAMS, ...PAGING_PARAMS]);

export const hasCommentFilters = (search: SearchRecord): boolean =>
  Object.keys(keepKeys(search, COMMENT_FILTER_PARAMS)).length > 0;
