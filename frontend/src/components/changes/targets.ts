// Where a record opens in the UI (docs/UI.md §5): table types on their detail
// page, the record-page types (evidence, participations, components,
// relations, indicators, saved views) on the generic record page
// `/records/$id`, comments on their subject's page with the thread open,
// vocabulary terms on the Codebook page; in the change feed, saved views open
// as their table with the view applied.
import type { ChangeFeedItem, RecordType, TableEntityType } from '../../api/types';
import { isRecordPageType, isTableType } from '../../lib/entity';
import type { SearchRecord } from '../../lib/query-string';

/** A page reached by route path, params and search. */
export type PageTarget =
  | { kind: 'detail'; type: TableEntityType; id: string; search: SearchRecord }
  /** The generic record page `/records/$id`. */
  | { kind: 'record'; id: string; search: SearchRecord }
  | { kind: 'codebook'; search: SearchRecord };

export type RecordTarget =
  | PageTarget
  /** The view's stored query is loaded when the link renders. */
  | { kind: 'saved_view'; id: string; tableType: TableEntityType };

/** A vocabulary term on the Codebook page; `vocabulary` selects its list if known. */
function termTarget(termId: string, vocabulary?: string | null, extra: SearchRecord = {}): PageTarget {
  return { kind: 'codebook', search: { ...(vocabulary ? { vocabulary } : {}), term: termId, ...extra } };
}

/** The page of a record (vocabulary terms: the Codebook page), with optional search params. */
export function pageTarget(type: RecordType, id: string, search: SearchRecord = {}): PageTarget | null {
  if (isTableType(type)) return { kind: 'detail', type, id, search };
  if (isRecordPageType(type)) return { kind: 'record', id, search };
  if (type === 'vocabulary_term') return termTarget(id, null, search);
  return null;
}

/** A comment thread opens on its subject's page with the comments panel open. */
export const threadTarget = (subjectType: RecordType, subjectId: string, threadId: string): PageTarget | null =>
  pageTarget(subjectType, subjectId, { comments: 'open', thread: threadId });

/** The target of a change-feed row (its `context` names comment subjects, vocabularies and view tables). */
export function changeTarget(change: ChangeFeedItem): RecordTarget | null {
  const { entity_type: type, entity_id: id, context } = change;
  if (isTableType(type)) return { kind: 'detail', type, id, search: {} };
  if (type === 'comment') {
    // A reply opens its thread, i.e. the root comment.
    return context?.subject_type && context.subject_id
      ? threadTarget(context.subject_type, context.subject_id, context.parent_id ?? id)
      : null;
  }
  if (type === 'vocabulary_term') return termTarget(id, context?.vocabulary);
  if (type === 'saved_view' && isTableType(context?.entity_type)) {
    return { kind: 'saved_view', id, tableType: context.entity_type };
  }
  return pageTarget(type, id);
}
