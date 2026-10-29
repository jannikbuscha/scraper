// Bulk edit (docs/API.md §3.2, docs/UI.md §3): the request with the row
// versions captured when the dialog opened, and per-row results that a retry
// of the conflicted rows updates.
import type { BulkRequest, BulkResult, BulkStatus, JsonObject, JsonValue } from '../api/types';

/** A selected row, with the version captured when the bulk dialog opened. */
export interface BulkTarget {
  id: string;
  label: string;
  version: number;
}

export type BulkOp = 'set' | 'add' | 'remove';

export interface BulkEdit {
  field: string;
  op: BulkOp;
  /** A value for `set`; a list of values for `add` and `remove`. */
  value: JsonValue;
  /** Further `set` values the rules demand, e.g. `scope_note` with `in_paper_scope`. */
  alongside?: JsonObject;
}

export function bulkRequest(targets: readonly BulkTarget[], edit: BulkEdit, note: string | null): BulkRequest {
  const items = targets.map((target) => ({ id: target.id, expected_version: target.version }));
  const alongside = edit.alongside ?? {};
  if (edit.op === 'set') return { items, set: { [edit.field]: edit.value, ...alongside }, note };
  const values = Array.isArray(edit.value) ? edit.value : [];
  const request: BulkRequest = { items, [edit.op]: { [edit.field]: values }, note };
  return Object.keys(alongside).length > 0 ? { ...request, set: alongside } : request;
}

/** The latest result per row: a retry replaces the results of the retried rows only. */
export function mergeBulkResults(
  previous: ReadonlyMap<string, BulkResult>,
  results: readonly BulkResult[],
): Map<string, BulkResult> {
  const next = new Map(previous);
  for (const result of results) next.set(result.id, result);
  return next;
}

export const BULK_STATUSES: readonly BulkStatus[] = ['updated', 'unchanged', 'conflict', 'entity_deleted', 'error'];

export function countBulkResults(results: ReadonlyMap<string, BulkResult>): Record<BulkStatus, number> {
  const counts: Record<BulkStatus, number> = { updated: 0, unchanged: 0, conflict: 0, entity_deleted: 0, error: 0 };
  for (const result of results.values()) counts[result.status] += 1;
  return counts;
}

/** Conflicted rows with their current versions, for "Retry with current versions". */
export function conflictRetryTargets(
  targets: readonly BulkTarget[],
  results: ReadonlyMap<string, BulkResult>,
): BulkTarget[] {
  return targets.flatMap((target) => {
    const result = results.get(target.id);
    return result?.status === 'conflict' && result.current_version !== null
      ? [{ ...target, version: result.current_version }]
      : [];
  });
}
